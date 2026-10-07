"""
Step report – one self-contained HTML page per pipeline step (opened from the ⓘ button in the UI).

Everything about the step in one place: what it is and why it runs, the tool and how it is used, what is expected,
the stage report (what · where · how · why · result · suggestions · blockers), the commands with their output,
the results (findings / gate checks / explained test cases with screenshots), the agent's reasoning and self-healing
notes, and the step's own log lines.
"""

import html
import json
from functools import lru_cache
from pathlib import Path

import yaml

from utils.stage_reports import stage_report

DOCS_FILE = Path(__file__).resolve().parents[1] / "config" / "step_docs.yml"

# step kind → the node whose events are this step's log lines
EVENT_NODE = {"checkout": "checkout_agent", "plan": "planner_agent", "questionnaire": "questionnaire_agent",
              "design": "pipeline_designer", "security_gate": "security_review", "release": "release_agent",
              "deploy": "deploy_agent", "functional": "functional_test_agent", "functional_gate": "functional_test_agent",
              "ui_tests": "ui_test_agent", "ui_gate": "ui_test_agent", "publish_tests": "publish_tests_agent",
              "approval": "approval_gate", "deploy_uat": "uat_deploy_agent", "report": "report_agent",
              "test_gate": "test", "container_gate": "image"}


@lru_cache(maxsize=1)
def step_docs() -> dict:
    return yaml.safe_load(DOCS_FILE.read_text(encoding="utf-8"))


def step_doc(step_id: str) -> dict:
    """The catalogue text of a step (scan.<name> → the scanner's text + the scan stage's purpose)."""
    docs = step_docs()
    kind, _, rest = step_id.partition(".")
    if kind == "scan":
        sc = docs["scanners"].get(rest, {})
        return {"what": sc.get("what", f"Security scanner {rest}."), "tool": sc.get("tool", rest), "how": sc.get("how", ""),
                "why": "Find security problems before anything is built or shipped – the findings feed the security gate "
                       "and the human review (HITL).",
                "expected": "No critical or high findings (lint findings never block).",
                "checks": "Every finding has a severity (CRITICAL / HIGH / MEDIUM / LOW) from the scanner, mapped to one scale."}
    return docs["steps"].get(kind, {})


def _event_matches(ev: dict, step_id: str) -> bool:
    kind, _, comp = step_id.partition(".")
    if kind == "scan":
        return ev["node"] == "security_agent" and (ev.get("message") or "").startswith(f"{comp}:")
    node = EVENT_NODE.get(kind, kind)
    return ev["node"] == (f"{node}.{comp}" if comp else node)


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _table(head: list[str], rows: list[list[str]]) -> str:
    """rows are already-escaped HTML cells."""
    if not rows:
        return "<p class='muted'>none</p>"
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def _badge(status: str) -> str:
    return f"<span class='badge {_e(status)}'>{_e(str(status).upper())}</span>"


def _results(rec: dict) -> str:
    items, kind = rec.get("items") or [], rec.get("item_type")
    if kind == "findings":
        return _table(["Severity", "Finding", "Where", "Package / fix", "AI triage"], [
            [_badge({"CRITICAL": "failed", "HIGH": "failed"}.get(f.get("severity"), "warning")) + " " + _e(f.get("severity")),
             _e(f.get("title")) + (f"<div class='muted'>{_e(f.get('rule_id'))}</div>" if f.get("rule_id") else ""),
             f"<code>{_e(f.get('file'))}{':' + _e(f.get('line')) if f.get('line') else ''}</code>",
             _e(" ".join(x for x in [f.get("package") or "", f.get("installed_version") or "",
                                     ("→ " + f["fixed_version"]) if f.get("fixed_version") else ""] if x))
             + (f"<div>{_e(f.get('recommendation'))}</div>" if f.get("recommendation") else ""),
             _e(f"{f['triage'].get('verdict')}: {f['triage'].get('explanation')} – fix: {f['triage'].get('fix')}") if f.get("triage") else ""]
            for f in items[:300]])
    if kind == "checks":
        return _table(["Check", "Actual", "Required", "Result"],
                      [[_e(c.get("name")), _e(c.get("actual")), _e(c.get("required")),
                        _badge("passed" if c.get("passed") else "failed")] for c in items])
    if kind == "tests":
        rows = []
        for c in items[:300]:
            how = c.get("how") or []
            how = how if isinstance(how, list) else [how]
            expl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in [
                ("About", _e(c.get("purpose"))), ("Checks", _e(c.get("checks"))),
                ("How", "<ol>" + "".join(f"<li>{_e(h)}</li>" for h in how) + "</ol>" if how else ""),
                ("Expected", _e(c.get("expected"))), ("Actual", _e(c.get("actual"))), ("Why", _e(c.get("why"))),
                ("Source", f"<code>{_e(c.get('file'))}:{_e(c.get('line'))}</code>" if c.get("file") else "")] if v)
            if c.get("code"):
                expl += f"<dt>Code</dt><dd><pre>{_e(c['code'][:2500])}</pre></dd>"
            if c.get("screenshot"):
                src = f"../../screenshots/{_e(c['screenshot'])}"         # page: …/{task}/steps/{step}/report.html
                expl += f"<dt>Screenshot</dt><dd><a href='{src}'><img src='{src}'></a></dd>"
            rows.append([f"<code>{_e(c.get('id'))}</code>", _e(c.get("name")) + (f"<details><summary>explanation</summary><dl>{expl}</dl></details>" if expl else ""),
                         _badge(c.get("status")), _e((c.get("message") or "")[:400])])
        return _table(["ID", "Test case", "Result", "Message"], rows)
    if kind == "services":
        return _table(["Service", "Status", "URL", "Detail"], [[_e(s.get("component")), _badge(s.get("status")),
                                                                 _e(s.get("url")), _e(s.get("message"))] for s in items])
    if kind == "components":
        return _table(["Component", "Stack", "Build", "Tests"], [
            [_e(c.get("name")), _e(f"{c.get('language')} {c.get('framework')}"), _e(" && ".join(c.get("build_commands") or [])),
             _e(c.get("test_command") or "–")] for c in items])
    return "<p class='muted'>This step has no item list – see the summary and the commands.</p>" if not items else \
        f"<pre>{_e(json.dumps(items[:50], indent=1, default=str))}</pre>"


