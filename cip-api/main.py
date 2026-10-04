"""
CIP API – agentic CI/CD pipeline (FastAPI + LangGraph + MCP), same structure as sdlc-api.

    uvicorn main:app --reload --port 8000
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings import CORS_ORIGINS, ENVIRONMENT, RUNS_DIR, STREAM_DB_PATH
from graph_builders.pipeline_graph_builder import get_pipeline_graph
from routers import llm_router, pipeline_router
from services.stream_event_writer import stream_writer
from utils.mongo_connection import get_mongo_client

if sys.platform == "win32":                         # stable loop for subprocesses on Windows (as in sdlc-api)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    await stream_writer.initialize(STREAM_DB_PATH)
    try:
        await get_pipeline_graph()
    except Exception:
        logging.exception("Failed to compile the pipeline graph")
    try:
        await get_mongo_client()
        logging.info("MongoDB client ready")
    except Exception:
        logging.exception("MongoDB not reachable – set mongo_db_url in .env")
    yield
    await stream_writer.close()


docs = {} if ENVIRONMENT == "development" else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="CIP – Agentic CI/CD", version="2.0", lifespan=lifespan, **docs)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(pipeline_router.router)
app.include_router(llm_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
