"""
Helpers every agent uses: stream an event, run a shell command, build a step record.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from services.stream_event_writer import StreamStatus, stream_writer


async def emit(task_id: str, node: str, status: StreamStatus, message: str = "", parent: str = "SYSTEM", data: Any = None):
    """Stream one event (shown live in the UI) and log it."""
    logging.info("[%s] %s %s", node, getattr(status, "value", status), message[:300])
    await stream_writer.push(task_id=task_id, node=node, parent=parent, status=status, message=message, data=data)


def _kill_tree(pid: int) -> None:
    """Kill a shell command with its children (npm, mvn, … start their own processes)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30)
        else:
            os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


async def run_command(cmd: str, cwd: str | Path, task_id: str = "", node: str = "", timeout: int = 1800,
                      env: Optional[dict] = None) -> dict:
    """Run a shell command (cmd.exe on Windows, sh elsewhere) and return {code, output, seconds}.

    A shell is used on purpose: `mvn`, `npm`, `gradlew` resolve to their .cmd launchers on Windows."""
    if task_id:
        await emit(task_id, node, StreamStatus.COMMAND, f"$ {cmd}", data={"cwd": str(cwd)})
    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, **(env or {})}, start_new_session=sys.platform != "win32",
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_tree(proc.pid)
            return {"code": 124, "output": f"timeout after {timeout}s", "seconds": timeout, "cmd": cmd}
        except asyncio.CancelledError:      # the run was stopped – end the command and everything it started
            _kill_tree(proc.pid)
            raise
        text = out.decode("utf-8", errors="replace")
        return {"code": proc.returncode, "output": text[-60_000:], "seconds": round(time.time() - t0, 1), "cmd": cmd}
    except OSError as e:
        return {"code": 127, "output": f"cannot start: {e}", "seconds": 0, "cmd": cmd}


def step_record(step_id: str, name: str, stage: str, status: str, message: str = "", component: str = "",
                summary: Optional[dict] = None, items: Optional[list] = None, item_type: str = "",
                commands: Optional[list] = None, started: Optional[float] = None, explanation: str = "") -> dict:
    """The record of one pipeline step, as stored in Mongo and shown in the UI / report."""
    return {"id": step_id, "name": name, "stage": stage, "component": component, "status": status,
            "message": message[:2000], "summary": summary or {}, "items": (items or [])[:500], "item_type": item_type,
            "commands": commands or [], "explanation": explanation,
            "duration_s": round(time.time() - started, 1) if started else 0}
