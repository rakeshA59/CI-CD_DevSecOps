"""
Pipeline Designer (guided flow) – deterministic, no LLM.

Turns what the code is (components from the planner) + the questionnaire answers into the pipeline of this run,
using the stage catalogue of config/devops_flow.yml: which stages run, which tools and MCP server each one uses,
and – for every stage that is left out – why. The result is the run's execution_plan (what the graph routes on)
and its `spec` (shown in the UI and the report).
"""

import re
import time

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from mcp_services.mcp_servers.scanner_mcp.scanners import pick_scanners
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.devops_flow import flow_config


def design(components: list[dict], answers: dict, source: str = "") -> tuple[list[dict], list[dict], dict]:
    """(execution_plan, spec, options) for these components and answers."""
    tests = answers.get("tests") or []
    container = answers.get("deploy_as") == "container" and any(c["deployable"] for c in components)
    langs = {c["language"] for c in components}
    scan_plan = pick_scanners(langs, bool(re.search(r"github\.com", source)),
                              {t: answers.get(f"{t}_tool") for t in ("sast", "sca", "secrets")})
    scanners = [p["tool"] for p in scan_plan]
    later = [f"{k} = {answers[k]}" for k in ("ci_platform", "cloud", "target") if answers.get(k) not in ("local", "none", "local_docker", None)]
    rules = {
        "scan": (True, ""),
        "security_review": (True, ""),
        "build_test_package": (bool(components), "no buildable component was found"),
        "release": (container and answers.get("registry") == "local",
                    "delivery is 'package only'" if not container else "release is switched off"),
        "deploy_dev": (container, "delivery is 'package only' – nothing to run"),
        "functional_tests": (container and "functional" in tests, "functional tests not selected" if container else "nothing is deployed"),
        "ui_tests": (container and "ui" in tests, "UI browser tests not selected" if container else "nothing is deployed"),
        "publish_tests": (bool(tests), "no tests selected"),
        "approval": (container and answers.get("uat") and answers.get("approval_before_uat"),
                     "no UAT deploy" if not (container and answers.get("uat")) else "approval not requested"),
        "deploy_uat": (container and bool(answers.get("uat")), "UAT not requested" if container else "nothing to deploy"),
        "report": (True, ""),
    }
    plan, spec = [], []
    for st in flow_config()["stages"]:
        on, reason = rules[st["id"]]
        tools = [f"{p['label']}: {p['tool_label']}" for p in scan_plan] if st["id"] == "scan" else st["tools"]
        spec.append({"id": st["id"], "title": st["title"], "node": st["node"], "why": st["why"], "tools": tools,
                     "mcp": st["mcp"], "included": bool(on), "reason": "" if on else reason})
        if on:
            plan.append({"name": st["node"]})
    ui = container and "ui" in tests
    options = {"run_tests": "unit" in tests, "containerize": container, "deploy": container, "continue_on_fail": True,
               # the UI tests need the dev containers after the functional tests – they remove them when done
               "keep_running": ui, "remove_after_ui": ui,
               "scanners": scanners, "scan_plan": scan_plan, "self_heal_attempts": int(answers.get("self_heal_attempts", 1)),
               "heal_cves": True, "heal_deploy": True, "explain_tests": True, "security_review": True,           # guided flow: the extended self-healing loops
               "recorded_for_later": later}
    return plan, spec, options


class PipelineDesignerAgent:
    def __init__(self) -> None:
        self.node_name = "pipeline_designer"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        t0 = time.time()
        plan, spec, options = design(state.get("components", []), state.get("answers") or {}, state.get("source", ""))
        used = [s for s in spec if s["included"]]
        msg = f"{len(used)} stages: " + " → ".join(s["title"] for s in used)
        if options["recorded_for_later"]:
            msg += f" · recorded for later (runs locally now): {', '.join(options['recorded_for_later'])}"
        await emit(state["task_id"], self.node_name, StreamStatus.END, msg,
                   data={"spec": spec, "plan": plan, "components": state.get("components", [])})
        items = [{"name": s["title"], "actual": ", ".join(s["tools"][:8]) if s["included"] else f"skipped – {s['reason']}",
                  "required": s["mcp"], "passed": s["included"]} for s in spec]
        return {"execution_plan": plan, "spec": spec, "options": {**(state.get("options") or {}), **options}, "step_index": 0,
                "steps": {"design": step_record("design", "Derive the pipeline", "discovery", "passed", msg, items=items,
                                                item_type="checks", started=t0,
                                                summary={"stages": len(used), "scanners": len(options["scanners"]),
                                                         "self-heal tries": options["self_heal_attempts"]})}}
