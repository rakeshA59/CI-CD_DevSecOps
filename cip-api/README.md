# CIP – agentic CI/CD (cip-api + cip-app)

The rewrite of CIP in the same architecture as **sdlc-dev-group**: FastAPI + **LangGraph** agents + LangChain tools +
**MCP** servers + **MongoDB** on the back end, React 19 + Vite + Tailwind v4 + shadcn/ui + Zustand on the front end.

## How a run works

```
checkout_agent → planner_agent → security_agent → component lanes (parallel, LangGraph Send)
                                                     build_agent → test_agent → container_agent
               → deploy_agent → functional_test_agent → report_agent
```

| Agent | What it decides / does | Tools |
|---|---|---|
| checkout_agent | git clone (URL) or copy (local folder), git details, uncommitted changes | git |
| planner_agent | explores the repo with its tools and plans components, build/test/package commands, ports, which stages run (rules first, LLM corrects) | list_files, read_file |
| security_agent | runs the chosen scanners in parallel (see below), LLM triage of critical/high findings | Scanner MCP: run_scanner |
| build_agent | runs the build; a missing JDK/Maven/Node/Go is installed; a failed build is investigated and fixed by the LLM, then retried | run_command, read_file, write_file, install_toolchain |
| test_agent | runs the repo's tests (JUnit / Jest / go test reports + coverage), repairs a broken test setup, **writes tests when there are none** (LLM) | same |
| container_agent | packages, uses the repo Dockerfile or writes one, builds + scans the image | Docker MCP, Scanner MCP |
| deploy_agent | runs all images on one dev network, waits for health | Docker MCP |
| functional_test_agent | crawls the running app, calls OpenAPI GET endpoints, LLM user-journey checks | HTTP |
| report_agent | overall result, root cause (+ LLM explanation), PDF | – |

Gates (security, tests, container, functional) are fixed thresholds from `.env` – the LLM never decides pass/fail.

## LLM providers

`cip-api/.env` uses the same key names as sdlc-api (see `.env.example`):

| Provider | Keys |
|---|---|
| Azure OpenAI | `openai_base_url`, `openai_api_key`, `openai_deployment_name`, `openai_api_version` |
| OpenAI | `openai_api_key`, `openai_model` (leave `openai_deployment_name` empty) |
| Anthropic | `anthropic_api_key`, `anthropic_deployment_name` / `anthropic_model`, optional `anthropic_base_url` |
| Gemini | `google_api_key`, `gemini_model` |

`llm_provider` is the default; the run form has a provider dropdown (preselected with the default saved on the
Settings page); `none` = rules only. `environment="production"` hides the API docs at /docs.

## Run (Windows, from the CI-CD_DevSecOps folder)

One click: `start_agentic.bat` (uses your `venv` folder or creates `.venv`, installs, starts the API – which starts both MCP
servers – and the app, opens the browser).

Manual (Command Prompt), one window per step:
```
REM 1. backend setup (once), then fill in the keys and mongo_db_url in cip-api\.env
REM    use a real Python 3.12/3.13 install ("py -0p" lists them); a venv breaks if its base Python is removed
cd cip-api
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
REM    all security scanners -> cip-api\.scanners (own venv + binaries; never into .venv)
.venv\Scripts\python scripts\install_scanners.py
copy .env.example .env

REM 2. API on :8000 (no --reload: runs write into cip-api\runs and would restart it). It starts the scanner (:8051)
REM    and docker (:8052) MCP servers itself (start_mcp_servers=false in .env to run them elsewhere).
cd cip-api
.venv\Scripts\python -m uvicorn main:app --port 8000

REM 3. frontend on :5173
cd cip-app
npm install
npm run dev
```
`mongo_db_url="memory://"` runs without MongoDB (runs are lost on restart).

## Two modes: Quick run and Guided DevOps flow

The start page has a switch. **Quick run** is the original fixed flow (unchanged). **Guided DevOps flow** is the
Architect's flow, run locally:

```
checkout → understand the tech stack → questionnaire (⏸ you answer) → derive the pipeline (stages + tools + MCP)
→ security scan → build · unit tests · package · containerise (per component, parallel, self-healing)
→ release to the local registry (localhost:5000) → deploy dev → functional tests → publish test results
→ approval (⏸ approve / reject) → deploy UAT → final report + PDF
```

