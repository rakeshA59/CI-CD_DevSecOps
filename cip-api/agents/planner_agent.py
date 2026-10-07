"""
Planner Agent (Plan-Execute: plans the whole pipeline upfront).

1. Rules find the build manifests and propose a first plan per component (works without an LLM).
2. With an LLM, the agent explores the repository with its tools (list_files / read_file), corrects the plan –
   commands, test runner, report paths, ports, what is deployable – and explains its decisions.
3. The execution plan (which stages run) is derived from the components and the run options.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import List

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from agent_states.pipeline_state import PipelineState
from agent_tools.workspace_tools import HIDDEN, WorkspaceTools
from agents.tool_loop import tool_loop
from llmapi.llm_provider import LLMProvider
from llmapi.structured_llm import ask_structured
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.app_name import clean_app_name, slug

PY = ".cip-venv\\Scripts\\python" if os.name == "nt" else ".cip-venv/bin/python"


class ComponentPlan(BaseModel):
    name: str = Field(description="short unique name, e.g. backend, frontend or the repo name")
    path: str = Field(description="folder relative to the repo root, '.' for the root")
    language: str
    framework: str = ""
    kind: str = Field(description="web-frontend (a UI of its own) | web-app (a backend that also serves the user-facing UI) "
                                  "| api | service | library | cli")
    serves_ui: str = Field("", description="web-app only: folder of the HTML/JS/CSS UI this backend serves")
    app_dir: str = Field("", description="when path is a parent folder: the backend's sub-folder (relative to path)")
    build_commands: List[str] = Field(description="shell commands, run in `path`, that install dependencies and compile")
    test_command: str = Field("", description="shell command that runs the unit tests and writes a machine-readable report")
    test_reports: List[str] = Field(default_factory=list, description="glob patterns (relative to path) of the test report files")
    package_command: str = ""
    artifacts: List[str] = Field(default_factory=list, description="glob patterns of the built deliverables")
    deployable: bool = Field(description="true when it runs as a server / web site that can be containerised")
    port: int = 0
    has_dockerfile: bool = False
    reasoning: str = Field("", description="one or two sentences: which files proved this")


class RepoPlan(BaseModel):
    components: List[ComponentPlan]
    summary: str = Field(description="what the application is, in one or two sentences")
    app_name: str = Field("", description="short human name of the application (2-4 words) from its README title, UI "
                                          "title or what it does – not the repository slug, no version or hash")


# code that serves a folder of HTML/JS/CSS (FastAPI / Starlette, Flask, Express, Spring, Django, ASP.NET, Go)
SERVES = re.compile(r"StaticFiles|FileResponse|send_from_directory|static_folder|express\.static|sendFile|"
                    r"addResourceHandlers|STATICFILES_DIRS|UseStaticFiles|http\.FileServer")
SOURCE = {".py", ".js", ".ts", ".mjs", ".cjs", ".java", ".kt", ".go", ".cs"}
STATIC_UI = {".js", ".css"}
NOT_UI = {"docs", "doc", "htmlcov", "coverage", "examples", "example", "test", "tests", "fixtures", "e2e", "reports"}


def _serves(ws: Path, comp: dict, ui: str) -> str:
    """The file:line of `comp` that serves the UI folder `ui` (sibling or parent folder), else ''."""
    folder = Path(ui).name
    for f in (ws / comp["path"]).rglob("*"):
        if f.suffix not in SOURCE or any(p in HIDDEN or p.startswith(".") for p in f.relative_to(ws).parts[:-1]):
            continue
        for n, line in enumerate(_read(f).splitlines()[:3000], 1):
            if SERVES.search(line) and (folder in line or "index.html" in line):
                return f"{f.relative_to(ws).as_posix()}:{n}"
    return ""


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def rule_plan(ws: Path, repo: str = "") -> list[dict]:
    """Deterministic first plan from the manifests (also the fallback without an LLM)."""
    comps, uis = [], []
    for dirpath, dirs, files in os.walk(ws):
        d = Path(dirpath)
        rel = d.relative_to(ws).as_posix() or "."
        dirs[:] = [x for x in dirs if x not in HIDDEN and not x.startswith(".")]
        f = set(files)
        name = slug(clean_app_name(repo or ws.name)) if rel == "." else d.name
        df = "Dockerfile" in f
        if "package.json" in f:
            pkg = json.loads(_read(d / "package.json") or "{}")
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            scripts = pkg.get("scripts", {})
            front = bool(deps.keys() & {"react", "vue", "@angular/core", "svelte", "vite", "next"})
            pm = "npm ci" if "package-lock.json" in f else "npm install"
            jest = "jest" in deps and "vitest" not in deps
            vver = deps.get("vitest", "").lstrip("^~") or "latest"
            test = ("npx jest --ci --coverage --coverageReporters=json-summary --coverageDirectory=.cip/coverage "
                    "--json --outputFile=.cip/jest.json" if jest else
                    f"npm install --no-save @vitest/coverage-v8@{vver} && npx vitest run --coverage.enabled "
                    "--coverage.reporter=json-summary --coverage.reportsDirectory=.cip/coverage --reporter=default "
                    "--reporter=junit --outputFile.junit=.cip/junit.xml") if ("vitest" in deps or jest) else ""
            comps.append(dict(name=name, path=rel, language="TypeScript" if "typescript" in deps else "JavaScript",
                              framework=next((k for k in ("next", "react", "vue", "@angular/core", "express", "@nestjs/core") if k in deps), "node"),
                              kind="web-frontend" if front else "api" if deps.keys() & {"express", "fastify", "@nestjs/core"} else "library",
                              build_commands=[pm] + (["npm run build"] if "build" in scripts else []), test_command=test,
                              test_reports=[".cip/junit.xml", ".cip/jest.json"], artifacts=["dist/**", "build/**"],
                              deployable=front or "start" in scripts, port=8080 if front else 3000, has_dockerfile=df))
        elif "pom.xml" in f or "build.gradle" in f or "build.gradle.kts" in f:
            mvn = "pom.xml" in f
            tool = ("mvnw" if "mvnw" in f else "mvn") if mvn else ("gradlew" if "gradlew" in f else "gradle")
            tool = (".\\" + tool + (".cmd" if mvn else ".bat")) if os.name == "nt" and tool.endswith("w") else ("./" + tool if tool.endswith("w") else tool)
            spring = "spring-boot" in _read(d / "pom.xml") + _read(d / "build.gradle")
            comps.append(dict(name=name, path=rel, language="Java", framework="Spring Boot" if spring else "Java",
                              kind="api" if spring else "library",
                              build_commands=[f"{tool} -B -ntp -DskipTests compile" if mvn else f"{tool} compileJava"],
                              test_command=f"{tool} -B -ntp test" if mvn else f"{tool} test",
                              test_reports=["target/surefire-reports/*.xml", "build/test-results/test/*.xml"],
                              package_command=f"{tool} -B -ntp -DskipTests package" if mvn else f"{tool} assemble",
                              artifacts=["target/*.jar", "target/*.war", "build/libs/*.jar"], deployable=spring, port=8080, has_dockerfile=df))
        elif f & {"requirements.txt", "pyproject.toml", "setup.py"}:
            reqs = (_read(d / "requirements.txt") + _read(d / "pyproject.toml")).lower()
            web = next((w for w in ("fastapi", "flask", "django", "streamlit") if w in reqs), "")
            install = f"{PY} -m pip install -q -r requirements.txt" if "requirements.txt" in f else f"{PY} -m pip install -q -e ."
            comps.append(dict(name=name, path=rel, language="Python", framework=web or "Python", kind="api" if web else "library",
                              build_commands=["python -m venv .cip-venv", install, f"{PY} -m pip install -q pytest pytest-cov",
                                              f"{PY} -m compileall -q -x \\.cip-venv ."],
                              test_command=f"{PY} -m pytest -q --junitxml=.cip/junit.xml --cov=. --cov-report=xml:.cip/coverage.xml",
                              test_reports=[".cip/junit.xml"], deployable=bool(web), port=8501 if web == "streamlit" else 8000,
                              has_dockerfile=df))
        elif "go.mod" in f:
            comps.append(dict(name=name, path=rel, language="Go", framework="Go", kind="api", build_commands=["go build ./..."],
                              test_command="go test -json -coverprofile=.cip/cover.out ./... > .cip/go-test.json",
                              test_reports=[".cip/go-test.json"], deployable="package main" in "".join(_read(x) for x in d.glob("*.go")),
                              port=8080, has_dockerfile=df))
        elif df:
            comps.append(dict(name=name, path=rel, language="unknown", framework="Dockerfile", kind="service",
                              build_commands=[], deployable=True, port=8080, has_dockerfile=True))
        elif "index.html" in f and (rel == "." or any(Path(x).suffix in STATIC_UI for x in files)) \
                and not NOT_UI & set(rel.lower().split("/")):
            uis.append(dict(name=name, path=rel, language="HTML", framework="static site", kind="web-frontend",
                            build_commands=[], deployable=True, port=8080, has_dockerfile=False,
                            reasoning=f"{rel}/index.html with JS/CSS and no build manifest"))
            continue                                  # keep walking: a backend may live below the UI folder
        else:
            continue
        dirs[:] = []                                  # sub-folders belong to this component
    inside = lambda p, parents: any(p != q and (q == "." or p.startswith(q + "/")) for q in parents)  # noqa: E731
    uis = [u for u in uis if not inside(u["path"], [x["path"] for x in uis]) and not inside(u["path"], [c["path"] for c in comps])]
    for ui in uis:                                    # a static UI served by a backend ships inside that backend
        host = next(((c, at) for c in comps if c["kind"] == "api" and (at := _serves(ws, c, ui["path"]))), None)
        if host:
            host[0].update(kind="web-app", serves_ui=ui["path"], reasoning=f"serves the UI in {ui['path']}/ ({host[1]})")
            if not ui["path"].startswith(host[0]["path"] + "/"):
                _widen(host[0], ui["path"])
        else:
            comps.append(ui)
    return comps


def _widen(comp: dict, ui: str) -> None:
    """The UI lives outside the backend folder: build the component from their common parent so the container holds
    both; the commands still run in the backend folder (app_dir)."""
    parent = os.path.commonpath([comp["path"], ui]).replace("\\", "/") if comp["path"] != "." else "."
    sub = os.path.relpath(comp["path"], parent or ".").replace("\\", "/")
    cd = lambda c: f"cd {sub} && {c}" if c else c  # noqa: E731
    comp.update(path=parent or ".", app_dir=sub, build_commands=[cd(c) for c in comp["build_commands"]],
                test_command=cd(comp.get("test_command", "")), package_command=cd(comp.get("package_command", "")),
                test_reports=[f"{sub}/{r}" for r in comp.get("test_reports", [])],
                artifacts=[f"{sub}/{a}" for a in comp.get("artifacts", [])])


def app_name(ws: Path, repo: str) -> str:
    """The <title> of the app's index.html when it is a real name, else the cleaned repository name."""
    for f in [ws / "index.html", *ws.glob("*/index.html"), *ws.glob("*/public/index.html"), *ws.glob("*/static/index.html")]:
        m = re.search(r"<title>\s*([^<]{3,60}?)\s*</title>", _read(f), re.I)
        if m and m.group(1).lower() not in ("document", "react app", "vite app", "vite + react", "vite + react + ts", "index"):
            return m.group(1)
    return clean_app_name(repo)


