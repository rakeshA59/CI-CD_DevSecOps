"""
Deploy Agent – runs every built image on one private Docker network through the Docker MCP server and waits until
each service answers HTTP. One class, two environments:

    DeployAgent()          dev  – state["deploy"], removed after the functional tests (unless keep_running)
    DeployAgent("uat")     UAT  – state["uat"], own network and ports, left running; only after an approval when one
                           was requested (guided flow)
"""

import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from agent_tools.workspace_tools import WorkspaceTools
from agents.container_agent import exposed_port
from agents.tool_loop import tool_loop
from llmapi.llm_provider import LLMProvider
from mcp_services.mcp_clients.mcp_tool_client import docker_client
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


class DeployAgent:
    def __init__(self, env: str = "dev") -> None:
        self.env = env
        self.node_name = "deploy_agent" if env == "dev" else f"{env}_deploy_agent"
        self.step_id, self.key, self.title = ("deploy", "deploy", "Deploy to dev") if env == "dev" else \
            (f"deploy_{env}", env, f"Deploy to {env.upper()}")

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        if self.env != "dev" and (state.get("approval") or {}).get("decision") == "reject":
            msg = f"not deployed – the {self.env.upper()} deploy was rejected by {(state['approval'].get('by') or 'the reviewer')}"
            await emit(task_id, self.node_name, StreamStatus.SKIPPED, msg)
            return {self.key: {"services": []}, "step_index": state["step_index"] + 1,
                    "steps": {self.step_id: step_record(self.step_id, self.title, "deploy", "skipped", msg)}}
        images = {n: r["image"] for n, r in (state.get("lanes") or {}).items() if (r.get("image") or {}).get("built")}
        if not images:
            reasons = "; ".join(f"{n}: {(r.get('image') or {}).get('message') or r.get('build', {}).get('message', 'not built')}"[:200]
                                for n, r in (state.get("lanes") or {}).items())
            msg = f"nothing to deploy – no image was built ({reasons})"
            await emit(task_id, self.node_name, StreamStatus.SKIPPED, msg)
            return {self.key: {"services": []}, "step_index": state["step_index"] + 1,
                    "steps": {self.step_id: step_record(self.step_id, self.title, "deploy", "blocked", msg)}}
        await emit(task_id, self.node_name, StreamStatus.START, f"Deploying {len(images)} service(s) to the {self.env} environment")
        prefix = "cip" if self.env == "dev" else f"cip-{self.env}"
        network, docker, services = f"{prefix}-{task_id[-12:].lower().strip('-')}", docker_client(), []
        for name, image in images.items():
            await emit(task_id, self.node_name, StreamStatus.COMMAND, f"$ docker run -d --network {network} -p 127.0.0.1::{image['port']} {image['image']}")
            res = await docker.call_tool("docker_run", {"image": image["image"], "name": f"{network}-{name}", "network": network,
                                                        "port": image["port"], "alias": name})
            services.append({"component": name, "image": image["image"], **res})
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{name}: {res.get('url') or '-'} → {res['status']} ({res.get('message')})")
        healed, notes, lanes = await self._heal(state, services, images, network, docker)
        ok = all(s["status"] == "passed" for s in services)
        msg = ", ".join(f"{s['component']} {s.get('url', '')} {s['status']}" for s in services)
        await emit(task_id, self.node_name, StreamStatus.END if ok else StreamStatus.ERROR, msg)
        return {self.key: {"network": network, "services": services}, "step_index": state["step_index"] + 1,
                **({"lanes": lanes} if lanes else {}),
                "steps": {self.step_id: step_record(self.step_id, self.title, "deploy", "passed" if ok else "failed", msg,
                                                    items=services, item_type="services", started=t0, explanation=notes.strip(),
                                                    summary={"network": network, "environment": self.env,
                                                             "via": docker.last_transport,
                                                             **({"self-heal attempts": healed} if healed else {})})}}

    async def _heal(self, state: PipelineState, services: list, images: dict, network: str, docker) -> tuple[int, str, dict]:
        """Guided flow: a service that does not come up is investigated from its container log, its Dockerfile / start
        command / port are fixed by the agent, the image is rebuilt and the service redeployed – up to N times."""
        opts = state.get("options") or {}
        if not opts.get("heal_deploy") or all(s["status"] == "passed" for s in services):
            return 0, "", {}
        llm = await LLMProvider().get_llm(state.get("provider"))
        if not llm:
            return 0, "", {}
        tries, total, notes, lanes = int(opts.get("self_heal_attempts", 1)), 0, "", {}
        comps = {c["name"]: c for c in state.get("components", [])}
        for i, svc in enumerate(services):
            name, attempt = svc["component"], 0
            folder = Path(state["workspace"]) / comps.get(name, {}).get("path", ".")
            image = dict(images[name])
            tools = WorkspaceTools(state["workspace"], state["task_id"], self.node_name)
            while services[i]["status"] != "passed" and attempt < tries:
                attempt += 1
                await emit(state["task_id"], self.node_name, StreamStatus.PROGRESS,
                           f"{name} did not come up – self-healing attempt {attempt}/{tries}: the agent is reading the container log")
                notes += f"\n--- {name}: self-healing attempt {attempt} (deploy) ---\n" + await tool_loop(
                    llm, tools.tools,
                    "You are a platform engineer. A container of this component was started but did not answer HTTP on its "
                    "port (or exited). From the container log, the Dockerfile and the app's config find the root cause – "
                    "wrong EXPOSE / listen port, wrong start command, server bound to 127.0.0.1 instead of 0.0.0.0, missing "
                    "environment variable, missing file in the image, non-root permission problem. Fix the Dockerfile (or a "
                    "deployment config file) so the server listens on 0.0.0.0 on the EXPOSEd port. Do not change application "
                    "logic. Finish with: ROOT CAUSE: … FIX: …",
                    f"Component {name} in folder {comps.get(name, {}).get('path', '.')}. Expected port: {image['port']}.\n"
                    f"Deploy result: {services[i].get('message')} (HTTP status {services[i].get('http_status')})\n"
                    f"Container log (end):\n{services[i].get('logs_tail', '')[-5000:]}\n\nDockerfile:\n"
                    f"{(folder / 'Dockerfile').read_text(errors='replace') if (folder / 'Dockerfile').is_file() else '(none)'}",
                    state["task_id"], self.node_name, max_steps=14)
                built = await docker.call_tool("docker_build", {"context": str(folder), "tag": image["image"]})
                if not built["built"]:
                    notes += "\n(the fixed Dockerfile did not build: " + built.get("log", "")[-300:] + ")"
                    continue
                image["port"] = exposed_port(folder, image["port"])
                await docker.call_tool("docker_remove", {"names": [f"{network}-{name}"]})
                res = await docker.call_tool("docker_run", {"image": image["image"], "name": f"{network}-{name}", "network": network,
                                                            "port": image["port"], "alias": name})
                services[i] = {"component": name, "image": image["image"], **res}
                notes += f"\nRESULT: redeployed → {res['status']} ({res.get('message')}) {res.get('url', '')}"
                await emit(state["task_id"], self.node_name, StreamStatus.PROGRESS, f"{name}: redeployed → {res['status']} ({res.get('message')})")
            total += attempt
            if attempt:
                lane = (state.get("lanes") or {}).get(name, {})
                lanes[name] = {**lane, "image": {**lane.get("image", {}), "port": image["port"],
                                                 "dockerfile": (folder / "Dockerfile").read_text(errors="replace")}}
        return total, notes, lanes
