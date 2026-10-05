"""
Test Agent (one per component lane).

Runs the component's own unit tests and reads the report into numbered test cases (TC-UT-…) with coverage.
When the repository has no tests (or none ran) and an LLM is selected, the agent writes unit tests for the main
modules in the project's own test framework, runs them, repairs the TESTS (never the code) up to twice, and
reports them marked as AI-generated. The test gate is a fixed threshold check.
"""

import re
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import LaneState
from agent_tools.workspace_tools import WorkspaceTools
from agents.tool_loop import tool_loop
from llmapi.llm_provider import LLMProvider
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.quality_gates import test_gate
from utils.test_explain import explain_unit_tests, explain_with_llm
from utils.test_reports import coverage_percent, parse_results, summarize

GENERATED = [".cip/generated-junit.xml", ".cip/generated-jest.json", ".cip/generated-go-test.json"]


PY_PACKAGES = {"yaml": "pyyaml", "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "dotenv": "python-dotenv",
               "bs4": "beautifulsoup4", "jwt": "pyjwt", "dateutil": "python-dateutil"}


def env_fix(test_command: str, output: str) -> str:
    """Rule-based repair of a test environment from the error text (missing Python module / Node package)."""
    if " -m pytest" in test_command:
        mods = set(re.findall(r"No module named '([\w.]+)'", output)) | set(re.findall(r"pip install ([\w\-\[\]]+)", output))
        pkgs = sorted({PY_PACKAGES.get(m.split(".")[0], m.split(".")[0]) for m in mods})
        return f"{test_command.split(' -m pytest')[0]} -m pip install -q {' '.join(pkgs)}" if pkgs else ""
    pkgs = {m if m.startswith("@") else m.split("/")[0] for m in re.findall(r"Cannot find (?:module|package) '([^'./][^']*)'", output)}
    return f"npm install --no-save {' '.join(sorted(pkgs))}" if pkgs else ""


