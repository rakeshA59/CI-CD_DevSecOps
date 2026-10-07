"""
Security Review Agent – "HITL – review reports", the last step of the Security stage (both flows).

The security gate is still computed by the security agent (fixed thresholds); this node shows that result with the
findings to a human and PAUSES the run (LangGraph interrupt) until the reviewer approves or rejects:
    approve → the pipeline continues exactly as before (a failed gate stays FAIL in the report)
    reject  → the pipeline stops and goes to the report ("rejected at the security review")
It is its own node (not part of the security agent) so that resuming does not run the scanners again.
Switched off with the run option `security_review: false` – then the step only records the gate.
"""

import time

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent_states.pipeline_state import PipelineState
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record

NAME = "HITL – review reports"


def review_summary(state: PipelineState) -> dict:
    """What the reviewer sees: the gate checks, findings per severity and per scanner."""
    gate = (state.get("gates") or {}).get("security") or {"passed": True, "checks": []}
    findings = [f for f in state.get("findings", []) if f.get("category") != "code_quality"]
    per_scanner: dict[str, dict] = {}
    for f in findings:
        per_scanner.setdefault(f["scanner"], {s: 0 for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")})
        if f["severity"] in per_scanner[f["scanner"]]:
            per_scanner[f["scanner"]][f["severity"]] += 1
    return {"gate_passed": gate["passed"], "checks": gate["checks"],
            "findings": {s: sum(f["severity"] == s for f in findings) for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
            "per_scanner": per_scanner,
            "top": [{k: f.get(k) for k in ("severity", "scanner", "title", "file", "line")}
                    for f in findings if f["severity"] in ("CRITICAL", "HIGH")][:10]}


class SecurityReviewAgent:
    def __init__(self) -> None:
        self.node_name = "security_review"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        t0, task_id = time.time(), state["task_id"]
        summary = review_summary(state)
        gate_txt = "gate PASS" if summary["gate_passed"] else "gate FAIL – " + "; ".join(
            f"{c['name']} = {c['actual']} (needs {c['required']})" for c in summary["checks"] if not c["passed"])
        done = {"step_index": state["step_index"] + 1}
        if not (state.get("options") or {}).get("security_review", True):
            return {**done, "steps": {"security_gate": step_record(
                "security_gate", NAME, "security", "passed" if summary["gate_passed"] else "failed",
                f"{gate_txt} · human review switched off", items=summary["checks"], item_type="checks", started=t0)}}

        await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"waiting for a human to review the security reports ({gate_txt})")
        decision = interrupt({"type": "security_review", "summary": summary}) or {}
        approve = str(decision.get("decision", "")).lower().startswith("approv")
        by, comment = (decision.get("by") or "reviewer")[:80], (decision.get("comment") or "")[:500]
        msg = f"{gate_txt} · {'approved' if approve else 'rejected'} by {by}" + (f": {comment}" if comment else "")
        await emit(task_id, self.node_name, StreamStatus.END if approve else StreamStatus.ERROR, msg)
        status = ("passed" if summary["gate_passed"] else "warning") if approve else "failed"
        out = {**done, "security_review": {"decision": "approve" if approve else "reject", "by": by, "comment": comment},
               "steps": {"security_gate": step_record("security_gate", NAME, "security", status, msg, items=summary["checks"],
                                                      item_type="checks", explanation=comment, started=t0,
                                                      summary={"decision": "approve" if approve else "reject", "reviewer": by,
                                                               **{k.lower(): v for k, v in summary["findings"].items()}})}}
        return out if approve else {**out, "stopped_at": "security review (rejected by the reviewer)"}
