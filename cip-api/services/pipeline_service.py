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
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from langgraph.types import Command

from agents.checkout_agent import is_remote
from core.settings import DEFAULT_LLM_PROVIDER, RUNS_DIR, env
from graph_builders.guided_graph_builder import get_guided_graph
from graph_builders.pipeline_graph_builder import get_pipeline_graph
from mcp_services.mcp_servers.docker_mcp.docker_ops import remove_run_containers, remove_run_images
from repositories.pipeline_repository import PipelineRepository
from services.stream_event_writer import StreamStatus, stream_writer
from utils.app_name import clean_app_name, slug
from utils.stage_reports import stage_summary, with_reports

RUNNING: dict[str, asyncio.Task] = {}
WAITING = {"questionnaire": "WAITING_INPUT", "approval": "WAITING_APPROVAL", "security_review": "WAITING_APPROVAL"}
PAUSED_FOR = {"questionnaire": "your answers to the questionnaire", "security_review": "a human review of the security reports (HITL)"}


def run_key(task_id: str) -> str:
    """The part of a task id that every container / network name of the run contains (see deploy_agent)."""
    return task_id[-12:].lower().strip("-")


BACKGROUND: set[asyncio.Task] = set()                 # keeps fire-and-forget clean-ups alive until they finish
HEAVY = {"node_modules", ".cip-venv", ".venv", "venv", "target", ".gradle", "__pycache__", ".pytest_cache"}


def _free_disk(workspace: Path) -> None:
    """Delete the re-creatable folders of a finished run (dependencies, build output); the code, the reports and
    the test results stay. Plus scanner temp folders older than an hour (Trivy image exports, CodeQL databases)."""
    def walk(folder: Path):
        for d in folder.iterdir() if folder.is_dir() else []:
            if d.is_dir() and not d.is_symlink():
                if d.name in HEAVY:
                    shutil.rmtree(d, ignore_errors=True)
                else:
                    walk(d)
    walk(workspace)
    tmp = Path(tempfile.gettempdir())
    for d in [*tmp.glob("trivy-*"), *tmp.glob("cip-codeql-*"), *tmp.glob("cip-scanner-*")]:
        try:
            if time.time() - d.stat().st_mtime > 3600:
                shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink()
        except OSError:
            pass


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    BACKGROUND.add(task)
    task.add_done_callback(BACKGROUND.discard)


async def cleanup_run(task_id: str, workspace: Path) -> None:
    """After a run ends: free the disk it used (cleanup_after_run=false in .env keeps everything)."""
    if env("cleanup_after_run", "true").lower() == "false":
        return
    try:
        await asyncio.to_thread(_free_disk, workspace)
        await remove_run_images(re.sub(r"[^a-z0-9]", "", task_id.lower())[-16:])
    except Exception:  # noqa: BLE001 – cleanup never fails a run
        logging.exception("cleanup of %s failed", task_id)


def _repo_name(source: str) -> str:
    return re.sub(r"\.git$", "", source.rstrip("/\\").replace("\\", "/").split("/")[-1]) or "repo"


