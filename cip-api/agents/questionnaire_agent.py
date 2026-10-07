"""
Questionnaire Agent (guided flow).

After the planner has read the code, this node works out what the code already tells (languages, Dockerfiles,
existing CI files, Kubernetes / Terraform, tests) and pre-answers the questionnaire of config/devops_flow.yml.
The run then PAUSES (LangGraph interrupt) until the user confirms or changes the answers in the UI; the answers are
validated against the questionnaire and stored in the state for the pipeline designer.
"""

import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent_states.pipeline_state import PipelineState
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from mcp_services.mcp_servers.scanner_mcp.scanners import pick_scanners
from utils.devops_flow import flow_config

CI_FILES = {".gitlab-ci.yml": "gitlab", "Jenkinsfile": "jenkins", ".github/workflows": "github_actions",
            "azure-pipelines.yml": "azure_devops", "buildspec.yml": "aws_codepipeline"}
SKIP = {"node_modules", ".git", ".venv", "venv", ".cip", ".cip-venv", "dist", "build", "target"}


def _find(ws: Path, pattern: str, limit: int = 10) -> list[str]:
    out = []
    for p in ws.rglob(pattern):
        if not SKIP.intersection(p.relative_to(ws).parts):
            out.append(p.relative_to(ws).as_posix())
            if len(out) >= limit:
                break
    return out


def discover(ws: Path, components: list[dict]) -> dict:
    """What the code itself says about how it is built, tested and delivered."""
    ci = {name: plat for name, plat in CI_FILES.items() if (ws / name).exists()}
    k8s = [f for f in _find(ws, "*.y*ml", 200) if any(k in f.lower() for k in ("k8s", "kubernetes", "helm", "deployment"))][:10]
    return {
        "components": [{"name": c["name"], "language": c["language"], "framework": c["framework"], "kind": c["kind"],
                        "deployable": c["deployable"], "has_tests": bool(c.get("test_command"))} for c in components],
        "languages": sorted({c["language"] for c in components}),
        "dockerfiles": _find(ws, "Dockerfile"),
        "ci_files": list(ci), "ci_platform": next(iter(ci.values()), None),
        "kubernetes_files": k8s, "terraform_files": _find(ws, "*.tf"),
        "deployable": any(c["deployable"] for c in components),
        "has_tests": any(c.get("test_command") for c in components),
    }


def questions(detected: dict) -> list[dict]:
    """The questionnaire with values pre-filled from discovery (and a note saying where each value came from)."""
    out = []
    picks = {p["type"]: p for p in pick_scanners(set(detected["languages"]), bool(detected.get("github")))}
    for q in flow_config()["questionnaire"]:
        q = {**q, "options": [dict(o) for o in q.get("options", [])]}
        value, note = q.get("default"), ""
        if q["type"] == "single":
            value = next(o["value"] for o in q["options"] if o.get("runs", True))
        if q.get("prefill") == "ci_files" and detected["ci_platform"]:
            note = f"found {', '.join(detected['ci_files'])} → {detected['ci_platform']} (recorded; runs locally in this version)"
        elif q.get("prefill") == "deployable":
            value = "container" if detected["deployable"] else "package"
            note = (f"{len(detected['dockerfiles'])} Dockerfile(s) in the repo" if detected["dockerfiles"] else
                    "server / web components found – CIP writes a Dockerfile" if detected["deployable"] else "no server component found")
        elif q.get("prefill") == "tests":
            web = any(c["kind"] == "web-frontend" for c in detected["components"])
            value = ["unit"] + (["functional"] if detected["deployable"] else []) + (["ui"] if web else [])
            note = ("unit tests found in the repo" if detected["has_tests"] else "no unit tests found – the test agent can write them (LLM)") + (
                " · web front-end found → browser tests" if web else "")
        elif q.get("prefill") == "scan_tool" and picks.get(q["id"].removesuffix("_tool")):
            p = picks[q["id"].removesuffix("_tool")]
            note = f"agent's pick: {p['tool_label']} – {p['reason']}"
        out.append({**q, "value": value, "note": note})
    return out


def validate(answers: dict, qs: list[dict]) -> dict:
    """Keep only known questions / options; fall back to the pre-filled value."""
    clean = {}
    for q in qs:
        v = (answers or {}).get(q["id"], q["value"])
        allowed = {o["value"] for o in q.get("options", [])}
        if q["type"] == "single":
            v = v if v in allowed else q["value"]
        elif q["type"] == "multi":
            v = [x for x in (v if isinstance(v, list) else [v]) if x in allowed]
        elif q["type"] == "bool":
            v = bool(v)
        elif q["type"] == "number":
            try:
                v = max(q.get("min", 0), min(q.get("max", 9), int(v)))
            except (TypeError, ValueError):
                v = q["value"]
        clean[q["id"]] = v
    return clean


class QuestionnaireAgent:
    def __init__(self) -> None:
        self.node_name = "questionnaire_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        t0 = time.time()
        detected = discover(Path(state["workspace"]), state.get("components", []))
        qs = questions(detected)
        # Pauses the run here; the UI shows the questions and resumes the graph with the answers.
        answers = validate(interrupt({"type": "questionnaire", "detected": detected, "questions": qs}), qs)
        labels = {q["id"]: q for q in qs}
        lines = []
        for k, v in answers.items():
            opts = {o["value"]: o for o in labels[k].get("options", [])}
            shown = ", ".join(opts[x]["label"] for x in v) if isinstance(v, list) else opts.get(v, {}).get("label", v)
            later = [x for x in (v if isinstance(v, list) else [v]) if opts.get(x, {}).get("runs") is False]
            lines.append({"name": labels[k]["label"], "actual": shown, "required": "recorded for later" if later else "used now",
                          "passed": True})
        await emit(state["task_id"], self.node_name, StreamStatus.END, "Questionnaire answered", data={"answers": answers})
        return {"detected": detected, "answers": answers,
                "steps": {"questionnaire": step_record("questionnaire", "Questionnaire", "discovery", "passed",
                                                       f"{len(answers)} answers – {', '.join(detected['languages']) or 'no'} code detected",
                                                       items=lines, item_type="checks", started=t0,
                                                       summary={"ci files found": ", ".join(detected["ci_files"]) or "none",
                                                                "dockerfiles": len(detected["dockerfiles"]),
                                                                "kubernetes files": len(detected["kubernetes_files"]),
                                                                "terraform files": len(detected["terraform_files"])})}}
