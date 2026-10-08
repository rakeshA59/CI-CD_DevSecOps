"""
Security Agent.

Runs the scanners through the Scanner MCP server in parallel – SAST (Semgrep, Bandit, CodeQL), lint (Ruff, ESLint),
dependencies (Trivy, OSV-Scanner, pip-audit, npm audit, Snyk), secrets (Gitleaks, TruffleHog) and platforms
(SonarQube, GitHub Dependabot / code / secret scanning alerts). Which ones run: the run options' `scanners`, else
the defaults for the languages the planner found (+ the token / server based ones that are configured).
Self-healing (like build / deploy): a missing scanner is installed into .scanners before the scan; a scanner that
fails is reinstalled and rerun, then – with an LLM – the agent reads its error and repairs the .scanners install
(self_heal_attempts times); only then the fallback tool of the same type runs.
Then – with an LLM – it triages the serious findings. The security gate itself is a fixed threshold check.
"""

import asyncio
import re
import time
from typing import List

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from agent_states.pipeline_state import PipelineState
from agent_tools.workspace_tools import WorkspaceTools
from agents.tool_loop import tool_loop
from core.settings import env
from llmapi.llm_provider import LLMProvider
from llmapi.structured_llm import ask_structured
from mcp_services.mcp_clients.mcp_tool_client import scanner_client
from mcp_services.mcp_servers.scanner_mcp.scanners import CATALOG, FALLBACK, INSTALL_AS, SCANNER_HOME, fits, pick_scanners
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.quality_gates import security_gate

RULESETS = {"Python": "p/python", "JavaScript": "p/javascript", "TypeScript": "p/typescript", "Java": "p/java",
            "Go": "p/golang", "C#": "p/csharp", "Ruby": "p/ruby", "PHP": "p/php"}
SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
BROKEN = re.compile(r"ImportError|ModuleNotFoundError|No module named|not recognized|cannot execute|Exec format|"
                    r"No such file|DLL load failed|Permission denied|SyntaxError", re.I)


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

    async def _prepare(self, task_id: str, client, chosen: list[str]) -> dict[str, list[str]]:
        """Install the chosen scanners that are not installed yet (once – later runs find them in .scanners)."""
        notes: dict[str, list[str]] = {}
        for name in [n for n in chosen if n in INSTALL_AS]:
            res = await client.call_tool("ensure_scanner", {"name": name})
            if not res["ok"] or "installed into" in res["message"]:
                notes[name] = [f"not installed → {res['message'] if res['ok'] else 'automatic install failed: ' + res['message']}"]
                await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"self-healing: {name} {notes[name][0]}")
        return notes

    async def _heal(self, task_id: str, client, results: dict, scan, llm, tries: int, notes: dict) -> None:
        """A scanner that could not run: reinstall it and rerun; then let the agent repair the install from the
        error output and rerun (up to `tries` times). What happened is kept per scanner in `notes`."""
        def failed(r):
            return isinstance(r, Exception) or (r.get("status") == "error" and "log" in r)

        def broken_install(r):      # not for findings, network or vulnerability-database problems – a reinstall cannot fix those
            return failed(r) and bool(BROKEN.search(str(r) if isinstance(r, Exception) else r["log"]))
        for name in [n for n, r in results.items() if broken_install(r) and n in INSTALL_AS]:
            err = str(results[name]) if isinstance(results[name], Exception) else results[name]["message"]
            log = notes.setdefault(name, [])
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"self-healing: {name} failed ({err}) – reinstalling it")
            fix = await client.call_tool("ensure_scanner", {"name": name, "force": True})
            log.append(f"failed: {err} → {fix['message']}")
            results[name] = await scan(name)
            attempt = 0
            while failed(results[name]) and llm and attempt < tries:
                attempt += 1
                await emit(task_id, self.node_name, StreamStatus.PROGRESS,
                           f"self-healing: {name} still fails – the agent is repairing the install (attempt {attempt}/{tries})")
                SCANNER_HOME.mkdir(exist_ok=True)
                tools = WorkspaceTools(str(SCANNER_HOME), task_id, self.node_name)
                answer = await tool_loop(
                    llm, tools.tools,
                    "You repair a security scanner installation. The scanner runs from the folder you are in (its own Python "
                    "venv in Scripts/ or bin/, downloaded binaries in bin/). Read the error, find the cause with the tools and "
                    "fix the INSTALLATION only (e.g. pip install a compatible version with this folder's python -m pip). "
                    "Never touch the repository or the API's own venv. Finish with: ROOT CAUSE: … FIX: …",
                    f"Scanner: {name}\nError output:\n{results[name].get('log', err)[-4000:] if isinstance(results[name], dict) else err}",
                    task_id, self.node_name, max_steps=12)
                log.append(f"agent attempt {attempt}: {answer.strip()[-600:]}")
                results[name] = await scan(name)
            log.append("rerun: OK" if not failed(results[name]) else "rerun: still failing → fallback tool")

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, ws, t0 = state["task_id"], state["workspace"], time.time()
        langs = {c["language"] for c in state.get("components", [])}
        src = state["source"].strip()
        url = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", src)
        github_repo = url.group(1) if url else (src if state.get("source_type") == "git repo" and re.fullmatch(r"[\w.-]+/[\w.-]+", src) else None)
        opts = state.get("options") or {}
        # one tool per scan type (SAST · SCA · secrets · lint per language), unless the run names its scanners
        plan = opts.get("scan_plan") or pick_scanners(langs, bool(github_repo))
        chosen = [n for n in (opts.get("scanners") or [p["tool"] for p in plan]) if n in CATALOG]
        why = {p["tool"]: p for p in plan}
        context = {"components": [{"name": c["name"], "path": c["path"], "language": c["language"]} for c in state.get("components", [])],
                   "github_repo": github_repo, "project": (state.get("source_info") or {}).get("name") or src.rstrip("/\\").split("/")[-1].split("\\")[-1],
                   "semgrep_configs": ["p/secrets"] + [RULESETS[lang] for lang in langs if lang in RULESETS],
                   **({"sonar_host_url": env("sonar_host_url"), "sonar_token": env("sonar_token")} if "sonarqube" in chosen else {})}
        await emit(task_id, self.node_name, StreamStatus.START, f"Scanning the code with {len(chosen)} scanners: {', '.join(chosen)}",
                   data={"scanners": [{"name": n, "label": CATALOG[n][1], "category": CATALOG[n][2]} for n in chosen]})
        client, limit = scanner_client(), asyncio.Semaphore(4)

        async def scan(name: str) -> dict:
            async with limit:
                await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: running")
                return await client.call_tool("run_scanner", {"name": name, "path": ws, "context": context})

        llm = await LLMProvider().get_llm(state.get("provider"))
        heal = await self._prepare(task_id, client, chosen)                     # missing tools → installed first
        results = dict(zip(chosen, await asyncio.gather(*(scan(n) for n in chosen), return_exceptions=True)))
        await self._heal(task_id, client, results, scan, llm, int(opts.get("self_heal_attempts", 1)), heal)
        # the picked tool could not run (not installed / no database / no network) → its fallback runs instead
        broken = [n for n, r in results.items() if isinstance(r, Exception) or r.get("status") in ("error", "skipped")]
        backup = {f: n for n in broken for f in FALLBACK.get(n, []) if f not in results and fits(f, langs)}
        if backup:
            await emit(task_id, self.node_name, StreamStatus.PROGRESS,
                       "fallback: " + ", ".join(f"{f} instead of {n}" for f, n in backup.items()))
            heal.update(await self._prepare(task_id, client, list(backup)))          # e.g. Biome: installed on first use
            results.update(zip(backup, await asyncio.gather(*(scan(f) for f in backup), return_exceptions=True)))
        steps, findings = {}, []
        for name, res in results.items():
            if isinstance(res, Exception):
                res = {"status": "error", "message": str(res), "findings": []}
            findings += res.get("findings", [])
            status = {"ok": "passed", "skipped": "skipped"}.get(res["status"], "error")       # findings colour the ⓘ
            replaced = [f for f, n in backup.items() if n == name]
            if replaced and status in ("error", "skipped"):   # the fallback took over – not an error of the pipeline
                status, res = "skipped", {**res, "message": f"could not run ({res.get('message', '')[:200]}) – replaced by "
                                                              f"{', '.join(CATALOG[f][1] for f in replaced)}"}
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: {res.get('message')}")
            steps[f"scan.{name}"] = step_record(f"scan.{name}", CATALOG[name][1], "security", status, res.get("message", ""),
                                                items=res.get("findings", []), item_type="findings", started=t0,
                                                summary={"via": client.last_transport, "category": CATALOG[name][2],
                                                         "scan type": (why.get(name) or why.get(backup.get(name)) or {}).get("label", ""),
                                                         "why this tool": (f"fallback – {backup[name]} could not run" if name in backup
                                                                           else (why.get(name) or {}).get("reason", "chosen in the run form")),
                                                         **({"self-heal": heal[name][-1]} if heal.get(name) else {})},
                                                explanation="\n".join(heal.get(name, [])))
        findings.sort(key=lambda f: SEV_ORDER.index(f["severity"]) if f["severity"] in SEV_ORDER else 9)
        serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH") and f.get("category") != "code_quality"][:25]
        summary = ""
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
        steps["security_gate"] = step_record("security_gate", "HITL – review reports", "security", "failed" if stop else "passed",
                                             "; ".join(f"{c['name']} = {c['actual']} (needs {c['required']})" for c in gate["checks"]
                                                       if not c["passed"]) or "all checks passed",
                                             items=gate["checks"], item_type="checks", explanation=summary)
        return {"findings": findings, "gates": {"security": gate}, "steps": steps, "step_index": state["step_index"] + 1,
                **({"stopped_at": "security gate"} if stop else {})}