def ensure_coverage(comp: dict, draft: list[dict]) -> dict:
    """The LLM sometimes drops the coverage flags from the test command – put them back (vitest / jest / pytest),
    so the test gate can measure line coverage instead of reporting 0 %."""
    cmd = comp.get("test_command") or ""
    if not cmd or any(k in cmd for k in ("coverage", "--cov", "coverprofile")):
        return comp
    rule = next((d for d in draft if d["path"] == comp["path"]), {})
    if "vitest" in cmd:
        ver = re.search(r"@vitest/coverage-v8@([^\s]+)", rule.get("test_command") or "")
        cmd = (f"npm install --no-save @vitest/coverage-v8@{ver.group(1) if ver else 'latest'} && "
               + re.sub(r"vitest run", "vitest run --coverage.enabled --coverage.reporter=json-summary "
                                       "--coverage.reportsDirectory=.cip/coverage", cmd, count=1))
    elif "jest" in cmd:
        cmd += " --coverage --coverageReporters=json-summary --coverageDirectory=.cip/coverage"
    elif "pytest" in cmd and "pytest-cov" in " ".join(comp.get("build_commands") or []):
        cmd += " --cov=. --cov-report=xml:.cip/coverage.xml"
    else:
        return comp
    return {**comp, "test_command": cmd}


