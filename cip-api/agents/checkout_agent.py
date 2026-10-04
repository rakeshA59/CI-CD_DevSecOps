"""
Checkout Agent.

Gets the code into the run's workspace:
    GitHub URL / org/repo  → git clone (GITHUB_TOKEN sent as an HTTP header only, never stored)
    local folder           → copied as it is on disk (no clone needed); git details read when it is a git repo
"""

import asyncio
import base64
import os
import re
import shutil
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from core.settings import env
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, run_command, step_record

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".idea", ".gradle", ".pytest_cache"}


def is_remote(source: str) -> bool:
    return source.startswith(("https://", "http://", "git@")) or (bool(re.match(r"^[\w.-]+/[\w.-]+$", source))
                                                                   and not Path(source).exists())


class CheckoutAgent:
    def __init__(self) -> None:
        self.node_name = "checkout_agent"

    async def _git(self, args: str, cwd: Path) -> str:
        res = await run_command(f"git {args}", cwd, timeout=60)
        return res["output"].strip() if res["code"] == 0 else ""

    async def _git_info(self, repo: Path) -> dict:
        info = {k: await self._git(a, repo) for k, a in (("commit", "rev-parse HEAD"), ("branch", "rev-parse --abbrev-ref HEAD"),
                                                         ("message", "log -1 --format=%s"), ("author", "log -1 --format=%an"),
                                                         ("date", "log -1 --format=%cI"))}
        status = await self._git("status --porcelain", repo)
        info["uncommitted"] = [ln[3:] for ln in status.splitlines() if ln.strip()][:30]
        return info

    def _copy(self, src: Path, dest: Path) -> dict:
        copied, skipped = 0, set()
        for dirpath, dirs, files in os.walk(src):
            rel = Path(dirpath).relative_to(src)
            skipped |= {d for d in dirs if d in SKIP}
            dirs[:] = [d for d in dirs if d not in SKIP]
            for f in files:
                (dest / rel).mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(Path(dirpath) / f, dest / rel / f)
                    copied += 1
                except OSError:
                    pass
        return {"files_copied": copied, "left_out": sorted(skipped)}

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        """Clone or copy the source; record where the code came from."""
        task_id, source, t0 = state["task_id"], state["source"].strip(), time.time()
        ws = Path(state["workspace"])
        await emit(task_id, self.node_name, StreamStatus.START, f"Getting the code from {source}")
        try:
            if is_remote(source):
                url = source if "://" in source or source.startswith("git@") else f"https://github.com/{source}.git"
                header = ""
                if env("github_token") and "github.com" in url:
                    token = base64.b64encode(f"x-access-token:{env('github_token')}".encode()).decode()
                    header = f'-c http.extraHeader="Authorization: Basic {token}" '
                branch = f"--branch {state['branch']} " if state.get("branch") else ""
                await emit(task_id, self.node_name, StreamStatus.COMMAND, f"$ git clone --depth 1 {branch}{url}")
                res = await run_command(f"git {header}clone --depth 1 {branch}{url} \"{ws}\"", ws.parent, timeout=900)
                if res["code"] != 0:
                    raise RuntimeError(res["output"].replace(header, "")[-800:])
                info = {"type": "git repo", "url": url, **await self._git_info(ws)}
                message = f"cloned {url} @ {info['commit'][:10]} ({info['branch']})"
            else:
                src = Path(source).expanduser().resolve()
                if not src.is_dir():
                    raise FileNotFoundError(f"local folder not found: {src}")
                await emit(task_id, self.node_name, StreamStatus.COMMAND, f"copy {src} → workspace (no git clone needed)")
                info = {"type": "local folder", "path": str(src), **await asyncio.to_thread(self._copy, src, ws)}
                if (src / ".git").exists():
                    info.update(await self._git_info(src))
                message = (f"local folder {src} – {info['files_copied']} files copied"
                           + (f", git {info.get('branch')} @ {info.get('commit', '')[:10]}" if info.get("commit") else ", not a git repo")
                           + (f", {len(info['uncommitted'])} uncommitted change(s) included" if info.get("uncommitted") else ""))
            await emit(task_id, self.node_name, StreamStatus.END, message, data=info)
            return {"source_info": info, "source_type": info["type"],
                    "steps": {"checkout": step_record("checkout", "git clone" if info["type"] == "git repo" else "copy local folder",
                                                      "checkout", "passed", message, summary=info, started=t0)}}
        except Exception as e:  # noqa: BLE001
            await emit(task_id, self.node_name, StreamStatus.ERROR, f"checkout failed: {e}")
            return {"stopped_at": "checkout", "errors": [f"checkout: {e}"],
                    "steps": {"checkout": step_record("checkout", "checkout", "checkout", "failed", str(e), started=t0)}}
