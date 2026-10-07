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

from agents.checkout_agent import is_remote
from graph_builders.pipeline_graph_builder import graph_outline
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
        return await PipelineService().start(source, req.branch, req.llm_provider, req.options.model_dump(), req.mode)
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
    return {"totals": {"runs": len(runs), "passed": sum(r["overall"] == "PASS" for r in done),
                       "failed": sum(r["overall"] in ("FAIL", "ERROR") for r in done),
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


@router.get("/{task_id}")
async def get_pipeline(task_id: str) -> Any:
    run = await PipelineRepository().get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run["active"] = task_id in RUNNING
    run["app_urls"] = _app_urls(task_id, await running_apps())
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