class TestAgent:
    def __init__(self) -> None:
        self.node_name = "test_agent"

    async def run(self, state: LaneState, config: RunnableConfig) -> LaneState:
        task_id, comp, t0 = state["task_id"], state["component"], time.time()
        node, result = f"test.{comp['name']}", dict(state.get("result", {}))
        folder = Path(state["workspace"]) / comp["path"]
        if result.get("build", {}).get("status") != "passed":
            why = f"BLOCKED – the build of {comp['name']} failed, so its tests cannot run"
            gate = test_gate({}, None, blocked=why)
            result.update(tests={"status": "blocked", "cases": []}, test_gate=gate)
            return {"result": result, "steps": {node: step_record(node, "Unit tests", "unit tests", "blocked", why, comp["name"])}}
        await emit(task_id, node, StreamStatus.START, f"Unit tests of {comp['name']}", parent="component_lanes")
        tools = WorkspaceTools(state["workspace"], task_id, node)
        tools.extra_path, tools.extra_env = result["build"].get("path", []), result["build"].get("env", {})
        cases, generated, notes = [], False, ""
        llm = await LLMProvider().get_llm(state.get("provider"))
        if comp.get("test_command"):
            res = await tools.run(comp["test_command"], comp["path"])
            cases = parse_results(folder, comp.get("test_reports") or [])
            tries, attempt = int((state.get("options") or {}).get("self_heal_attempts", 1)), 0
            while (not cases or all(c["status"] == "error" for c in cases)) and attempt < max(tries, 1):   # could not start
                attempt += 1
                fix = env_fix(comp["test_command"], res["output"] + " ".join(c.get("message", "") for c in cases))
                if fix:
                    await emit(task_id, node, StreamStatus.PROGRESS, f"test environment incomplete – {fix}")
                    await tools.run(fix, comp["path"])
                elif llm and attempt <= tries:
                    await emit(task_id, node, StreamStatus.PROGRESS, f"tests could not start – self-healing attempt {attempt}/{tries}: "
                                                                     "the agent is repairing the test setup")
                    notes += (f"\n--- self-healing attempt {attempt} ---\n" if tries > 1 else "") + await tool_loop(
                        llm, tools.tools,
                        "The unit tests of this component could not start. Find out why with the tools and fix the TEST "
                        "ENVIRONMENT only (missing test dependency, missing config / setup file the tests expect, wrong "
                        "command). Never change application code or the assertions. Finish with: ROOT CAUSE: … FIX: …",
                        f"Component {comp['name']} in {comp['path']}.\nCommand: {comp['test_command']}\nOutput:\n{res['output'][-6000:]}"
                        + (f"\n\nEarlier attempts (not enough yet):\n{notes[-2500:]}" if notes else ""),
                        task_id, node, max_steps=16)
                else:
                    break
                res = await tools.run(comp["test_command"], comp["path"])
                cases = parse_results(folder, comp.get("test_reports") or [])
        if llm and not [c for c in cases if c["status"] != "skipped"]:
            await emit(task_id, node, StreamStatus.PROGRESS, "no unit tests ran – the agent is writing tests for this code")
            notes = await tool_loop(
                llm, tools.tools,
                "You are a senior test engineer. The component has no working unit tests. Read its main source files, then "
                "write focused unit tests in the project's own language and test framework (add the framework as a dev "
                "dependency if needed) under a folder named cip_generated_tests (or the framework's test folder). Run them so "
                "a report is written to .cip/generated-junit.xml (JUnit XML), or .cip/generated-jest.json (Jest --json), "
                "or .cip/generated-go-test.json (go test -json), relative to the component folder. If a test fails because "
                "the TEST is wrong, fix the test (at most twice); if the APPLICATION is wrong, keep the test and say so. "
                "Never change application code. Finish with: COMMAND: <the test command> and a short list of what the tests cover.",
                f"Component {comp['name']} ({comp['language']} {comp['framework']}) in folder {comp['path']}.\n"
                f"Files:\n{await tools.list_files(comp['path'], 3)}", task_id, node, max_steps=16)
            cases = parse_results(folder, GENERATED) or cases
            generated = bool(cases)
            for c in cases:
                c["source"] = "AI-generated"
        # Every test case gets a plain explanation: what it is about, what it checks, how it ran, result and why.
        explain_unit_tests(cases, folder, "" if generated else comp.get("test_command") or "")
        if llm and (state.get("options") or {}).get("explain_tests"):
            try:
                await emit(task_id, node, StreamStatus.PROGRESS, f"explaining {len(cases)} test case(s) in plain words")
                await explain_with_llm(llm, cases)
            except Exception as exc:   # explanations are a nice-to-have; never fail the tests because of them
                notes += f"\n(test explanations by the LLM skipped: {exc})"
        cov = coverage_percent(folder)
        summ = summarize(cases)
        gate = test_gate(summ, cov)
        status = "passed" if summ["executed"] and not summ["failed"] else "failed" if summ["executed"] else "skipped"
        message = (f"{summ['passed']}/{summ['executed']} passed" + (f", coverage {cov}%" if cov is not None else "")
                   + (" (tests written by the agent)" if generated else "") if summ["executed"] else
                   "no unit tests found" + ("" if llm else " – select an LLM to let the agent write tests"))
        await emit(task_id, node, StreamStatus.END, message, parent="component_lanes")
        result.update(tests={"status": status, "summary": summ, "coverage": cov, "generated": generated}, test_gate=gate)
        return {"result": result, "steps": {
            node: step_record(node, "Unit tests", "unit tests", status, message, comp["name"],
                              summary={**summ, "coverage %": cov, **({"self-heal attempts": attempt} if comp.get("test_command") and attempt else {})},
                              items=cases, item_type="tests", commands=tools.commands, explanation=notes, started=t0),
            f"test_gate.{comp['name']}": step_record(f"test_gate.{comp['name']}", "Test gate", "unit tests",
                                                     "passed" if gate["passed"] else "failed",
                                                     "; ".join(f"{c['name']} = {c['actual']} (needs {c['required']})"
                                                               for c in gate["checks"] if not c["passed"]) or "all checks passed",
                                                     comp["name"], items=gate["checks"], item_type="checks")}}
