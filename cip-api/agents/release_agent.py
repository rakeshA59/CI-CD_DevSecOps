"""
Release Agent (guided flow) – publishes every built image to the image registry through the Docker MCP server.

Today the registry is a local one (registry:2 on localhost:5000, started when it is not running). The pushed name
replaces the local tag, so the dev and UAT deployments run exactly the released artifact.
"""

import re
import time

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from mcp_services.mcp_clients.mcp_tool_client import docker_client
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


class ReleaseAgent:
    def __init__(self) -> None:
        self.node_name = "release_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        lanes = state.get("lanes") or {}
        images = {n: r["image"] for n, r in lanes.items() if (r.get("image") or {}).get("built")}
        nxt = {"step_index": state["step_index"] + 1}
        if not images:
            msg = "nothing to release – no image was built (see the containerise steps)"
            await emit(task_id, self.node_name, StreamStatus.SKIPPED, msg)
            return {**nxt, "steps": {"release": step_record("release", "Release to registry", "release", "blocked", msg)}}
        await emit(task_id, self.node_name, StreamStatus.START, f"Releasing {len(images)} image(s) to the registry")
        docker = docker_client()
        reg = await docker.call_tool("docker_registry", {"port": 5000})
        if not reg["running"]:
            msg = f"local registry could not be started: {reg['message']}"
            await emit(task_id, self.node_name, StreamStatus.ERROR, msg)
            return {**nxt, "steps": {"release": step_record("release", "Release to registry", "release", "failed", msg)}}
        repo = re.sub(r"[^a-z0-9._-]", "-", (state.get("repo") or "app").lower())
        released, pushed, lanes_update = {}, [], {}
        for name, image in images.items():
            await emit(task_id, self.node_name, StreamStatus.COMMAND, f"$ docker push {reg['registry']}/{repo}/{name}")
            res = await docker.call_tool("docker_push", {"image": image["image"], "registry": reg["registry"],
                                                         "repository": f"{repo}/{name.lower()}"})
            pushed.append({"component": name, "status": "passed" if res["pushed"] else "failed", "url": res["image"],
                           "message": res["digest"] or res["log"][-300:], "image": image["image"]})
            if res["pushed"]:
                released[name] = res["image"]
                lanes_update[name] = {**lanes[name], "image": {**image, "image": res["image"], "local_tag": image["image"]}}
        ok = len(released) == len(images)
        msg = ", ".join(f"{p['component']} → {p['url']}" for p in pushed if p["status"] == "passed") or "push failed"
        await emit(task_id, self.node_name, StreamStatus.END if ok else StreamStatus.ERROR, msg)
        return {**nxt, "release": released, "lanes": lanes_update,
                "steps": {"release": step_record("release", "Release to registry", "release", "passed" if ok else "failed", msg,
                                                 items=pushed, item_type="services", started=t0,
                                                 summary={"registry": reg["registry"], "via": docker.last_transport})}}
