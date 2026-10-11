"""
JSON-file backend for pipeline runs and app settings – drop-in replacement for MongoDB.

Storage layout (inside DATA_DIR, default cip-api/data/):
    runs.json       [{...run doc...}, ...]   one entry per pipeline run
    settings.json   {"key": value, ...}      key/value settings chosen in the UI

Thread-safety: an asyncio.Lock serialises writes so concurrent agents don't corrupt the file.
Reads always go through the file (no stale cache). The files are human-readable and can be
backed up with a simple copy.
"""

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any, Optional

from core.settings import BASE_DIR

DATA_DIR = Path(BASE_DIR / "data").resolve()
RUNS_FILE = DATA_DIR / "runs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

_lock = asyncio.Lock()


def _ensure_files() -> None:
    """Create the data directory and seed empty files if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RUNS_FILE.exists():
        RUNS_FILE.write_text("[]", encoding="utf-8")
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text("{}", encoding="utf-8")


def _read_runs() -> list[dict]:
    _ensure_files()
    try:
        return json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        logging.warning("[JsonRepo] runs.json is corrupt – starting fresh")
        return []


def _write_runs(runs: list[dict]) -> None:
    _ensure_files()
    RUNS_FILE.write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")


def _read_settings() -> dict:
    _ensure_files()
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        logging.warning("[JsonRepo] settings.json is corrupt – starting fresh")
        return {}


def _write_settings(settings: dict) -> None:
    _ensure_files()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, default=str), encoding="utf-8")


def _apply_projection(doc: dict, projection: dict) -> dict:
    """Minimal MongoDB-style projection: {field: 1} keeps only those fields; nested dotted keys (a.b) are supported."""
    if not projection:
        d = dict(doc)
        d.pop("_id", None)
        return d
    out = {}
    for key, include in projection.items():
        if key == "_id" and not include:
            continue
        if not include:
            continue
        if "." in key:
            parts = key.split(".")
            src, dst = doc, out
            for p in parts[:-1]:
                src = src.get(p) if isinstance(src, dict) else None
                if src is None:
                    break
                dst = dst.setdefault(p, {})
            if src is not None and isinstance(src, dict) and parts[-1] in src:
                dst[parts[-1]] = src[parts[-1]]
        elif key in doc:
            out[key] = doc[key]
    return out


def _match_filter(doc: dict, filt: dict) -> bool:
    """Minimal MongoDB-style filter: equality and $in."""
    for key, cond in filt.items():
        val = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


def _set_nested(doc: dict, key: str, value: Any) -> None:
    """Set a possibly dotted key: 'a.b.c' = v → doc['a']['b']['c'] = v."""
    if "." not in key:
        doc[key] = value
        return
    parts = key.split(".")
    target = doc
    for p in parts[:-1]:
        target = target.setdefault(p, {})
    target[parts[-1]] = value


class JsonFileRepository:
    """Same interface as PipelineRepository but backed by JSON files."""

    async def create_run(self, doc: dict) -> None:
        async with _lock:
            runs = _read_runs()
            entry = {**doc, "created_at": doc.get("created_at") or dt.datetime.now(dt.timezone.utc).isoformat()}
            entry.pop("_id", None)
            runs.insert(0, entry)  # newest first
            _write_runs(runs)

    async def update_run(self, task_id: str, fields: dict) -> None:
        async with _lock:
            runs = _read_runs()
            for run in runs:
                if run.get("task_id") == task_id:
                    for k, v in fields.items():
                        _set_nested(run, k, v)
                    break
            _write_runs(runs)

    async def stop_unfinished_runs(self, reason: str) -> None:
        """Runs still RUNNING / WAITING when the API starts were cut off by a restart."""
        async with _lock:
            runs = _read_runs()
            changed = False
            for run in runs:
                if run.get("status") in ("RUNNING", "WAITING_INPUT", "WAITING_APPROVAL"):
                    run["status"] = "STOPPED"
                    run["overall"] = "STOPPED"
                    run["pending"] = None
                    run["stopped_reason"] = reason
                    run["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    changed = True
            if changed:
                _write_runs(runs)

    async def get_run(self, task_id: str) -> Optional[dict]:
        runs = _read_runs()
        for run in runs:
            if run.get("task_id") == task_id:
                out = dict(run)
                out.pop("_id", None)
                return out
        return None

    async def list_runs(self, limit: int = 50, dashboard: bool = False) -> list[dict]:
        runs = _read_runs()
        projection = {"_id": 0, "task_id": 1, "source": 1, "source_type": 1, "repo": 1, "app_name": 1, "pipeline_name": 1,
                       "status": 1, "overall": 1, "created_at": 1, "finished_at": 1, "duration_s": 1, "provider": 1,
                       "source_info.branch": 1, "source_info.commit": 1, "mode": 1}
        if dashboard:
            projection.update({"stage_summary": 1, "tests_summary": 1, "findings_by_severity": 1, "pending.type": 1,
                               "report.overall": 1, "report.root_cause": 1})
        # runs are stored newest-first (create_run inserts at 0)
        sorted_runs = sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)
        return [_apply_projection(r, projection) for r in sorted_runs[:limit]]

    async def get_setting(self, key: str, default: Any = None) -> Any:
        settings = _read_settings()
        return settings.get(key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        async with _lock:
            settings = _read_settings()
            settings[key] = value
            _write_settings(settings)
