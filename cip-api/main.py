"""
CIP API – agentic CI/CD pipeline (FastAPI + LangGraph + MCP), same structure as sdlc-api.

    uvicorn main:app --reload --port 8000
"""

import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings import CORS_ORIGINS, DOCKER_MCP_URL, ENVIRONMENT, RUNS_DIR, SCANNER_MCP_URL, STREAM_DB_PATH, env
from graph_builders.pipeline_graph_builder import get_pipeline_graph
from mcp_services.mcp_clients.mcp_tool_client import ipv4, reachable
from repositories.pipeline_repository import PipelineRepository
from routers import llm_router, pipeline_router, settings_router
from routers.settings_router import load_sonar
from services.stream_event_writer import stream_writer
from utils.mongo_connection import get_mongo_client

if sys.platform == "win32":                         # stable loop for subprocesses on Windows (as in sdlc-api)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


MCP_SERVERS = {"scanner": ("mcp_services.mcp_servers.scanner_mcp.server", SCANNER_MCP_URL),
               "docker": ("mcp_services.mcp_servers.docker_mcp.server", DOCKER_MCP_URL)}


async def start_mcp_servers() -> list[subprocess.Popen]:
    """Start the local MCP servers that are not running yet (same Python as the API), so the agents really call
    their tools over MCP. Off with start_mcp_servers=false in .env (e.g. when they run elsewhere)."""
    if env("start_mcp_servers", "true").lower() == "false":
        return []
    procs = []
    for name, (module, url) in MCP_SERVERS.items():
        if "localhost" in url or "127.0.0.1" in url:
            if not await reachable(url):
                procs.append(subprocess.Popen([sys.executable, "-m", module], cwd=str(Path(__file__).parent)))
                logging.info("started the %s MCP server (%s)", name, url)
    return procs


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
        await PipelineRepository().stop_unfinished_runs("the API was restarted while the run was in progress")
    except Exception:
        logging.exception("MongoDB not reachable – set mongo_db_url in .env")
    try:
        await load_sonar()                          # SonarQube URL / token saved in Settings → scanners
    except Exception:
        logging.exception("could not load the SonarQube settings")
    mcp_procs = await start_mcp_servers()
    yield
    for p in mcp_procs:
        p.terminate()
    await stream_writer.close()


docs = {} if ENVIRONMENT == "development" else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="DevOps – Agentic CI/CD", version="2.0", lifespan=lifespan, **docs)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(pipeline_router.router)
app.include_router(llm_router.router)
app.include_router(settings_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/mcp")
async def mcp_health():
    """Are the MCP servers up? (When one is down the agents call the same tools in-process.)"""
    return {name: {"url": ipv4(url), "up": await reachable(url)} for name, (_, url) in MCP_SERVERS.items()}