| Piece | Where |
|---|---|
| Questionnaire + stage catalogue (what is asked, which stages / tools / MCP server, why) | `config/devops_flow.yml` |
| Graph (LangGraph `interrupt()` pauses, in-memory checkpointer, thread = task id) | `graph_builders/guided_graph_builder.py` |
| Discovery + questionnaire (pre-filled from the code: languages, Dockerfiles, CI / k8s / Terraform files) | `agents/questionnaire_agent.py` |
| Pipeline designer – deterministic, no LLM | `agents/pipeline_designer_agent.py` |
| Release to registry (`docker_registry`, `docker_push` on the Docker MCP) | `agents/release_agent.py` |
| Publish test results (JUnit XML + HTML) | `agents/publish_tests_agent.py` |
| Human approval before UAT | `agents/approval_gate_agent.py` |
| UAT deploy (own network + ports, left running) | `DeployAgent("uat")` |
| Self-healing loop (read log → fix → retry, `self_heal_attempts` times) | build, test-setup and Docker-image steps; guided flow also: image CVEs (harden the Dockerfile → rebuild → rescan) and dev deploy (read the container log → fix port / CMD / binding → redeploy) |
| UI browser tests (Selenium, headless Chrome): pages render, no console errors, navigation, forms, LLM user journeys, a screenshot per test | `agents/ui_test_agent.py` – needs Chrome on the machine |
| Security review – **HITL – review reports** after the scans (both flows; switch `security_review` on the run form) | `agents/security_review_agent.py` – approve continues, reject stops the pipeline |
| One tool per scan type (SAST · SCA + IaC · secrets · lint per language), chosen by the tech stack, override in the questionnaire, fallback when it cannot run | `scanners.py` `pick_scanners()` / `FALLBACK` |
| Pipeline · **Graph** · **Logs** views of a run (graph: stages, component branches, sub-step panels, zoom / layout / fit; logs: tabs, search, stage + step filter, export) | `cip-app/src/features/pipeline/components/graph/`, `LogsView.jsx` |
| ⓘ on every step: hover summary, click = full step report (HTML) | `config/step_docs.yml`, `services/step_report_html.py`, `GET /pipelines/{id}/steps/{step}/report.html` |
| Settings: LLM providers, infra providers (AWS / Azure / GCP credentials, encrypted), dev / test / prod environments | `routers/settings_router.py`, `utils/secret_box.py` (key: `settings_secret_key` or `.settings.key`) |
| Test-case explanations (what it is about · what it checks · how · expected · actual · why) | `utils/test_explain.py`, functional + UI agents; shown under each test in the UI, `test-report.html` and the PDF |
| Stage reports (what · where · how · why · result · suggestions · blockers) | `utils/stage_reports.py` – every step, both modes, also in the PDF |
| Common dashboard | `GET /pipelines/dashboard`, page **Dashboard** |

Answers like GitLab / Jenkins / AWS / Azure / Kubernetes are recorded (marked *later*) – everything runs locally in
this version. A paused run lives in the API's memory: restarting the API loses runs that wait for answers or approval.

## Security scanners

| Category | Scanner | Runs by default when | Installed by |
|---|---|---|---|
| SAST | Semgrep | always | `install_scanners.py` (.scanners venv) |
| SAST | Bandit | Python in the repo | `install_scanners.py` (.scanners venv) |
| SAST | CodeQL | the CLI is installed | `install_scanners.py --codeql` (~1 GB) |
| Lint (never blocks the gate) | Ruff · ESLint | Python · JS/TS with an ESLint config | .scanners venv · the repo's own node_modules |
| Dependencies | Trivy fs (+ Dockerfile / IaC) · OSV-Scanner | always | `install_scanners.py` (binaries) |
| Dependencies | pip-audit · npm audit | Python · Node | .scanners venv · Node.js |
| Dependencies | Snyk Open Source | `snyk_token` is set | `install_scanners.py` (binary) |
| Secrets | Gitleaks · TruffleHog | always | `install_scanners.py` (binaries) |
| Platform | SonarQube | `sonar_host_url` + `sonar_token` are set (.env or Settings → Scanners) | your SonarQube server (scanner CLI or its Docker image) |
| Platform | GitHub alerts: Dependabot, code scanning, **secret scanning** | GitHub source + `github_token` | – (GitHub API) |

The run form lets you switch off "Automatic" and pick scanners yourself. Self-healing: a missing scanner is installed
into `.scanners` before the scan; a scanner whose install is broken (ImportError, …) is reinstalled and rerun, then –
with an LLM – the agent repairs the install from the error output; only then its Docker image / the fallback tool of
the same type is used. Settings → Scanners shows the MCP servers, each scanner's state (Install / Repair) and the
SonarQube connection. `python scripts\install_scanners.py` can still be run by hand (`... install_scanners.py trivy`
for one).

Why a separate `.scanners` folder: Semgrep pins old `opentelemetry` / `protobuf` / `mcp` versions; installed into the
API's venv it downgrades them and breaks FastAPI and the Google / LangChain packages – and a copy found in the
API's venv is never used.

## API

| Method | Path | |
|---|---|---|
| POST | /pipelines/start | `{source, branch, llm_provider, options}` → task_id |
| GET | /pipelines | recent runs (date/time, local folder or git repo, result) |
| GET | /pipelines/scanners | scanner catalogue + what is installed / configured |
| GET | /pipelines/dashboard | common dashboard: totals + every run with its stage statuses |
| POST | /pipelines/{task_id}/answers | guided flow: `{answers}` → resumes a run waiting for the questionnaire |
| POST | /pipelines/{task_id}/approval | guided flow: `{decision: approve\|reject, by, comment}` → resumes a run waiting for approval |
| GET | /pipelines/{task_id}/test-results/{junit.xml\|test-report.html} | published test results |
| GET | /pipelines/{task_id} | full run (steps, gates, components, report) |
| GET | /pipelines/{task_id}/stream | live agent events (SSE) |
| GET | /pipelines/{task_id}/report.pdf | PDF report |
| GET | /llm/providers · PUT /llm/default · POST /llm/test | providers configured, default, connection test |
