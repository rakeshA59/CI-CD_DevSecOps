"""
Pipeline Router – start runs, list them, read one, stream its live events (SSE), download its PDF.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from langchain_core.messages import HumanMessage, SystemMessage

from agents.checkout_agent import is_remote
from graph_builders.pipeline_graph_builder import graph_outline
from llmapi.llm_provider import LLMProvider
from mcp_services.mcp_clients.mcp_tool_client import scanner_client
from mcp_services.mcp_servers.docker_mcp.docker_ops import running_apps
from mcp_services.mcp_servers.scanner_mcp.scanners import list_scanners
from core.settings import RUNS_DIR
from models.pipeline_models import ApprovalDecision, QuestionnaireAnswers, StartPipelineRequest
from repositories.pipeline_repository import PipelineRepository
from services.pipeline_service import RUNNING, PipelineService, run_key
from services.step_report_html import render_step_report, step_docs
from services.stream_event_writer import stream_writer

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


def _app_urls(task_id: str, apps: dict[str, list[str]]) -> list[dict]:
    """This run's containers that are running right now (live `docker ps`, not what the run stored):
    [{"name": "uat frontend", "url": "http://127.0.0.1:32772"}] – container cip-uat-<run>-frontend → "uat frontend"."""
    key = run_key(task_id)
    return [{"name": name.replace(f"-{key}", "").removeprefix("cip-").replace("-", " "), "url": u}
            for name, urls in sorted(apps.items()) if key in name for u in urls]


@router.post("/start")
async def start_pipeline(req: StartPipelineRequest) -> Any:
    """Start a CI/CD run for a GitHub repo or a local folder."""
    source = req.source.strip().strip('"')
    if not source:
        raise HTTPException(status_code=400, detail="Enter a GitHub URL, org/repo or a local folder path")
    if not is_remote(source) and not Path(source).expanduser().is_dir():
        raise HTTPException(status_code=400, detail=f"Not a GitHub URL and no such local folder: {source}")
    try:
        return await PipelineService().start(source, req.branch, req.llm_provider, req.options.model_dump(), req.mode, req.pipeline_name)
    except Exception as e:
        logging.exception("start failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scanners")
async def scanners() -> Any:
    """The scanner catalogue with what is installed / configured on this machine (for the run form)."""
    return await list_scanners()


@router.post("/scanners/{name}/repair")
async def repair_scanner(name: str) -> Any:
    """Settings → Scanners → Repair: (re)install one scanner into .scanners."""
    return await scanner_client().call_tool("ensure_scanner", {"name": name, "force": True})


@router.get("/step-docs")
async def get_step_docs() -> Any:
    """What every step and scanner is (the ⓘ hover cards)."""
    return step_docs()


@router.get("/dashboard")
async def dashboard() -> Any:
    """Common dashboard: every run with its result, stage statuses, tests and open findings, plus totals."""
    runs = await PipelineRepository().list_runs(100, dashboard=True)
    done = [r for r in runs if r.get("overall")]
    latest = {}
    for r in runs:                                   # newest first → first run per repository is its latest
        latest.setdefault(r.get("repo"), r)
    open_findings = {s: sum((r.get("findings_by_severity") or {}).get(s, 0) for r in latest.values()) for s in ("CRITICAL", "HIGH")}
    tests = [r.get("tests_summary") or {} for r in done]
    apps = await running_apps()
    for r in runs:
        r["active"] = r["task_id"] in RUNNING
        r["app_urls"] = _app_urls(r["task_id"], apps)
    return {"totals": {"runs": len(runs), "successful": sum(r.get("status") == "COMPLETED" for r in runs),
                       "terminated": sum(r.get("status") == "STOPPED" for r in runs),
                       "errors": sum(r.get("status") == "ERROR" for r in runs),
                       "waiting": sum(str(r.get("status")).startswith("WAITING") for r in runs),
                       "repositories": len(latest), "open_findings_latest": open_findings,
                       "tests_passed": sum(t.get("passed", 0) for t in tests), "tests_total": sum(t.get("total", 0) for t in tests)},
            "runs": runs}


@router.get("")
async def list_pipelines() -> Any:
    """Recent runs, newest first (date/time, local folder or git repo, result)."""
    runs = await PipelineRepository().list_runs()
    for r in runs:
        r["active"] = r["task_id"] in RUNNING
    return {"runs": runs}


@router.get("/graph")
async def pipeline_graph() -> Any:
    """The LangGraph workflow (nodes + edges) for the UI."""
    return graph_outline()


@router.get("/remediation-history")
async def remediation_history() -> Any:
    """List all saved remediation specs (most recent first)."""
    specs = []
    if RUNS_DIR.is_dir():
        for rdir in sorted(RUNS_DIR.iterdir(), reverse=True):
            rfile = rdir / "remediation.json"
            if rfile.is_file():
                try:
                    data = json.loads(rfile.read_text(encoding="utf-8"))
                    specs.append(data)
                except Exception:
                    pass
    return {"specs": specs}


@router.get("/{task_id}")
async def get_pipeline(task_id: str) -> Any:
    run = await PipelineRepository().get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run["active"] = task_id in RUNNING
    run["app_urls"] = _app_urls(task_id, await running_apps())
    # Hide download buttons when the files no longer exist on disk
    if (run.get("report") or {}).get("pdf") and not (RUNS_DIR / task_id / "report.pdf").is_file():
        run["report"] = {k: v for k, v in run["report"].items() if k != "pdf"}
    if (run.get("steps") or {}).get("publish_tests") and not (RUNS_DIR / task_id / "test-results" / "test-report.html").is_file():
        run["steps"]["publish_tests"]["status"] = "skipped"
    return run


@router.get("/{task_id}/steps/{step_id}/report.html", response_class=HTMLResponse)
async def step_report(task_id: str, step_id: str) -> Any:
    """Full report of one step: what / why / tool / how / expected, stage report, results, commands, reasoning, logs."""
    run = await PipelineRepository().get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    events = await stream_writer.read(task_id, 0, 20000)
    return HTMLResponse(render_step_report(run, step_id, events))


@router.post("/{task_id}/stop")
async def stop_pipeline(task_id: str) -> Any:
    """Stop a running or paused run; its containers are removed, its finished stages are kept."""
    try:
        return await PipelineService().stop(task_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="run not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{task_id}/stream")
async def stream_pipeline(task_id: str, after: int = 0):
    """Server-sent events: every agent event of the run, until SYSTEM_END."""

    async def events():
        cursor = after
        while True:
            batch = await stream_writer.read(task_id, cursor)
            for ev in batch:
                cursor = ev["id"]
                yield f"id: {ev['id']}\ndata: {json.dumps(ev, default=str)}\n\n"
                if ev["status"] == "SYSTEM_END":
                    return
                if ev["status"] == "SYSTEM_PAUSE" and task_id not in RUNNING and not await stream_writer.read(task_id, ev["id"]):
                    run = await PipelineRepository().get_run(task_id)     # the run is paused right here, not resumed since
                    if str((run or {}).get("status")).startswith("WAITING"):
                        return
            if not batch and task_id not in RUNNING:
                run = await PipelineRepository().get_run(task_id)
                if run and run.get("status") != "RUNNING":
                    end = "SYSTEM_PAUSE" if str(run.get("status")).startswith("WAITING") else "SYSTEM_END"
                    yield f"data: {json.dumps({'status': end, 'node': 'SYSTEM', 'data': {'overall': run.get('overall'), 'status': run.get('status')}})}\n\n"
                    return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{task_id}/answers")
async def answer_questionnaire(task_id: str, body: QuestionnaireAnswers) -> Any:
    """Resume a guided run that waits for its questionnaire (answers are validated by the questionnaire agent)."""
    return await _resume(task_id, "questionnaire", body.answers)


@router.post("/{task_id}/approval")
async def approve(task_id: str, body: ApprovalDecision) -> Any:
    """Resume a run that waits for a human decision: the security review (HITL) or the approval before UAT."""
    run = await PipelineRepository().get_run(task_id) or {}
    kind = "security_review" if (run.get("pending") or {}).get("type") == "security_review" else "approval"
    return await _resume(task_id, kind, body.model_dump())


async def _resume(task_id: str, kind: str, payload: dict) -> Any:
    try:
        return await PipelineService().resume(task_id, kind, payload)
    except LookupError:
        raise HTTPException(status_code=404, detail="run not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{task_id}/test-results/{name}")
async def test_results(task_id: str, name: str):
    """The published test results of a guided run (junit.xml / test-report.html)."""
    if name not in ("junit.xml", "test-report.html") or "/" in task_id or "\\" in task_id:
        raise HTTPException(status_code=404, detail="unknown file")
    path = RUNS_DIR / task_id / "test-results" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not published")
    return FileResponse(path, media_type="text/html" if name.endswith("html") else "application/xml", filename=name)


@router.get("/{task_id}/screenshots/{name}")
async def ui_screenshot(task_id: str, name: str):
    """A screenshot taken by the UI browser tests (TC-UI-xxx.png)."""
    if not re.fullmatch(r"TC-UI-\d{3}\.png", name) or "/" in task_id or "\\" in task_id:
        raise HTTPException(status_code=404, detail="unknown screenshot")
    path = RUNS_DIR / task_id / "ui-screenshots" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such screenshot")
    return FileResponse(path, media_type="image/png")


@router.get("/{task_id}/report.pdf")
async def pipeline_pdf(task_id: str):
    path = PipelineService().pdf_path(task_id)
    if "/" in task_id or "\\" in task_id or not path.is_file():
        raise HTTPException(status_code=404, detail="report not written yet")
    return FileResponse(path, media_type="application/pdf", filename=f"{task_id}-report.pdf")


# ---------------------------------------------------------------------------
#  Remediation Specs – LLM-generated fix recommendations per stage
# ---------------------------------------------------------------------------

_REMEDIATION_PROMPT = """\
You are a senior DevSecOps engineer reviewing a CI/CD pipeline run.
Below is the complete log and run data for a pipeline execution.
Analyze EVERY stage that has errors, test failures, security findings, or warnings.

