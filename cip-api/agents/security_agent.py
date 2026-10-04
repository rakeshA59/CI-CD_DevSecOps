"""
Security Agent.

Runs the scanners through the Scanner MCP server in parallel – SAST (Semgrep, Bandit, CodeQL), lint (Ruff, ESLint),
dependencies (Trivy, OSV-Scanner, pip-audit, npm audit, Snyk), secrets (Gitleaks, TruffleHog) and platforms
(SonarQube, GitHub Dependabot / code / secret scanning alerts). Which ones run: the run options' `scanners`, else
the defaults for the languages the planner found (+ the token / server based ones that are configured).
Then – with an LLM – it triages the serious findings. The security gate itself is a fixed threshold check.
"""

import asyncio
import re
import time
from typing import List

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from agent_states.pipeline_state import PipelineState
from llmapi.llm_provider import LLMProvider
from llmapi.structured_llm import ask_structured
from mcp_services.mcp_clients.mcp_tool_client import scanner_client
from mcp_services.mcp_servers.scanner_mcp.scanners import CATALOG, default_scanners
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.quality_gates import security_gate

RULESETS = {"Python": "p/python", "JavaScript": "p/javascript", "TypeScript": "p/typescript", "Java": "p/java",
            "Go": "p/golang", "C#": "p/csharp", "Ruby": "p/ruby", "PHP": "p/php"}
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


class Triage(BaseModel):
    index: int
    verdict: str = Field(description="likely real | needs review | likely false positive")
    explanation: str = Field(description="why it matters for this application, 1-2 sentences")
    fix: str = Field(description="concrete fix")


class TriageList(BaseModel):
    items: List[Triage]
    summary: str = Field(description="2-3 sentence security summary for the release decision")


class SecurityAgent:
    def __init__(self) -> None:
        self.node_name = "security_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, ws, t0 = state["task_id"], state["workspace"], time.time()
        langs = {c["language"] for c in state.get("components", [])}
        src = state["source"].strip()
        url = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", src)
        github_repo = url.group(1) if url else (src if state.get("source_type") == "git repo" and re.fullmatch(r"[\w.-]+/[\w.-]+", src) else None)
        chosen = [n for n in ((state.get("options") or {}).get("scanners") or default_scanners(langs, bool(github_repo))) if n in CATALOG]
        context = {"components": [{"name": c["name"], "path": c["path"], "language": c["language"]} for c in state.get("components", [])],
                   "github_repo": github_repo, "project": (state.get("source_info") or {}).get("name") or src.rstrip("/\\").split("/")[-1].split("\\")[-1],
                   "semgrep_configs": ["p/secrets"] + [RULESETS[lang] for lang in langs if lang in RULESETS]}
        await emit(task_id, self.node_name, StreamStatus.START, f"Scanning the code with {len(chosen)} scanners: {', '.join(chosen)}",
                   data={"scanners": [{"name": n, "label": CATALOG[n][1]} for n in chosen]})
        client, limit = scanner_client(), asyncio.Semaphore(4)

        async def scan(name: str) -> dict:
            async with limit:
                await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: running")
                return await client.call_tool("run_scanner", {"name": name, "path": ws, "context": context})

        results = dict(zip(chosen, await asyncio.gather(*(scan(n) for n in chosen), return_exceptions=True)))
        steps, findings = {}, []
        for name, res in results.items():
            if isinstance(res, Exception):
                res = {"status": "error", "message": str(res), "findings": []}
            findings += res.get("findings", [])
            status = {"ok": "passed" if not res.get("findings") else "warning", "skipped": "skipped"}.get(res["status"], "error")
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: {res.get('message')}")
            steps[f"scan.{name}"] = step_record(f"scan.{name}", CATALOG[name][1], "security", status, res.get("message", ""),
                                                items=res.get("findings", []), item_type="findings", started=t0,
                                                summary={"via": client.last_transport, "category": CATALOG[name][2]})
        findings.sort(key=lambda f: SEV_ORDER.index(f["severity"]) if f["severity"] in SEV_ORDER else 9)
        serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH") and f.get("category") != "code_quality"][:25]
        summary = ""
        llm = await LLMProvider().get_llm(state.get("provider"))
        if llm and serious:
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"AI triage of {len(serious)} critical / high findings")
            listing = "\n".join(f"[{i}] {f['severity']} {f['scanner']} {f.get('rule_id')} {f['title']} at {f.get('file')}:{f.get('line')}"
                                f"\n    {(f.get('snippet') or f.get('description') or '')[:300]}" for i, f in enumerate(serious))
            tri = await ask_structured(llm, TriageList, "You are an application security engineer. Triage each finding.", listing)
            if tri:
                summary = tri.summary
                for t in tri.items:
                    if 0 <= t.index < len(serious):
                        serious[t.index]["triage"] = t.model_dump()
        gate = security_gate(findings)
        stop = not gate["passed"] and not (state.get("options") or {}).get("continue_on_fail")
        message = f"{len(findings)} findings from {len(chosen)} scanners · gate {'PASS' if gate['passed'] else 'FAIL'}"
        await emit(task_id, self.node_name, StreamStatus.END, message)
        steps["security_gate"] = step_record("security_gate", "Security gate", "security", "passed" if gate["passed"] else "failed",
                                             "; ".join(f"{c['name']} = {c['actual']} (needs {c['required']})" for c in gate["checks"]
                                                       if not c["passed"]) or "all checks passed",
                                             items=gate["checks"], item_type="checks", explanation=summary)
        return {"findings": findings, "gates": {"security": gate}, "steps": steps, "step_index": state["step_index"] + 1,
                **({"stopped_at": "security gate"} if stop else {})}
