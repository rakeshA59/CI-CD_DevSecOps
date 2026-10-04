"""
Build Agent (one per component lane).

Runs the planned build commands. When a build fails the agent does not give up:
  1. a missing tool (mvn / java / node / go / gradle) is installed automatically and the build retried;
  2. with an LLM, it reads the error, investigates with its tools (read files, run commands, install toolchains),
     fixes what it can in the workspace copy, and the build is retried once.
Every command and the agent's diagnosis are kept as the step's evidence.
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

MISSING = [(r"\b(mvn|mvnw)\b.*(not recognized|not found)|JAVA_HOME", ["jdk", "maven"]),
           (r"\bjava\b.*(not recognized|not found)", ["jdk"]), (r"\bgradle\b.*(not recognized|not found)", ["jdk", "gradle"]),
           (r"\b(npm|node|npx)\b.*(not recognized|not found)", ["node"]), (r"\bgo\b.*(not recognized|not found)", ["go"])]


class BuildAgent:
    def __init__(self) -> None:
        self.node_name = "build_agent"

    async def _build(self, tools: WorkspaceTools, comp: dict) -> dict | None:
        """Run the build commands; the first failing result, or None when all passed."""
        for cmd in comp["build_commands"]:
            res = await tools.run(cmd, comp["path"])
            if res["code"] != 0:
                return res
        return None

    async def run(self, state: LaneState, config: RunnableConfig) -> LaneState:
        task_id, comp, t0 = state["task_id"], state["component"], time.time()
        node = f"build.{comp['name']}"
        await emit(task_id, node, StreamStatus.START, f"Building {comp['name']} ({comp['language']} {comp['framework']})",
                   parent="component_lanes")
        tools = WorkspaceTools(state["workspace"], task_id, node)
        (Path(state["workspace"]) / comp["path"] / ".cip").mkdir(parents=True, exist_ok=True)
        fail, diagnosis = await self._build(tools, comp), ""
        if fail:
            needed = next((t for rx, t in MISSING if re.search(rx, fail["output"], re.I)), None)
            if needed:
                for tool in needed:
                    await emit(task_id, node, StreamStatus.PROGRESS, f"{tool} is missing – installing it for this run")
                    diagnosis += await tools.install_toolchain(tool) + "\n"
                fail = await self._build(tools, comp)
        llm = await LLMProvider().get_llm(state.get("provider")) if fail else None
        if fail and llm:
            await emit(task_id, node, StreamStatus.PROGRESS, "build failed – the agent is investigating the error")
            diagnosis += await tool_loop(
                llm, tools.tools,
                "You are a build engineer fixing a failing CI build in a throw-away copy of the repository. Find the root "
                "cause with the tools. You may install missing toolchains, run commands (e.g. install a missing dependency) "
                "and edit build files when the fix is obvious. Do not touch application logic. Finish with: ROOT CAUSE: … "
                "FIX: … (what you changed, or what the team must change).",
                f"Component {comp['name']} in folder {comp['path']}.\nFailed command: {fail['cmd']}\nOutput (end):\n{fail['output'][-6000:]}",
                task_id, node, max_steps=12)
            fail = await self._build(tools, comp)
        status = "failed" if fail else "passed"
        message = (f"build failed: {fail['output'][-600:]}" if fail else
                   f"built with {len(comp['build_commands'])} command(s)" if comp["build_commands"] else "nothing to compile")
        await emit(task_id, node, StreamStatus.ERROR if fail else StreamStatus.END, message[:400], parent="component_lanes")
        result = {**state.get("result", {}), "build": {"status": status, "message": message, "diagnosis": diagnosis,
                                                       "path": tools.extra_path, "env": tools.extra_env}}
        return {"result": result, "steps": {f"build.{comp['name']}": step_record(
            f"build.{comp['name']}", "Build", "build", status, message, component=comp["name"], commands=tools.commands,
            explanation=diagnosis.strip(), started=t0)}}
