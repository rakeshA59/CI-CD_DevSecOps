"""
Approval Gate (guided flow) – human in the loop before UAT.

The run PAUSES here (LangGraph interrupt) with a summary of everything so far (gates, findings, tests, released
images). The reviewer approves or rejects in the UI; the decision, the reviewer's name and comment are recorded in
the step and in the report. A rejection skips the UAT deploy – it does not fail the run.
"""

import time

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent_states.pipeline_state import PipelineState
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


class ApprovalGateAgent:
    def __init__(self, target: str = "uat") -> None:
        self.target = target
        self.node_name = "approval_gate"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        t0 = time.time()
        gates = {k: g["passed"] for k, g in (state.get("gates") or {}).items()}
        steps = state.get("steps") or {}
        summary = {
            "gates": gates,
            "failed_steps": [f"{s['name']}{' – ' + s['component'] if s.get('component') else ''}"
                             for s in steps.values() if s["status"] in ("failed", "error")],
            "findings": {sev: sum(f["severity"] == sev for f in state.get("findings", []) if f.get("category") != "code_quality")
                         for sev in ("CRITICAL", "HIGH", "MEDIUM")},
            "released": state.get("release") or {},
        }
        decision = interrupt({"type": "approval", "target": self.target, "summary": summary}) or {}
        verdict = "approve" if str(decision.get("decision", "")).lower().startswith("approv") else "reject"
        record = {"decision": verdict, "by": (decision.get("by") or "reviewer")[:80], "comment": (decision.get("comment") or "")[:500]}
        msg = f"{'approved' if verdict == 'approve' else 'rejected'} by {record['by']}" + (f": {record['comment']}" if record["comment"] else "")
        await emit(state["task_id"], self.node_name, StreamStatus.END if verdict == "approve" else StreamStatus.SKIPPED, msg)
        items = [{"name": f"gate {k}", "actual": "PASS" if v else "FAIL", "required": "PASS", "passed": v} for k, v in gates.items()]
        return {"approval": record, "step_index": state["step_index"] + 1,
                "steps": {"approval": step_record("approval", f"Approval before {self.target.upper()}", "approval",
                                                  "passed" if verdict == "approve" else "skipped", msg, items=items,
                                                  item_type="checks", explanation=record["comment"], started=t0,
                                                  summary={"decision": verdict, "reviewer": record["by"]})}}