The pipeline stages in order are:
  Stage 1: Source (checkout)
  Stage 2: Discovery (plan/detect tech stack)
  Stage 3: Scanning (security scans – Semgrep SAST, Gitleaks Secrets, Trivy SCA, SonarQube, etc.)
  Stage 4: Build & Test (build, unit tests, packaging)
  Stage 5: Containerize (Docker image build & scan)
  Stage 6: Release (push to registry)
  Stage 7: Deploy (deploy to dev/staging)
  Stage 8: Functional Tests
  Stage 9: UI Tests
  Stage 10: Approval (human review)
  Stage 11: Deploy UAT (production/UAT deploy)
  Stage 12: Report (final report generation)

Use this EXACT format for each stage that has issues (skip stages that passed cleanly):

### STAGE: Stage <number>: <Stage Name>

If this stage has multiple scanners/tools (e.g. Stage 3 may have Semgrep, Gitleaks, Trivy, SonarQube), create a separate sub-section for EACH scanner using this format:

**Scanner: <Scanner Name>** (e.g. Semgrep SAST, Gitleaks Secrets, Trivy SCA)

#### Issues Found
List EVERY finding from this scanner. Do NOT skip or summarize — list each one individually:
- **[<SEVERITY>]** `<file_path>:<line>` — <description of what was found>
  - Package/Rule: <package name or rule ID if available>
  - Installed version: <version if available>
  - Fixed version: <version if available>
  - CVE/ID: <CVE or rule identifier if available>

