"""
Publish Tests Agent (guided flow) – collects every test result of the run (unit tests of all components, AI-written
tests, functional tests) into one published test report: JUnit XML (for any CI / test-management tool) and a
readable HTML page, stored with the run and downloadable from the dashboard.
"""

import html
import time
from pathlib import Path
from xml.sax.saxutils import quoteattr

from langchain_core.runnables import RunnableConfig

from agent_states.pipeline_state import PipelineState
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record


def _suites(steps: dict) -> dict[str, list[dict]]:
    suites: dict[str, list[dict]] = {}
    for sid, s in steps.items():
        if s.get("item_type") == "tests" and (sid.startswith("test.") or sid in ("functional", "ui_tests")):
            suites[f"{s['name']}{' – ' + s['component'] if s.get('component') else ''}"] = s.get("items") or []
    return suites


def junit_xml(suites: dict[str, list[dict]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>"]
    for suite, cases in suites.items():
        fails = sum(c["status"] == "failed" for c in cases)
        errs = sum(c["status"] == "error" for c in cases)
        out.append(f"  <testsuite name={quoteattr(suite)} tests=\"{len(cases)}\" failures=\"{fails}\" errors=\"{errs}\">")
        for c in cases:
            out.append(f"    <testcase name={quoteattr(c.get('name', ''))} classname={quoteattr(c.get('suite') or suite)} "
                       f"time=\"{c.get('time_s') or 0}\">")
            if c["status"] in ("failed", "error"):
                out.append(f"      <{'failure' if c['status'] == 'failed' else 'error'} message={quoteattr((c.get('message') or '')[:500])}/>")
            elif c["status"] == "skipped":
                out.append("      <skipped/>")
            out.append("    </testcase>")
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out)


def _explain_html(c: dict) -> str:
    """The plain explanation of a test case as a small definition list (empty when the case has none)."""
    e = html.escape
    how = c.get("how") or []
    how = how if isinstance(how, list) else [how]
    rows = [("What it is about", c.get("purpose")), ("What it checks", c.get("checks")),
            ("How", "<ol>" + "".join(f"<li>{e(str(h))}</li>" for h in how) + "</ol>" if how else ""),
            ("Expected", c.get("expected")), ("Actual", c.get("actual")),
            ("Why it passed" if c["status"] == "passed" else "Why it did not pass", c.get("why")),
            ("Test source", f"{c['file']}:{c.get('line') or ''}" if c.get("file") else "")]
    body = "".join(f"<dt>{k}</dt><dd>{v if k == 'How' else e(str(v))}</dd>" for k, v in rows if v)
    if c.get("code"):
        body += f"<dt>Test code</dt><dd><pre>{e(c['code'][:2500])}</pre></dd>"
    if c.get("screenshot"):
        src = f"../screenshots/{e(c['screenshot'])}"
        body += f"<dt>Screenshot</dt><dd><a href='{src}'><img src='{src}' alt='{e(c.get('id') or '')}'></a></dd>"
    return f"<details><summary>explanation</summary><dl>{body}</dl></details>" if body else ""


def html_report(task_id: str, suites: dict[str, list[dict]]) -> str:
    rows = "".join(
        f"<tr class='{c['status']}'><td>{html.escape(s)}</td><td>{html.escape(c.get('id') or '')}</td>"
        f"<td>{html.escape(c.get('name', ''))}{(' <small>(' + html.escape(c['kind']) + ' test)</small>') if c.get('kind') else ''}"
        f"{_explain_html(c)}</td><td>{c['status'].upper()}</td><td>{html.escape((c.get('message') or '')[:300])}</td></tr>"
        for s, cases in suites.items() for c in cases)
    total = sum(len(c) for c in suites.values())
    passed = sum(c["status"] == "passed" for cs in suites.values() for c in cs)
    return (f"<!doctype html><meta charset='utf-8'><title>Test results {html.escape(task_id)}</title>"
            "<style>body{font-family:system-ui;margin:24px}td,th{border:1px solid #ddd;padding:4px 8px;font-size:13px;vertical-align:top}"
            "table{border-collapse:collapse}.failed,.error{background:#fde8e8}.passed{background:#eaf7ee}"
            "details{margin-top:4px}summary{cursor:pointer;color:#555;font-size:12px}dl{display:grid;grid-template-columns:150px 1fr;"
            "gap:2px 10px;margin:6px 0;font-size:12px}dt{color:#555;font-weight:600}dd{margin:0}pre{background:#f6f6f6;padding:6px;"
            "overflow:auto;max-height:260px;font-size:11px}img{max-width:520px;border:1px solid #ccc}ol{margin:0;padding-left:18px}</style>"
            f"<h1>Test results – {html.escape(task_id)}</h1><p>{passed}/{total} passed · open “explanation” under a test to see "
            "what it is about, what it checks, how it ran, the result and why</p>"
            f"<table><tr><th>Suite</th><th>ID</th><th>Test</th><th>Result</th><th>Message</th></tr>{rows}</table>")


class PublishTestsAgent:
    def __init__(self) -> None:
        self.node_name = "publish_tests_agent"

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        suites = _suites(state.get("steps") or {})
        folder = Path(state["run_dir"]) / "test-results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "junit.xml").write_text(junit_xml(suites), encoding="utf-8")
        (folder / "test-report.html").write_text(html_report(task_id, suites), encoding="utf-8")
        cases = [{**c, "suite": s} for s, cs in suites.items() for c in cs]
        passed = sum(c["status"] == "passed" for c in cases)
        failed = sum(c["status"] in ("failed", "error") for c in cases)
        status = "skipped" if not cases else "passed" if not failed else "warning"
        msg = (f"{passed}/{len(cases)} passed in {len(suites)} suite(s) · published junit.xml + test-report.html"
               if cases else "no test results to publish (no tests ran)")
        await emit(task_id, self.node_name, StreamStatus.END, msg)
        return {"step_index": state["step_index"] + 1,
                "steps": {"publish_tests": step_record("publish_tests", "Publish test results", "test results", status, msg,
                                                       items=cases[:500], item_type="tests", started=t0,
                                                       summary={"suites": len(suites), "tests": len(cases), "passed": passed,
                                                                "failed": failed, "files": "junit.xml, test-report.html"})}}
