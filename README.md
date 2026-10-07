# CI-CD_DevSecOps – agentic CI/CD pipeline

DevOps (agentic CI/CD, formerly CIP): LangGraph agents behind FastAPI, MCP servers for scanning and Docker, MongoDB for run records, and a React app.

```
CI-CD_DevSecOps/
├── cip-api/            FastAPI + LangGraph agents + MCP servers (scanner :8051, docker :8052)
├── cip-app/            React 19 + Vite + Tailwind UI (SDLC styling)
└── start_agentic.bat   one-click start on Windows
```

## Run

1. Copy `cip-api/.env.example` to `cip-api/.env` and fill in the keys. The key names are the same as sdlc-api
   (`openai_base_url`, `openai_api_key`, `openai_deployment_name`, `anthropic_api_key`, `google_api_key`, `mongo_db_url`, …).
   `mongo_db_url="memory://"` keeps runs in memory, no MongoDB needed.
2. Double-click `start_agentic.bat`. It creates `cip-api/.venv`, installs packages, starts both MCP servers,
   the API on http://localhost:8000 and the app on http://localhost:5173, then opens the browser.

Manual commands and details: see `cip-api/README.md`.