class PlannerAgent:
    def __init__(self) -> None:
        self.node_name = "planner_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        """Discover the components and plan the pipeline."""
        task_id, ws, t0 = state["task_id"], Path(state["workspace"]), time.time()
        await emit(task_id, self.node_name, StreamStatus.START, "Reading the repository to plan the pipeline")
        draft = rule_plan(ws, state.get("repo", ""))
        name = app_name(ws, state.get("repo", ""))
        await emit(task_id, self.node_name, StreamStatus.PROGRESS,
                   f"build files found: {', '.join(c['path'] + ' (' + c['language'] + ')' for c in draft) or 'none'}")
        llm = await LLMProvider().get_llm(state.get("provider"))
        plan, summary, how = draft, "", "rules (no LLM selected)"
        if llm:
            tools = WorkspaceTools(str(ws), task_id, self.node_name)
            notes = await tool_loop(
                llm, tools.tools[:2],
                "You are a senior build engineer. Explore the repository with list_files and read_file and work out, for "
                "every deployable or buildable component: language, framework, the exact shell commands to install "
                "dependencies and build it, the unit-test command that writes a machine-readable report (JUnit XML, Jest "
                "JSON or `go test -json`), where that report lands, the package command, whether it is a server / web site, "
                "its port and whether it has a Dockerfile. A draft from file detection is given – confirm or correct it. "
                "Classify only from evidence in the files (cite file:line in reasoning). A backend that serves a folder of "
                "HTML/JS/CSS (StaticFiles, FileResponse('index.html'), express.static, send_from_directory, Spring static/) is "
                "kind web-app with serves_ui = that folder; when that folder is outside the backend folder, plan ONE "
                "component whose path is their common parent so the container holds both. Never merge components otherwise. "
                "An app_name is the short human name of the application (README title, UI title or what it does).",
                f"Draft plan:\n{json.dumps(draft, indent=1)}\n\nRepository root listing:\n{await tools.list_files('.', 2)}",
                task_id, self.node_name, max_steps=10)
            result = await ask_structured(llm, RepoPlan, "Turn the notes into the final build plan. Keep commands runnable "
                                          f"on {'Windows (cmd.exe)' if os.name == 'nt' else 'Linux'}; use the draft where it is right.",
                                          f"Draft:\n{json.dumps(draft)}\n\nNotes:\n{notes}")
            if result and result.components:
                plan = [ensure_coverage(c.model_dump(), draft) for c in result.components if (ws / c.path).is_dir()]
                summary, how = result.summary, f"LLM ({state.get('provider')}) after exploring the repo"
                name = clean_app_name(result.app_name) if result.app_name.strip() else name
        for c in plan:
            await emit(task_id, self.node_name, StreamStatus.PROGRESS,
                       f"■ {c['name']}: {c['language']} {c['framework']} ({c['kind']}{', serves UI ' + c['serves_ui'] if c.get('serves_ui') else ''}) – build: {' && '.join(c['build_commands']) or '-'}"
                       f" · tests: {c['test_command'] or 'none'}")
        opts = state.get("options") or {}
        execution_plan = [{"name": "security_agent"}, {"name": "security_review"}]
        if plan:
            execution_plan.append({"name": "component_lanes"})
        if opts.get("deploy", True) and opts.get("containerize", True) and any(c["deployable"] for c in plan):
            execution_plan += [{"name": "deploy_agent"}, {"name": "functional_test_agent"}]
        execution_plan.append({"name": "report_agent"})
        message = f"{len(plan)} component(s) – planned by {how}"
        await emit(task_id, self.node_name, StreamStatus.END, message, data={"components": plan, "plan": execution_plan})
        return {"components": plan, "execution_plan": execution_plan, "step_index": 0, "app_name": name,
                "steps": {"plan": step_record("plan", "Plan the pipeline", "discovery", "passed" if plan else "warning",
                                              message, items=plan, item_type="components", started=t0,
                                              summary={"app name": name, "application": summary, "planned by": how,
                                                       "stages": " → ".join(s["name"] for s in execution_plan)})}}
