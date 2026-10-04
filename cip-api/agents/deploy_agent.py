"""
Deploy Agent – runs every built image on one private Docker network (the dev environment) through the Docker
MCP server and waits until each service answers HTTP.
"""

import time

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from mcp_services.mcp_clients.mcp_tool_client import docker_client
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


class DeployAgent:
    def __init__(self) -> None:
        self.node_name = "deploy_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        images = {n: r["image"] for n, r in (state.get("lanes") or {}).items() if (r.get("image") or {}).get("built")}
        if not images:
            reasons = "; ".join(f"{n}: {(r.get('image') or {}).get('message') or r.get('build', {}).get('message', 'not built')}"[:200]
                                for n, r in (state.get("lanes") or {}).items())
            msg = f"nothing to deploy – no image was built ({reasons})"
            await emit(task_id, self.node_name, StreamStatus.SKIPPED, msg)
            return {"deploy": {"services": []}, "step_index": state["step_index"] + 1,
                    "steps": {"deploy": step_record("deploy", "Deploy to dev", "deploy", "blocked", msg)}}
        await emit(task_id, self.node_name, StreamStatus.START, f"Deploying {len(images)} service(s) to the dev environment")
        network, docker, services = f"cip-{task_id[-12:].lower()}", docker_client(), []
        for name, image in images.items():
            await emit(task_id, self.node_name, StreamStatus.COMMAND, f"$ docker run -d --network {network} -p 127.0.0.1::{image['port']} {image['image']}")
            res = await docker.call_tool("docker_run", {"image": image["image"], "name": f"{network}-{name}", "network": network,
                                                        "port": image["port"], "alias": name})
            services.append({"component": name, "image": image["image"], **res})
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: {res.get('url') or '-'} → {res['status']} ({res.get('message')})")
        ok = all(s["status"] == "passed" for s in services)
        msg = ", ".join(f"{s['component']} {s.get('url', '')} {s['status']}" for s in services)
        await emit(task_id, self.node_name, StreamStatus.END if ok else StreamStatus.ERROR, msg)
        return {"deploy": {"network": network, "services": services}, "step_index": state["step_index"] + 1,
                "steps": {"deploy": step_record("deploy", "Deploy to dev", "deploy", "passed" if ok else "failed", msg,
                                                items=services, item_type="services", started=t0,
                                                summary={"network": network, "via": docker.last_transport})}}