def render_step_report(run: dict, step_id: str, events: list[dict]) -> str:
    rec = (run.get("steps") or {}).get(step_id) or {"id": step_id, "name": step_id, "status": "pending", "message": "not run yet"}
    doc, rep = step_doc(step_id), rec.get("report") or stage_report(rec)
    about = "".join(f"<dt>{k}</dt><dd>{_e(doc.get(f))}</dd>" for k, f in
                    [("What it is", "what"), ("Why it runs", "why"), ("Tool", "tool"), ("How it is done", "how"),
                     ("What is checked", "checks"), ("Expected", "expected")] if doc.get(f))
    stage = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in [
        ("What it did", _e(rep.get("what"))), ("Where", _e("; ".join(rep.get("where") or [])) or "the run's copy of the repository"),
        ("How", "<br>".join(f"<code>{_e(h)}</code>" for h in rep.get("how") or []) or "–"), ("Why", _e(rep.get("why"))),
        ("Result", _e(rep.get("result"))),
        ("Suggestions", "<ul>" + "".join(f"<li>{_e(s)}</li>" for s in rep.get("suggestions") or []) + "</ul>" if rep.get("suggestions") else "–"),
        ("Blockers", "<ul>" + "".join(f"<li>{_e(b)}</li>" for b in rep.get("blockers") or []) + "</ul>" if rep.get("blockers") else "none")])
    summary = _table(["Key", "Value"], [[_e(k), _e(v)] for k, v in (rec.get("summary") or {}).items()
                                        if v not in (None, "") and not isinstance(v, (dict, list))])
    cmds = "".join(
        f"<details{' open' if c.get('exit_code') else ''}><summary>{_badge('passed' if c.get('exit_code') == 0 else 'failed')} "
        f"<code>{_e(c.get('command'))}</code> <span class='muted'>in {_e(c.get('folder'))} · exit {_e(c.get('exit_code'))} · "
        f"{_e(c.get('seconds'))}s</span></summary><pre>{_e(c.get('output_tail'))}</pre></details>"
        for c in rec.get("commands") or []) or "<p class='muted'>No commands – this step works through the MCP servers or the API.</p>"
    logs = [e for e in events if _event_matches(e, step_id)]
    log_html = "<pre>" + "\n".join(f"#{e['id']} {_e(e['status'])}  {_e(e.get('message'))}" for e in logs[-400:]) + "</pre>" \
        if logs else "<p class='muted'>No log lines for this step.</p>"
    title = f"{rec.get('name', step_id)}{' – ' + rec['component'] if rec.get('component') else ''}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)} · DevOps step report</title>
<style>
:root{{--bg:#fff;--fg:#1d2433;--muted:#667085;--line:#e4e7ec;--card:#f8f9fb;--accent:#2b3a67}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f131a;--fg:#e6e9ef;--muted:#98a2b3;--line:#2a3140;--card:#161b24;--accent:#8fa3ff}}}}
body{{font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px;max-width:1200px;margin:auto;font-size:14px}}
h1{{color:var(--accent);margin:0 0 4px}} h2{{margin:28px 0 8px;font-size:17px;border-bottom:1px solid var(--line);padding-bottom:4px}}
.muted{{color:var(--muted)}} code{{font-family:Consolas,monospace;font-size:12px}}
dl{{display:grid;grid-template-columns:170px 1fr;gap:6px 14px;margin:0}} dt{{color:var(--muted);font-weight:600}} dd{{margin:0}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid var(--line);padding:5px 8px;vertical-align:top;text-align:left;font-size:13px}}
th{{background:var(--card)}} pre{{background:var(--card);border:1px solid var(--line);padding:8px;overflow:auto;max-height:420px;font-size:12px;white-space:pre-wrap}}
details{{margin:6px 0}} summary{{cursor:pointer}} img{{max-width:560px;border:1px solid var(--line)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.badge{{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:700;border:1px solid}}
.passed{{color:#1f7a4d;border-color:#1f7a4d55}} .failed,.error,.blocked{{color:#c4321f;border-color:#c4321f55}}
.warning,.skipped,.waiting{{color:#a66a00;border-color:#a66a0055}} .pending,.running{{color:var(--muted)}}
</style></head><body>
<h1>{_e(title)}</h1>
<p>{_badge(rec.get('status', 'pending'))} <span class="muted">{_e(rec.get('message'))}</span></p>
<p class="muted">Run {_e(run.get('task_id'))} · {_e(run.get('repo'))} · stage: {_e(rec.get('stage'))}
{' · ' + _e(rec.get('duration_s')) + 's' if rec.get('duration_s') else ''}</p>
<h2>About this step</h2><div class="card"><dl>{about or "<dd>–</dd>"}</dl></div>
<h2>Stage report</h2><div class="card"><dl>{stage}</dl></div>
<h2>Summary</h2>{summary}
<h2>Results</h2>{_results(rec)}
<h2>Commands</h2>{cmds}
{f"<h2>Agent reasoning / self-healing</h2><pre>{_e(rec['explanation'])}</pre>" if rec.get('explanation') else ''}
<h2>Logs of this step</h2>{log_html}
</body></html>"""
