"""
Pipeline Router – start runs, list them, read one, stream its live events (SSE), download its PDF.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from agents.checkout_agent import is_remote
from graph_builders.pipeline_graph_builder import graph_outline
from mcp_services.mcp_servers.scanner_mcp.scanners import list_scanners
from models.pipeline_models import StartPipelineRequest
from repositories.pipeline_repository import PipelineRepository
from services.pipeline_service import RUNNING, PipelineService
from services.stream_event_writer import stream_writer

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


@router.post("/start")
async def start_pipeline(req: StartPipelineRequest) -> Any:
    """Start a CI/CD run for a GitHub repo or a local folder."""
    source = req.source.strip().strip('"')
    if not source:
        raise HTTPException(status_code=400, detail="Enter a GitHub URL, org/repo or a local folder path")
    if not is_remote(source) and not Path(source).expanduser().is_dir():
        raise HTTPException(status_code=400, detail=f"Not a GitHub URL and no such local folder: {source}")
    try:
        return await PipelineService().start(source, req.branch, req.llm_provider, req.options.model_dump())
    except Exception as e:
        logging.exception("start failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scanners")
async def scanners() -> Any:
    """The scanner catalogue with what is installed / configured on this machine (for the run form)."""
    return await list_scanners()


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
    return run


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
            if not batch and task_id not in RUNNING:
                run = await PipelineRepository().get_run(task_id)
                if run and run.get("status") != "RUNNING":
                    yield f"data: {json.dumps({'status': 'SYSTEM_END', 'node': 'SYSTEM', 'data': {'overall': run.get('overall')}})}\n\n"
                    return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/{task_id}/report.pdf")
async def pipeline_pdf(task_id: str):
    path = PipelineService().pdf_path(task_id)
    if "/" in task_id or "\\" in task_id or not path.is_file():
        raise HTTPException(status_code=404, detail="report not written yet")
    return FileResponse(path, media_type="application/pdf", filename=f"{task_id}-report.pdf")
