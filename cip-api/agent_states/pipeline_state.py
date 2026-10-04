"""
Pipeline State.

Canonical state passed through every node of the CI/CD LangGraph workflow (like AutomationState in sdlc-api).
Fields written by parallel component lanes use reducers so the lanes never overwrite each other.
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def merge_dicts(left: Optional[dict], right: Optional[dict]) -> dict:
    """Reducer: shallow-merge dicts written by different nodes / lanes."""
    return {**(left or {}), **(right or {})}


class PipelineState(TypedDict, total=False):
    # Task context
    task_id: str
    source: str                      # GitHub URL, org/repo or local folder
    source_type: str                 # "git repo" | "local folder"
    branch: Optional[str]
    provider: str                    # LLM provider chosen in the UI
    options: Dict[str, Any]          # run_tests / containerize / deploy / functional / continue_on_fail
    run_dir: str
    workspace: str
    source_info: Dict[str, Any]

    # Plan (written by the planner agent) – plan-execute routing like the sdlc-api graph builders
    components: List[Dict[str, Any]]
    execution_plan: List[Dict[str, str]]
    step_index: int

    # Results
    steps: Annotated[Dict[str, Dict[str, Any]], merge_dicts]     # step id -> step record (UI + report)
    lanes: Annotated[Dict[str, Dict[str, Any]], merge_dicts]     # component -> build/test/package/image results
    findings: Annotated[List[Dict[str, Any]], operator.add]      # security findings of all scanners
    gates: Annotated[Dict[str, Dict[str, Any]], merge_dicts]
    deploy: Dict[str, Any]
    functional: Dict[str, Any]
    stopped_at: Optional[str]
    overall: Optional[str]
    report: Dict[str, Any]
    errors: Annotated[List[str], operator.add]


class LaneState(TypedDict, total=False):
    """State of one component lane (sent to the lane sub-graph with LangGraph Send)."""

    task_id: str
    provider: str
    options: Dict[str, Any]
    run_dir: str
    workspace: str
    component: Dict[str, Any]
    result: Dict[str, Any]
    steps: Annotated[Dict[str, Dict[str, Any]], merge_dicts]
