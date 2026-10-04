"""
Report Agent – decides the overall result from the gates, explains the root cause of a failure (LLM when
selected, rules otherwise) and writes the downloadable PDF report of the run.
"""

import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from llmapi.llm_provider import LLMProvider
from services.pdf_report import write_pdf
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


def overall(state: PipelineState) -> tuple[str, list[str]]:
    """PASS / FAIL / INCOMPLETE and the root-cause lines (first real failure first)."""
    steps = list((state.get("steps") or {}).values())
    failed = [s for s in steps if s["status"] in ("failed", "error")]
    blocked = [s for s in steps if s["status"] == "blocked"]
    lines = [f"{s['name']}{' – ' + s['component'] if s.get('component') else ''}: {s['message'][:240]}" for s in failed[:6]]
    if blocked:
        lines.append(f"{len(blocked)} step(s) were blocked by that: " + ", ".join(s["id"] for s in blocked[:8]))
    if state.get("stopped_at"):
        lines.append(f"the pipeline stopped at the {state['stopped_at']}")
    gates = (state.get("gates") or {}).values()
    if failed or blocked or any(not g["passed"] for g in gates):
        return "FAIL", lines
    if any(s["status"] == "skipped" for s in steps):
        return "INCOMPLETE", lines or ["some steps were skipped (e.g. Docker not running)"]
    return "PASS", lines


class ReportAgent:
    def __init__(self) -> None:
        self.node_name = "report_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        await emit(task_id, self.node_name, StreamStatus.START, "Writing the report")
        result, causes = overall(state)
        explanation = ""
        llm = await LLMProvider().get_llm(state.get("provider")) if result != "PASS" else None
        if llm:
            reply = await llm.ainvoke([SystemMessage(content="You are a release manager. In 3-5 short sentences explain why "
                                                             "this CI/CD run did not pass and what the team should fix first."),
                                       HumanMessage(content="\n".join(causes))])
            explanation = reply.content if isinstance(reply.content, str) else ""
        report = {"overall": result, "root_cause": causes, "explanation": explanation}
        pdf = Path(state["run_dir"]) / "report.pdf"
        try:
            write_pdf({**state, "report": report}, pdf)
            report["pdf"] = str(pdf)
        except Exception as e:  # noqa: BLE001
            report["pdf_error"] = str(e)
        await emit(task_id, self.node_name, StreamStatus.END, f"OVERALL: {result}", data=report)
        return {"overall": result, "report": report, "step_index": state.get("step_index", 0) + 1,
                "steps": {"report": step_record("report", "Report", "report", "passed", f"overall {result} · PDF written",
                                                explanation=explanation, started=t0)}}
