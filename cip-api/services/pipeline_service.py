"""
Pipeline Service – starts a run as a background task, executes the LangGraph workflow and stores the result in MongoDB.

Two modes:
    quick    the fixed flow (pipeline_graph_builder) – runs start to end, as before.
    guided   the Architect's flow (guided_graph_builder) – pauses for the questionnaire and for the approval before
             UAT. A paused run is saved with status WAITING_INPUT / WAITING_APPROVAL and its `pending` question;
             `resume()` continues it with the user's answer (LangGraph Command(resume=...)).
"""

import asyncio
import datetime as dt
import logging
import re
import time
import uuid
from pathlib import Path

from langgraph.types import Command

from agents.checkout_agent import is_remote
from core.settings import DEFAULT_LLM_PROVIDER, RUNS_DIR
from graph_builders.guided_graph_builder import get_guided_graph
from graph_builders.pipeline_graph_builder import get_pipeline_graph
from mcp_services.mcp_servers.docker_mcp.docker_ops import remove_run_containers
from repositories.pipeline_repository import PipelineRepository
from services.stream_event_writer import StreamStatus, stream_writer
from utils.stage_reports import stage_summary, with_reports

RUNNING: dict[str, asyncio.Task] = {}
WAITING = {"questionnaire": "WAITING_INPUT", "approval": "WAITING_APPROVAL"}


def run_key(task_id: str) -> str:
    """The part of a task id that every container / network name of the run contains (see deploy_agent)."""
    return task_id[-12:].lower().strip("-")


def _repo_name(source: str) -> str:
    return re.sub(r"\.git$", "", source.rstrip("/\\").replace("\\", "/").split("/")[-1]) or "repo"