class PipelineService:
    def __init__(self) -> None:
        self.repository = PipelineRepository()

    async def start(self, source: str, branch: str | None, provider: str | None, options: dict, mode: str = "guided", pipeline_name: str | None = None) -> dict:
        """Create the run document and launch the graph in the background."""
        provider = provider or await self.repository.get_setting("llm_provider", DEFAULT_LLM_PROVIDER)
        repo = _repo_name(source)
        app_name = clean_app_name(repo)
        task_id = f"{slug(app_name)}-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        run_dir = RUNS_DIR / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        mode = "guided" if mode == "guided" else "quick"
        doc = {"task_id": task_id, "source": source, "repo": repo, "app_name": app_name, "branch": branch, "provider": provider, "options": options,
               "source_type": "git repo" if is_remote(source) else "local folder", "status": "RUNNING", "mode": mode,
               "pipeline_name": pipeline_name or None}
        await self.repository.create_run(doc)
        state = {**doc, "run_dir": str(run_dir), "workspace": str(run_dir / "workspace"), "steps": {}, "lanes": {},
                 "findings": [], "gates": {}, "errors": [], "step_index": 0}
        RUNNING[task_id] = asyncio.create_task(self._execute(task_id, state, mode))
        return {"task_id": task_id, "provider": provider, "mode": mode}

    async def resume(self, task_id: str, kind: str, payload: dict) -> dict:
        """Continue a paused run with the questionnaire answers or a review / approval decision."""
        run = await self.repository.get_run(task_id)
        if not run:
            raise LookupError("run not found")
        if task_id in RUNNING or run.get("status") != WAITING.get(kind):
            raise ValueError(f"run is {run.get('status')}, not waiting for {kind}")
        await self.repository.update_run(task_id, {"status": "RUNNING", "pending": None})
        RUNNING[task_id] = asyncio.create_task(self._execute(task_id, Command(resume=payload), run.get("mode") or "quick"))
        return {"task_id": task_id, "resumed": kind}

    async def _execute(self, task_id: str, payload, mode: str) -> None:
        t0 = time.time()
        first = not isinstance(payload, Command)
        if first:
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_START,
                                     f"Pipeline started for {payload['source']} ({'guided DevOps flow' if mode == 'guided' else 'quick run'})")
        graph = await (get_guided_graph() if mode == "guided" else get_pipeline_graph())
        config = {"recursion_limit": 120 if mode == "guided" else 60, "metadata": {"task_id": task_id},
                  "configurable": {"thread_id": task_id}}    # the checkpointer keeps a paused run under its task id
        pending, latest = None, {}
        try:
            async for latest in graph.astream(payload, config, stream_mode="values"):   # = ainvoke, keeping the latest state
                pass
            snapshot = await graph.aget_state(config)
            final = snapshot.values
            pending = next((i.value for t in snapshot.tasks for i in (t.interrupts or [])), None) if snapshot.next else None
            status = WAITING.get((pending or {}).get("type"), "WAITING_INPUT") if pending else "COMPLETED"
        except asyncio.CancelledError:                    # Stop button
            latest = (await graph.aget_state(config)).values or latest
            final, status = {**(payload if first else {}), **latest, "overall": "STOPPED"}, "STOPPED"
        except Exception as e:  # noqa: BLE001
            logging.exception("[PipelineService] run %s crashed", task_id)
            base = payload if first else {}
            final, status = {**base, "errors": base.get("errors", []) + [str(e)], "overall": "ERROR"}, "ERROR"
        run = await self.repository.get_run(task_id) or {}
        steps = with_reports(final.get("steps"))
        await self.repository.update_run(task_id, {
            "status": status, "overall": final.get("overall"), "pending": pending,
            "app_name": final.get("app_name") or run.get("app_name"),
            "duration_s": round((run.get("duration_s") or 0) + time.time() - t0, 1),
            **({} if pending else {"finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}),
            "source_info": final.get("source_info"), "source_type": final.get("source_type", run.get("source_type")),
            "components": final.get("components"), "execution_plan": final.get("execution_plan"), "steps": steps,
            "stage_summary": stage_summary(steps), "gates": final.get("gates"), "deploy": final.get("deploy"),
            "report": final.get("report"), "errors": final.get("errors"), "spec": final.get("spec"),
            "answers": final.get("answers"), "detected": final.get("detected"), "release": final.get("release"),
            "uat": final.get("uat"), "approval": final.get("approval"), "security_review": final.get("security_review"),
            "tests_summary": _tests_summary(steps),
            "findings_by_severity": {s: sum(f["severity"] == s for f in final.get("findings", []) if f.get("category") != "code_quality")
                                     for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}})
        if pending:
            what = PAUSED_FOR.get(pending["type"]) or f"approval before {pending.get('target', '').upper()}"
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_PAUSE, f"PAUSED – waiting for {what}",
                                     data={"status": status, "pending": pending["type"]})
        elif status != "STOPPED":                         # a stop already told the UI (see stop())
            await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_END, f"OVERALL: {final.get('overall')}",
                                     data={"overall": final.get("overall"), "status": status})
        RUNNING.pop(task_id, None)
        if not pending:                                   # background: Docker may be slow – never hold up the run's end
            _background(self._after(task_id, status, Path(final.get("workspace") or RUNS_DIR / task_id / "workspace")))

    @staticmethod
    async def _after(task_id: str, status: str, workspace: Path) -> None:
        if status == "STOPPED":
            await remove_run_containers(run_key(task_id))
        await cleanup_run(task_id, workspace)

    async def stop(self, task_id: str) -> dict:
        """Stop a run: a running one is cancelled (its command is killed); a paused one is closed."""
        run = await self.repository.get_run(task_id)
        if not run:
            raise LookupError(task_id)
        if run.get("status") not in ("RUNNING", *WAITING.values()):
            raise ValueError(f"run is already {run.get('status')}")
        task = RUNNING.get(task_id)
        await self.repository.update_run(task_id, {"status": "STOPPED", "overall": "STOPPED", "pending": None,
                                                   "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        await stream_writer.push(task_id, "SYSTEM", StreamStatus.SYSTEM_END,
                                 "STOPPED by the user – finished stages are kept, the run's containers are being removed",
                                 data={"overall": "STOPPED", "status": "STOPPED"})
        if task:
            task.cancel()                                 # _execute saves the finished stages, then cleans up
        else:                                             # paused run: nothing is executing
            _background(self._after(task_id, "STOPPED", RUNS_DIR / task_id / "workspace"))
        return {"task_id": task_id, "status": "STOPPED"}

    def pdf_path(self, task_id: str) -> Path:
        return RUNS_DIR / task_id / "report.pdf"


def _tests_summary(steps: dict) -> dict:
    cases = [c for sid, s in steps.items() if s.get("item_type") == "tests" and (sid.startswith("test.") or sid in ("functional", "ui_tests"))
             for c in s.get("items") or []]
    return {"total": len(cases), "passed": sum(c.get("status") == "passed" for c in cases)}
