"""
Application settings.

Everything comes from environment variables (.env), the same way sdlc-api reads its configuration
(lower-case keys such as mongo_db_url, openai_api_key; the upper-case form is accepted too).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default=""):
    """`name` from .env (lower-case, sdlc-api style) or its upper-case form."""
    value = os.getenv(name) or os.getenv(name.upper())
    return value.strip().strip("'\"") if value else default


BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = env("environment", "development")          # development | production (production hides /docs)
RUNS_DIR = Path(env("cip_runs_dir", BASE_DIR / "runs")).resolve()
STREAM_DB_PATH = Path(env("cip_stream_db", BASE_DIR / "stream_events.db")).resolve()

MONGO_DB_URL = env("mongo_db_url", "mongodb://localhost:27017")
MONGO_DB_NAME = env("mongo_db_name", "cip")

# Default LLM provider when the UI has not saved one: azure_openai | openai | anthropic | gemini | none
DEFAULT_LLM_PROVIDER = env("llm_provider", "azure_openai")

# Quality gate thresholds (deterministic – the LLM never decides pass / fail)
GATES = {
    "security": {"critical": int(env("gate_critical", 0)), "high": int(env("gate_high", 0)),
                 "secrets": int(env("gate_secrets", 0))},
    "testing": {"pass_rate": float(env("gate_pass_rate", 100)), "coverage": float(env("gate_coverage", 60))},
    "container": {"critical": int(env("gate_image_critical", 0)), "high": int(env("gate_image_high", 5))},
    "functional": {"pass_rate": float(env("gate_functional_pass_rate", 100))},
    "ui": {"pass_rate": float(env("gate_ui_pass_rate", 80))},          # browser checks are noisier than API checks
}

# MCP servers (SSE). When a server is not running, the client calls the same functions in-process.
SCANNER_MCP_URL = env("scanner_mcp_url", "http://127.0.0.1:8051/sse")
DOCKER_MCP_URL = env("docker_mcp_url", "http://127.0.0.1:8052/sse")

# Selenium (UI browser tests): Chrome is found automatically and Selenium Manager downloads the matching driver.
# Set these only for a portable Chrome / an offline driver.
CHROME_BINARY = env("chrome_binary", "")
CHROMEDRIVER_PATH = env("chromedriver_path", "")

CORS_ORIGINS = env("cors_origins", "http://localhost:5173,http://127.0.0.1:5173").split(",")
