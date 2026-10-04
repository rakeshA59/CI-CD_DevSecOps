"""
Pipeline Repository – MongoDB access for pipeline runs and app settings.

Collections:
    pipeline_runs   one document per run (task_id, source, status, steps, gates, report …)
    app_settings    key/value settings chosen in the UI (default LLM provider)
"""

import datetime as dt
from typing import Any, Optional

from utils.mongo_connection import get_mongo_db

RUNS = "pipeline_runs"
SETTINGS = "app_settings"


class PipelineRepository:
    async def create_run(self, doc: dict) -> None:
        db = await get_mongo_db()
        await db[RUNS].insert_one({**doc, "created_at": dt.datetime.now(dt.timezone.utc).isoformat()})

    async def update_run(self, task_id: str, fields: dict) -> None:
        db = await get_mongo_db()
        await db[RUNS].update_one({"task_id": task_id}, {"$set": fields})

    async def get_run(self, task_id: str) -> Optional[dict]:
        db = await get_mongo_db()
        return await db[RUNS].find_one({"task_id": task_id}, {"_id": 0})

    async def list_runs(self, limit: int = 50) -> list[dict]:
        db = await get_mongo_db()
        projection = {"_id": 0, "task_id": 1, "source": 1, "source_type": 1, "repo": 1, "status": 1, "overall": 1,
                      "created_at": 1, "finished_at": 1, "duration_s": 1, "provider": 1, "source_info.branch": 1,
                      "source_info.commit": 1}
        return await db[RUNS].find({}, projection).sort("created_at", -1).limit(limit).to_list(length=limit)

    async def get_setting(self, key: str, default: Any = None) -> Any:
        db = await get_mongo_db()
        doc = await db[SETTINGS].find_one({"key": key})
        return doc["value"] if doc else default

    async def set_setting(self, key: str, value: Any) -> None:
        db = await get_mongo_db()
        await db[SETTINGS].update_one({"key": key}, {"$set": {"key": key, "value": value}}, upsert=True)
