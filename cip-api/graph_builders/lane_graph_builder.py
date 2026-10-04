"""
Component Lane Graph Builder.

The sub-graph every component runs through (one lane per component, lanes run in parallel via Send):

    build_agent → test_agent → container_agent (package + image + image scan) → END
"""

import asyncio
import logging

from langgraph.graph import END, StateGraph

from agent_states.pipeline_state import LaneState
from agents.build_agent import BuildAgent
from agents.container_agent import ContainerAgent
from agents.test_agent import TestAgent

_compiled_lane_graph = None
_lock = asyncio.Lock()


def build_lane_graph():
    workflow = StateGraph(LaneState)
    workflow.add_node("build_agent", BuildAgent().run, metadata={"alias": "Build Engineer"})
    workflow.add_node("test_agent", TestAgent().run, metadata={"alias": "Test Engineer"})
    workflow.add_node("container_agent", ContainerAgent().run, metadata={"alias": "Release Engineer"})
    workflow.set_entry_point("build_agent")
    workflow.add_conditional_edges("build_agent", lambda s: "test_agent" if (s.get("options") or {}).get("run_tests", True)
                                   else "container_agent", {"test_agent": "test_agent", "container_agent": "container_agent"})
    workflow.add_edge("test_agent", "container_agent")
    workflow.add_edge("container_agent", END)
    return workflow.compile()


async def get_lane_graph():
    """Compiled once and cached (singleton, like the sdlc-api graph builders)."""
    global _compiled_lane_graph
    async with _lock:
        if _compiled_lane_graph is None:
            logging.info("[LaneGraphBuilder] compiling the component lane graph")
            _compiled_lane_graph = build_lane_graph()
    return _compiled_lane_graph
