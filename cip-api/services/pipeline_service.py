"""
Pipeline Service – starts a run as a background task, executes the LangGraph workflow and stores the result in MongoDB.
"""

import asyncio
import datetime as dt
import logging
import re
import time
import uuid
from pathlib import Path

from agents.checkout_agent import is_remote
from core.settings import DEFAULT_LLM_PROVIDER, RUNS_DIR
from graph_builders.pipeline_graph_builder import get_pipeline_graph
from repositories.pipeline_repository import PipelineRepository
from services.stream_event_writer import StreamStatus, stream_writer

RUNNING: dict[str, asyncio.Task] = {}


def _repo_name(source: str) -> str:
    return re.sub(r"\.git$", "", source.rstrip("/\\").replace("\\", "/").split("/")[-1]) or "repo"


class PipelineService:
    def __init__(self) -> None:
        self.repository = PipelineRepository()

    async def start(self, source: str, branch: str | None, provider: str | None, options: dict) -> dict:
        """Create the run document and launch the graph in the background."""
        provider = provider or await self.repository.get_setting("llm_provider", DEFAULT_LLM_PROVIDER)
        repo = _repo_name(source)
        task_id = f"{re.sub(r'[^A-Za-z0-9_.-]', '-', repo)}-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        run_dir = RUNS_DIR / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        doc = {"task_id": task_id, "source": source, "repo": repo, "branch": branch, "provider": provider, "options": options,
               "source_type": "git repo" if is_remote(source) else "local folder", "status": "RUNNING"}
        await self.repository.create_run(doc)
        state = {**doc, "run_dir": str(run_dir), "workspace": str(run_dir / "workspace"), "steps": {}, "lanes": {},
                 "findings": [], "gates": {}, "errors": [], "step_index": 0}
        RUNNING[task_id] = asyncio.create_task(self._execute(task_id, state))
        return {"task_id": task_id, "provider": provider}

    async def _execute(self, task_id: str, state: dict) -> None:
        t0 = time.time()
        await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_START, f"Pipeline started for {state['source']}")
        try:
            graph = await get_pipeline_graph()
            final = await graph.ainvoke(state, {"recursion_limit": 60, "metadata": {"task_id": task_id}})
            status = "COMPLETED"
        except Exception as e:  # noqa: BLE001
            logging.exception("[PipelineService] run %s crashed", task_id)
            final, status = {**state, "errors": state.get("errors", []) + [str(e)], "overall": "ERROR"}, "ERROR"
        await self.repository.update_run(task_id, {
            "status": status, "overall": final.get("overall"), "duration_s": round(time.time() - t0, 1),
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source_info": final.get("source_info"),
            "source_type": final.get("source_type", state["source_type"]), "components": final.get("components"),
            "execution_plan": final.get("execution_plan"), "steps": final.get("steps"), "gates": final.get("gates"),
            "deploy": final.get("deploy"), "report": final.get("report"), "errors": final.get("errors"),
            "findings_by_severity": {s: sum(f["severity"] == s for f in final.get("findings", []))
                                     for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}})
        await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_END, f"OVERALL: {final.get('overall')}",
                                 data={"overall": final.get("overall"), "status": status})
        RUNNING.pop(task_id, None)

    def pdf_path(self, task_id: str) -> Path:
        return RUNS_DIR / task_id / "report.pdf"
