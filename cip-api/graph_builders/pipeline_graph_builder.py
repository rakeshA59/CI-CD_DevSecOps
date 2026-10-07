"""
Pipeline Graph Builder.

Top-level CI/CD workflow (Plan-Execute, dynamic routing on execution_plan[step_index] like sdlc-api):

    checkout_agent → planner_agent → security_agent → security_review (⏸ HITL) → component lanes (parallel)
                   → deploy_agent → functional_test_agent → report_agent → END

security_review pauses the run (LangGraph interrupt) until a human approves the security reports; the run's state
is kept by the checkpointer (thread_id = task_id) and resumed with Command(resume=...).

The planner decides which stages exist for this repository; a failed gate routes straight to the report
(unless "continue when a gate fails" is on).
"""

import asyncio
import logging

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agent_states.pipeline_state import PipelineState
from agents.checkout_agent import CheckoutAgent
from agents.deploy_agent import DeployAgent
from agents.functional_test_agent import FunctionalTestAgent
from agents.planner_agent import PlannerAgent
from agents.report_agent import ReportAgent
from agents.security_agent import SecurityAgent
from agents.security_review_agent import SecurityReviewAgent
from graph_builders.lane_graph_builder import get_lane_graph

_compiled_pipeline_graph = None
_lock = asyncio.Lock()
NODES = ["security_agent", "security_review", "deploy_agent", "functional_test_agent", "report_agent"]
CHECKPOINTER = MemorySaver()        # keeps a run paused at the security review (in memory, like the guided flow)


def next_node(state: PipelineState):
    """Route to the next planned step; fan out one lane per component; stop at the report after a failed gate."""
    if state.get("stopped_at"):
        return "report_agent" if state.get("execution_plan") else END
    plan, i = state.get("execution_plan", []), state.get("step_index", 0)
    if i >= len(plan):
        return END
    name = plan[i]["name"]
    if name == "component_lanes":
        return [Send("component_lane", {"task_id": state["task_id"], "provider": state.get("provider"),
                                        "options": state.get("options", {}), "run_dir": state["run_dir"],
                                        "workspace": state["workspace"], "component": c, "result": {}})
                for c in state["components"]]
    return name


async def component_lane(lane: dict, config: RunnableConfig) -> dict:
    """Run one component through the lane sub-graph and merge its result into the pipeline state."""
    graph = await get_lane_graph()
    out = await graph.ainvoke(lane, config)
    return {"lanes": {lane["component"]["name"]: out.get("result", {})}, "steps": out.get("steps", {})}


def lanes_done(state: PipelineState) -> dict:
    """After all lanes: collect their gates and stop on a failed one (unless continue-on-fail)."""
    gates = {}
    for name, r in (state.get("lanes") or {}).items():
        for key in ("test_gate", "container_gate"):
            if r.get(key):
                gates[f"{key.split('_')[0]}:{name}"] = r[key]
    failed = [k for k, g in gates.items() if not g["passed"]]
    stop = failed and not (state.get("options") or {}).get("continue_on_fail")
    return {"gates": gates, "step_index": state["step_index"] + 1, **({"stopped_at": f"{failed[0]} gate"} if stop else {})}


def build_pipeline_graph():
    workflow = StateGraph(PipelineState)
    workflow.add_node("checkout_agent", CheckoutAgent().run, metadata={"alias": "Source Controller"})
    workflow.add_node("planner_agent", PlannerAgent().run, metadata={"alias": "Release Planner"})
    workflow.add_node("security_agent", SecurityAgent().run, metadata={"alias": "Security Engineer"})
    workflow.add_node("security_review", SecurityReviewAgent().run, metadata={"alias": "Security Reviewer"})
    workflow.add_node("component_lane", component_lane, metadata={"alias": "Component Lane"})
    workflow.add_node("lanes_done", lanes_done)
    workflow.add_node("deploy_agent", DeployAgent().run, metadata={"alias": "Platform Engineer"})
    workflow.add_node("functional_test_agent", FunctionalTestAgent().run, metadata={"alias": "QA Engineer"})
    workflow.add_node("report_agent", ReportAgent().run, metadata={"alias": "Release Manager"})

    workflow.set_entry_point("checkout_agent")
    workflow.add_conditional_edges("checkout_agent", lambda s: "report_agent" if s.get("stopped_at") else "planner_agent",
                                   {"planner_agent": "planner_agent", "report_agent": "report_agent"})
    routes = {n: n for n in NODES} | {"component_lane": "component_lane", END: END}
    for node in ["planner_agent", "security_agent", "security_review", "lanes_done", "deploy_agent", "functional_test_agent"]:
        workflow.add_conditional_edges(node, next_node, routes)
    workflow.add_edge("component_lane", "lanes_done")
    workflow.add_edge("report_agent", END)
    return workflow.compile(checkpointer=CHECKPOINTER)


async def get_pipeline_graph():
    global _compiled_pipeline_graph
    async with _lock:
        if _compiled_pipeline_graph is None:
            logging.info("[PipelineGraphBuilder] compiling the pipeline graph")
            _compiled_pipeline_graph = build_pipeline_graph()
    return _compiled_pipeline_graph


def graph_outline() -> dict:
    """Nodes and edges for the UI's pipeline view."""
    g = build_pipeline_graph().get_graph()
    return {"nodes": [n for n in g.nodes if not n.startswith("__")],
            "edges": [{"source": e.source, "target": e.target} for e in g.edges]}
