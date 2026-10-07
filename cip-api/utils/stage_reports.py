"""
Stage reports – one clear, fixed-shape report per step, built from the step record (deterministic, no LLM):

    what · where · how · why · result · suggestions · blockers

`why` comes from the stage catalogue (config/devops_flow.yml); everything else from what the agent recorded
(commands, items, gates, explanation). Used by the dashboard, the run page and the PDF.
"""

from collections import Counter

from utils.devops_flow import why_of

SEV = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def stage_report(step: dict) -> dict:
    items, kind, status = step.get("items") or [], step.get("item_type"), step.get("status", "")
    cmds = step.get("commands") or []
    where = [f"component {step['component']}"] if step.get("component") else []
    where += sorted({c.get("folder") for c in cmds if c.get("folder")})[:4]
    how = [c["command"] for c in cmds[:6]] or [f"{k}: {v}" for k, v in (step.get("summary") or {}).items()
                                              if k in ("via", "registry", "network", "image", "planned by", "scanners")]
    result, suggestions, blockers = f"{status.upper()} – {step.get('message', '')[:300]}", [], []

    if kind == "findings":
        sev = Counter(f.get("severity") for f in items)
        result = f"{status.upper()} – {len(items)} findings ({', '.join(f'{sev[s]} {s.lower()}' for s in SEV if sev[s]) or 'none'})"
        top = [f for f in items if f.get("severity") in ("CRITICAL", "HIGH") and f.get("category") != "code_quality"]
        blockers = [f"{f['severity']}: {f['title'][:120]} ({f.get('file') or f.get('package') or ''}"
                    f"{':' + str(f['line']) if f.get('line') else ''})" for f in top[:8]]
        suggestions = list(dict.fromkeys((f.get("triage") or {}).get("fix") or f.get("recommendation") or "" for f in top))[:6]
        where += sorted({f.get("file") for f in items if f.get("file")})[:6]
    elif kind == "tests":
        c = Counter(t.get("status") for t in items)
        result = f"{status.upper()} – {c['passed']}/{len(items)} passed, {c['failed']} failed, {c['error']} errors, {c['skipped']} skipped"
        bad = [t for t in items if t.get("status") in ("failed", "error")]
        blockers = [f"{t.get('id', '')} {t.get('name', '')[:100]}: {(t.get('message') or '')[:120]}" for t in bad[:8]]
        if bad:
            suggestions.append("Open the failing tests above – a failing assertion means the application behaves differently than the test expects.")
    elif kind == "checks":
        bad = [c for c in items if not c.get("passed")]
        blockers = [f"{c['name']} = {c['actual']} (needs {c['required']})" for c in bad]
        suggestions = [f"Bring '{c['name']}' to {c['required']}" for c in bad][:6]
    elif kind == "services":
        bad = [s for s in items if s.get("status") != "passed"]
        result = f"{status.upper()} – " + ", ".join(f"{s.get('component')} {s.get('url') or ''} {s.get('status')}" for s in items)[:300]
        blockers = [f"{s.get('component')}: {s.get('message', '')[:200]}" for s in bad]
        if bad:
            suggestions.append("Check the container log tail of the failing service (Results tab) – it usually names the missing setting or port.")
    elif kind == "components":
        result = f"{status.upper()} – " + "; ".join(f"{c['name']} ({c['language']} {c['framework']})" for c in items)[:300]

    if status in ("failed", "error", "blocked") and not blockers:
        blockers.append(step.get("message", "")[:300])
    if step.get("explanation"):
        suggestions.append(step["explanation"].strip()[:800])
    attempts = (step.get("summary") or {}).get("self-heal attempts")
    if attempts:
        how.append(f"self-healing: {attempts} fix attempt(s) by the agent")
    return {"what": f"{step.get('name')}{' – ' + step['component'] if step.get('component') else ''}: {step.get('message', '')[:300]}",
            "where": where or ["the run's copy of the repository"], "how": how or ["see the commands / events of this step"],
            "why": why_of(step.get("id", "")), "result": result, "suggestions": [s for s in suggestions if s][:8],
            "blockers": [b for b in blockers if b][:10]}


GATE_OF = {"test": "test_gate", "image": "container_gate", "functional": "functional_gate", "ui_tests": "ui_gate"}
QUALITY_STEPS = ("scan", "security_gate", "test", "image", "functional", "ui_tests")
HIDDEN_GATES = ("test_gate", "container_gate", "functional_gate", "ui_gate")      # shown inside the step they check


def gate_of(step_id: str, steps: dict) -> dict | None:
    kind, _, comp = step_id.partition(".")
    gid = GATE_OF.get(kind)
    return steps.get(f"{gid}.{comp}" if comp else gid) if gid else None


def quality(step: dict, gate: dict | None) -> str | None:
    """What the step found (colour of its ⓘ): critical – critical / high findings or CVEs, secrets, failed tests;
    warning – other findings, a quality gate below its threshold (e.g. coverage); clean – nothing to report."""
    if step.get("id", "").split(".")[0] not in QUALITY_STEPS or step.get("status") != "passed":
        return None                                   # only steps that ran and produce findings / test results
    items, kind = step.get("items") or [], step.get("item_type")
    checks = (gate or {}).get("items") or (items if kind == "checks" else [])
    bad = [c for c in checks if not c.get("passed")]
    if kind == "findings" and any(f.get("severity") in ("CRITICAL", "HIGH") and f.get("category") != "code_quality" for f in items) \
            or kind == "tests" and any(t.get("status") in ("failed", "error") for t in items) \
            or any(w in c.get("name", "") for c in bad for w in ("critical", "high", "secrets")):
        return "critical"
    if (kind == "findings" and items) or bad or step.get("status") == "warning":
        return "warning"
    return "clean"


def with_reports(steps: dict) -> dict:
    steps = steps or {}
    out = {}
    for k, v in steps.items():
        gate = gate_of(k, steps)
        out[k] = {**v, "report": stage_report(v), "quality": quality(v, gate),
                  **({"gate": {"name": gate.get("name"), "status": gate.get("status"), "checks": gate.get("items") or []}} if gate else {})}
    return out


def stage_summary(steps: dict) -> dict:
    """Worst status per stage (for the dashboard grid)."""
    rank = ["failed", "error", "blocked", "warning", "running", "passed", "skipped"]   # one skipped scanner ≠ amber stage
    out: dict[str, str] = {}
    for k, s in (steps or {}).items():
        if k.split(".")[0] in HIDDEN_GATES:
            continue
        st, cur = s.get("stage", "other"), out.get(s.get("stage", "other"))
        if cur is None or (s["status"] in rank and rank.index(s["status"]) < rank.index(cur if cur in rank else "passed")):
            out[st] = s["status"]
    return out
