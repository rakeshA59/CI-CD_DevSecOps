"""
Guided DevOps Graph Builder (mode = "guided") – the Architect's flow, run locally.

    checkout_agent → planner_agent → questionnaire_agent (⏸ answers) → pipeline_designer
        → [derived stages, routed on execution_plan like the quick graph]
          security_agent → component lanes (build · test · package · image) → lanes_done
          → release_agent → deploy_agent (dev) → functional_test_agent → ui_test_agent (Selenium) → publish_tests_agent
          → approval_gate (⏸ approve / reject) → uat_deploy_agent → report_agent → END

The two ⏸ nodes call LangGraph `interrupt()`; the run's state is kept by the checkpointer (thread_id = task_id)
and resumed with `Command(resume=...)` from the API. The quick graph (pipeline_graph_builder) is unchanged.
"""

import asyncio
import logging

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent_states.pipeline_state import PipelineState
from agents.approval_gate_agent import ApprovalGateAgent
from agents.checkout_agent import CheckoutAgent
from agents.deploy_agent import DeployAgent
from agents.functional_test_agent import FunctionalTestAgent
from agents.pipeline_designer_agent import PipelineDesignerAgent
from agents.planner_agent import PlannerAgent
from agents.publish_tests_agent import PublishTestsAgent
from agents.questionnaire_agent import QuestionnaireAgent
from agents.release_agent import ReleaseAgent
from agents.report_agent import ReportAgent
from agents.security_agent import SecurityAgent
from agents.ui_test_agent import UITestAgent
from graph_builders.lane_graph_builder import get_lane_graph
from graph_builders.pipeline_graph_builder import lanes_done, next_node

_compiled_guided_graph = None
_lock = asyncio.Lock()
# In-memory checkpointer: paused runs survive while the API runs (a MongoDB checkpointer is the production step).
CHECKPOINTER = MemorySaver()
STAGE_NODES = ["security_agent", "release_agent", "deploy_agent", "functional_test_agent", "ui_test_agent", "publish_tests_agent",
               "approval_gate", "uat_deploy_agent", "report_agent"]


async def component_lane(lane: dict, config: RunnableConfig) -> dict:
    """One component through the lane sub-graph (own config: the lane graph has no checkpointer)."""
    graph = await get_lane_graph()
    out = await graph.ainvoke(lane, {"recursion_limit": 50})
    return {"lanes": {lane["component"]["name"]: out.get("result", {})}, "steps": out.get("steps", {})}


def build_guided_graph():
    workflow = StateGraph(PipelineState)
    workflow.add_node("checkout_agent", CheckoutAgent().run, metadata={"alias": "Source Controller"})
    workflow.add_node("planner_agent", PlannerAgent().run, metadata={"alias": "Tech-stack Analyst"})
    workflow.add_node("questionnaire_agent", QuestionnaireAgent().run, metadata={"alias": "DevOps Consultant"})
    workflow.add_node("pipeline_designer", PipelineDesignerAgent().run, metadata={"alias": "Pipeline Architect"})
    workflow.add_node("security_agent", SecurityAgent().run, metadata={"alias": "Security Engineer"})
    workflow.add_node("component_lane", component_lane, metadata={"alias": "Component Lane"})
    workflow.add_node("lanes_done", lanes_done)
    workflow.add_node("release_agent", ReleaseAgent().run, metadata={"alias": "Release Engineer"})
    workflow.add_node("deploy_agent", DeployAgent().run, metadata={"alias": "Platform Engineer"})
    workflow.add_node("functional_test_agent", FunctionalTestAgent().run, metadata={"alias": "QA Engineer"})
    workflow.add_node("ui_test_agent", UITestAgent().run, metadata={"alias": "UI Test Engineer"})
    workflow.add_node("publish_tests_agent", PublishTestsAgent().run, metadata={"alias": "QA Lead"})
    workflow.add_node("approval_gate", ApprovalGateAgent("uat").run, metadata={"alias": "Reviewer"})
    workflow.add_node("uat_deploy_agent", DeployAgent("uat").run, metadata={"alias": "Platform Engineer"})
    workflow.add_node("report_agent", ReportAgent().run, metadata={"alias": "Release Manager"})

    workflow.set_entry_point("checkout_agent")
    workflow.add_conditional_edges("checkout_agent", lambda s: "report_agent" if s.get("stopped_at") else "planner_agent",
                                   {"planner_agent": "planner_agent", "report_agent": "report_agent"})
    workflow.add_edge("planner_agent", "questionnaire_agent")
    workflow.add_edge("questionnaire_agent", "pipeline_designer")
    routes = {n: n for n in STAGE_NODES} | {"component_lane": "component_lane", END: END}
    for node in ["pipeline_designer", "lanes_done", *STAGE_NODES[:-1]]:
        workflow.add_conditional_edges(node, next_node, routes)
    workflow.add_edge("component_lane", "lanes_done")
    workflow.add_edge("report_agent", END)
    return workflow.compile(checkpointer=CHECKPOINTER)


async def get_guided_graph():
    global _compiled_guided_graph
    async with _lock:
        if _compiled_guided_graph is None:
            logging.info("[GuidedGraphBuilder] compiling the guided DevOps graph")
            _compiled_guided_graph = build_guided_graph()
    return _compiled_guided_graph