class PipelineService:
    def __init__(self) -> None:
        self.repository = PipelineRepository()

    async def start(self, source: str, branch: str | None, provider: str | None, options: dict, mode: str = "quick") -> dict:
        """Create the run document and launch the graph in the background."""
        provider = provider or await self.repository.get_setting("llm_provider", DEFAULT_LLM_PROVIDER)
        repo = _repo_name(source)
        task_id = f"{re.sub(r'[^A-Za-z0-9_.-]', '-', repo)}-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        run_dir = RUNS_DIR / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        mode = "guided" if mode == "guided" else "quick"
        doc = {"task_id": task_id, "source": source, "repo": repo, "branch": branch, "provider": provider, "options": options,
               "source_type": "git repo" if is_remote(source) else "local folder", "status": "RUNNING", "mode": mode}
        await self.repository.create_run(doc)
        state = {**doc, "run_dir": str(run_dir), "workspace": str(run_dir / "workspace"), "steps": {}, "lanes": {},
                 "findings": [], "gates": {}, "errors": [], "step_index": 0}
        RUNNING[task_id] = asyncio.create_task(self._execute(task_id, state, mode))
        return {"task_id": task_id, "provider": provider, "mode": mode}

    async def resume(self, task_id: str, kind: str, payload: dict) -> dict:
        """Continue a paused guided run with the questionnaire answers or the approval decision."""
        run = await self.repository.get_run(task_id)
        if not run:
            raise LookupError("run not found")
        if task_id in RUNNING or run.get("status") != WAITING.get(kind):
            raise ValueError(f"run is {run.get('status')}, not waiting for {kind}")
        await self.repository.update_run(task_id, {"status": "RUNNING", "pending": None})
        RUNNING[task_id] = asyncio.create_task(self._execute(task_id, Command(resume=payload), "guided"))
        return {"task_id": task_id, "resumed": kind}

    async def _execute(self, task_id: str, payload, mode: str) -> None:
        t0 = time.time()
        first = not isinstance(payload, Command)
        if first:
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_START,
                                     f"Pipeline started for {payload['source']} ({'guided DevOps flow' if mode == 'guided' else 'quick run'})")
        config = {"recursion_limit": 120, "metadata": {"task_id": task_id}, "configurable": {"thread_id": task_id}}
        pending, latest = None, {}
        try:
            if mode == "guided":
                graph = await get_guided_graph()
                await graph.ainvoke(payload, config)
                snapshot = await graph.aget_state(config)
                final = snapshot.values
                pending = next((i.value for t in snapshot.tasks for i in (t.interrupts or [])), None) if snapshot.next else None
            else:
                graph = await get_pipeline_graph()
                # same as ainvoke, but keeps the latest state so a stopped run still shows its finished stages
                async for latest in graph.astream(payload, {"recursion_limit": 60, "metadata": {"task_id": task_id}},
                                                  stream_mode="values"):
                    pass
                final = latest
            status = WAITING.get((pending or {}).get("type"), "WAITING_INPUT") if pending else "COMPLETED"
        except asyncio.CancelledError:                    # Stop button
            if mode == "guided":
                latest = (await (await get_guided_graph()).aget_state(config)).values
            final, status = {**(payload if first else {}), **latest, "overall": "STOPPED"}, "STOPPED"
            await remove_run_containers(run_key(task_id))
        except Exception as e:  # noqa: BLE001
            logging.exception("[PipelineService] run %s crashed", task_id)
            base = payload if first else {}
            final, status = {**base, "errors": base.get("errors", []) + [str(e)], "overall": "ERROR"}, "ERROR"
        run = await self.repository.get_run(task_id) or {}
        steps = with_reports(final.get("steps"))
        await self.repository.update_run(task_id, {
            "status": status, "overall": final.get("overall"), "pending": pending,
            "duration_s": round((run.get("duration_s") or 0) + time.time() - t0, 1),
            **({} if pending else {"finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}),
            "source_info": final.get("source_info"), "source_type": final.get("source_type", run.get("source_type")),
            "components": final.get("components"), "execution_plan": final.get("execution_plan"), "steps": steps,
            "stage_summary": stage_summary(steps), "gates": final.get("gates"), "deploy": final.get("deploy"),
            "report": final.get("report"), "errors": final.get("errors"), "spec": final.get("spec"),
            "answers": final.get("answers"), "detected": final.get("detected"), "release": final.get("release"),
            "uat": final.get("uat"), "approval": final.get("approval"),
            "tests_summary": _tests_summary(steps),
            "findings_by_severity": {s: sum(f["severity"] == s for f in final.get("findings", []) if f.get("category") != "code_quality")
                                     for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}})
        if pending:
            what = "your answers to the questionnaire" if pending["type"] == "questionnaire" else f"approval before {pending.get('target', '').upper()}"
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_PAUSE, f"PAUSED – waiting for {what}",
                                     data={"status": status, "pending": pending["type"]})
        else:
            msg = "STOPPED by the user – finished stages are kept, the run's containers were removed" if status == "STOPPED" \
                else f"OVERALL: {final.get('overall')}"
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_END, msg, data={"overall": final.get("overall"), "status": status})
        RUNNING.pop(task_id, None)

    async def stop(self, task_id: str) -> dict:
        """Stop a run: a running one is cancelled (its command is killed); a paused one is closed."""
        run = await self.repository.get_run(task_id)
        if not run:
            raise LookupError(task_id)
        if task_id in RUNNING:
            RUNNING[task_id].cancel()                    # _execute saves the finished stages and cleans up
            return {"task_id": task_id, "status": "STOPPING"}
        if run.get("status") not in ("RUNNING", *WAITING.values()):
            raise ValueError(f"run is already {run.get('status')}")
        await remove_run_containers(run_key(task_id))
        await self.repository.update_run(task_id, {"status": "STOPPED", "overall": "STOPPED", "pending": None,
                                                   "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_END, "STOPPED by the user",
                                 data={"overall": "STOPPED", "status": "STOPPED"})
        return {"task_id": task_id, "status": "STOPPED"}

    def pdf_path(self, task_id: str) -> Path:
        return RUNS_DIR / task_id / "report.pdf"


def _tests_summary(steps: dict) -> dict:
    cases = [c for sid, s in steps.items() if s.get("item_type") == "tests" and (sid.startswith("test.") or sid in ("functional", "ui_tests"))
             for c in s.get("items") or []]
    return {"total": len(cases), "passed": sum(c.get("status") == "passed" for c in cases)}