If there are test failures, list: **[FAIL]** `<test_name>` — <error message>

#### Root Cause
Explain WHY these issues exist — what pattern or mistake led to them.

#### Remediation
Numbered, actionable steps the developer should take:
1. <specific step with file paths and commands>
2. <next step>

If code changes are needed, show the fix:
```
<file_path>
<the fix>
```

---

RULES:
- Use the stage numbers and names above. Map each step/scanner to its pipeline stage.
- If multiple scanners found issues in the same stage, list each scanner SEPARATELY with its own "Scanner:" heading, Issues Found, Root Cause, and Remediation sections within that stage.
- List EVERY individual finding from EVERY scanner. Do not omit, summarize, or group findings. Each finding must appear with its severity, file, line, description, and any available package/version/CVE info.
- Be specific — reference actual file names, line numbers, error messages and findings from the logs.
- Do NOT say "and X more similar issues" or "see above" — list each finding individually.
"""


def _build_remediation_context(run: dict, events: list[dict]) -> str:
    """Combine run record + stream events into a text block for the LLM."""
    parts = [f"Pipeline: {run.get('pipeline_name') or run.get('app_name')}",
             f"Repository: {run.get('repo')}",
             f"Overall verdict: {run.get('overall') or run.get('status')}",
             f"Provider: {run.get('provider')}",
             ""]

    # Gates
    gates = run.get("gates") or {}
    if gates:
        parts.append("=== GATES ===")
        for g, v in gates.items():
            parts.append(f"  {g}: {v}")
        parts.append("")

    # Findings by severity
    fbs = run.get("findings_by_severity") or {}
    if fbs:
        parts.append(f"=== FINDINGS SUMMARY === CRITICAL:{fbs.get('CRITICAL',0)} HIGH:{fbs.get('HIGH',0)} MEDIUM:{fbs.get('MEDIUM',0)} LOW:{fbs.get('LOW',0)}")
        parts.append("")

    # Tests summary
    ts = run.get("tests_summary") or {}
    if ts.get("total"):
        parts.append(f"=== TESTS === passed {ts['passed']}/{ts['total']}")
        parts.append("")

    # Step details from run record (findings, errors, items) — include stage info
    _STEP_STAGE_MAP = {
        "checkout": "Stage 1: Source", "plan": "Stage 2: Discovery", "questionnaire": "Stage 2: Discovery",
        "design": "Stage 2: Discovery", "scan": "Stage 3: Scanning", "security_gate": "Stage 3: Scanning",
        "build": "Stage 4: Build & Test", "test": "Stage 4: Build & Test", "test_gate": "Stage 4: Build & Test",
        "package": "Stage 5: Containerize", "image": "Stage 5: Containerize", "container_gate": "Stage 5: Containerize",
        "release": "Stage 6: Release", "deploy": "Stage 7: Deploy",
        "functional": "Stage 8: Functional Tests", "functional_gate": "Stage 8: Functional Tests",
        "ui_tests": "Stage 9: UI Tests", "ui_gate": "Stage 9: UI Tests",
        "publish_tests": "Stage 9: UI Tests", "approval": "Stage 10: Approval",
        "deploy_uat": "Stage 11: Deploy UAT", "report": "Stage 12: Report",
    }
    # Friendly scanner names from step component IDs
    _SCANNER_DISPLAY = {
        "semgrep": "Semgrep SAST", "gitleaks": "Gitleaks Secrets",
        "trivy": "Trivy SCA", "trivy-fs": "Trivy SCA (Filesystem)",
        "sonarqube": "SonarQube", "snyk": "Snyk SCA",
        "owasp": "OWASP Dependency-Check",
    }
    steps = run.get("steps") or {}

    def _format_finding(f: dict) -> list[str]:
        """Format a single finding into context lines."""
        lines: list[str] = []
        pkg = f.get("package") or f.get("title", "")
        fix_ver = f.get("fixed_version") or (f.get("triage") or {}).get("fix") or f.get("recommendation") or ""
        cve = f.get("id") or f.get("rule_id") or ""
        loc = f.get("file") or f.get("where") or ""
        line = f.get("line") or ""
        lines.append(f"  FINDING [{f.get('severity')}] {cve}: {f.get('message','') or pkg}")
        if loc:
            lines.append(f"    File: {loc}{':' + str(line) if line else ''}")
        if pkg and pkg != f.get("message", ""):
            lines.append(f"    Package: {pkg}")
        if f.get("installed_version"):
            lines.append(f"    Installed: {f['installed_version']}")
        if f.get("fixed_version"):
            lines.append(f"    Fix: upgrade to {f['fixed_version']}")
        elif fix_ver:
            lines.append(f"    Recommendation: {fix_ver[:200]}")
        return lines

    def _format_findings_smart(findings: list[dict]) -> list[str]:
        """Format findings: CRITICAL/HIGH individually; LOW/MEDIUM grouped by rule with examples."""
        lines: list[str] = []
        _SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        # Sort: CRITICAL first, then HIGH, MEDIUM, LOW
        sorted_findings = sorted(findings, key=lambda f: _SEV_RANK.get(f.get("severity", ""), 4))
        critical_high = [f for f in sorted_findings if f.get("severity") in ("CRITICAL", "HIGH")]
        medium_low = [f for f in sorted_findings if f.get("severity") not in ("CRITICAL", "HIGH")]

        # CRITICAL and HIGH: list every one individually
        for f in critical_high:
            lines.extend(_format_finding(f))

        # MEDIUM and LOW: if > 50, group by rule_id with up to 3 examples each
        if len(medium_low) > 50:
            from collections import OrderedDict
            grouped: dict[str, list[dict]] = OrderedDict()
            for f in medium_low:
                key = f.get("rule_id") or f.get("id") or f.get("message", "unknown")
                grouped.setdefault(key, []).append(f)
            lines.append(f"  --- {len(medium_low)} MEDIUM/LOW findings grouped by rule ---")
            for rule, group in grouped.items():
                sev = group[0].get("severity", "")
                msg = group[0].get("message", "")
                lines.append(f"  RULE [{sev}] {rule} — {len(group)} occurrences: {msg}")
                # Show up to 3 example files
                for f in group[:3]:
                    loc = f.get("file") or f.get("where") or ""
                    ln = f.get("line") or ""
                    if loc:
                        lines.append(f"    Example: {loc}{':' + str(ln) if ln else ''}")
                if len(group) > 3:
                    lines.append(f"    ... and {len(group)-3} more in other files")
        else:
            # 50 or fewer: list them all individually
            for f in medium_low:
                lines.extend(_format_finding(f))

        return lines

    if steps:
        parts.append("=== STEP DETAILS ===")
        for sid, s in steps.items():
            status = s.get("status", "")
            msg = s.get("message", "")
            items = s.get("items") or []
            findings = [i for i in items if i.get("severity")]
            failed_tests = [i for i in items if i.get("status") == "failed"]
            if status in ("failed", "error", "warning") or findings or failed_tests:
                # Extract scanner name from step ID (e.g. "scan.semgrep" → "semgrep")
                step_parts = sid.split(".")
                step_base = step_parts[0]
                scanner_component = step_parts[1] if len(step_parts) > 1 else ""
                scanner_display = _SCANNER_DISPLAY.get(scanner_component, scanner_component.title() if scanner_component else "")
                stage_name = _STEP_STAGE_MAP.get(step_base, s.get("stage", "other"))

                parts.append(f"\n--- Step: {sid} ({s.get('label','')}) [Pipeline {stage_name}] ---")
                if scanner_display:
                    parts.append(f"*** SCANNER: {scanner_display} ***")
                parts.append(f"Status: {status}")
                if msg:
                    parts.append(f"Message: {msg}")
                if s.get("explanation"):
                    parts.append(f"Explanation: {s['explanation']}")
                parts.append(f"  Total findings from this scanner: {len(findings)}")
                # Smart formatting: full detail for CRITICAL/HIGH, grouped for LOW/MEDIUM if many
                parts.extend(_format_findings_smart(findings))
                for t in failed_tests[:30]:
                    parts.append(f"  FAILED TEST: {t.get('name','')} – {t.get('message','')}")
        parts.append("")

    # Errors
    errors = run.get("errors") or []
    if errors:
        parts.append("=== ERRORS ===")
        for e in errors:
            parts.append(f"  {e}")
        parts.append("")

    # Stream events (logs) — include ERROR, COMMAND (with errors), END with failure data
    parts.append("=== LOGS (key events) ===")
    for ev in events:
        st = ev.get("status", "")
        msg = ev.get("message", "")
        node = ev.get("node", "")
        if st in ("ERROR", "SKIPPED"):
            parts.append(f"[{st}] {node}: {msg}")
        elif st == "END" and ev.get("data"):
            d = ev["data"]
            if isinstance(d, dict) and (d.get("status") in ("failed", "error") or d.get("errors")):
                parts.append(f"[END] {node}: {msg} | data: {json.dumps(d, default=str)[:500]}")
        elif st == "COMMAND" and ("error" in msg.lower() or "fail" in msg.lower() or "exit code" in msg.lower()):
            parts.append(f"[CMD] {node}: {msg[:300]}")

    return "\n".join(parts)[:120000]   # cap at 120k chars to include all findings


@router.get("/{task_id}/remediation-saved")
async def remediation_saved(task_id: str) -> Any:
    """Load a previously saved remediation spec."""
    rfile = RUNS_DIR / task_id / "remediation.json"
    if not rfile.is_file():
        raise HTTPException(status_code=404, detail="no saved remediation spec")
    return json.loads(rfile.read_text(encoding="utf-8"))


@router.get("/{task_id}/remediation")
async def remediation_specs(task_id: str) -> Any:
    """Generate LLM-powered remediation specifications for a pipeline run."""
    run = await PipelineRepository().get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    events = await stream_writer.read(task_id, 0, 20000)
    context = _build_remediation_context(run, events)
    provider = run.get("provider")
    llm = await LLMProvider().get_llm(provider)
    if not llm:
        raise HTTPException(status_code=500, detail="No LLM provider configured")
    reply = await llm.ainvoke([
        SystemMessage(content=_REMEDIATION_PROMPT),
        HumanMessage(content=context),
    ])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    result = {"task_id": task_id,
              "pipeline_name": run.get("pipeline_name") or run.get("app_name"),
              "overall": run.get("overall"),
              "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
              "remediation": text}
    # Save to disk so it can be recalled later
    try:
        out = RUNS_DIR / task_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "remediation.json").write_text(json.dumps(result, default=str), encoding="utf-8")
    except Exception:
        logging.warning("could not save remediation spec to disk", exc_info=True)
    return result
