"""
Quality gates – deterministic thresholds from core.settings.GATES. No LLM is involved in pass / fail.
"""

from core.settings import GATES


def _gate(name: str, checks: list[tuple[str, object, str, bool]], blocked: str = "") -> dict:
    rows = [{"name": n, "actual": a, "required": r, "passed": ok} for n, a, r, ok in checks]
    return {"name": name, "passed": not blocked and all(c["passed"] for c in rows), "checks": rows, "blocked": blocked}


def security_gate(findings: list[dict]) -> dict:
    g = GATES["security"]
    findings = [f for f in findings if f.get("category") != "code_quality"]      # lint is reported, never blocks
    crit = sum(f["severity"] == "CRITICAL" for f in findings)
    high = sum(f["severity"] == "HIGH" and f.get("category") != "secret" for f in findings)
    secrets = sum(f.get("category") == "secret" for f in findings)
    return _gate("security", [("critical findings", crit, f"<= {g['critical']}", crit <= g["critical"]),
                              ("high findings", high, f"<= {g['high']}", high <= g["high"]),
                              ("secrets", secrets, f"<= {g['secrets']}", secrets <= g["secrets"])])


def test_gate(summary: dict, coverage: float | None, blocked: str = "") -> dict:
    g = GATES["testing"]
    cov = coverage if coverage is not None else 0.0
    return _gate("testing", [("tests executed", summary.get("executed", 0), ">= 1", summary.get("executed", 0) >= 1),
                             ("pass rate %", summary.get("pass_rate", 0.0), f">= {g['pass_rate']}", summary.get("pass_rate", 0) >= g["pass_rate"]),
                             ("line coverage %", cov, f">= {g['coverage']}", cov >= g["coverage"])], blocked)


def container_gate(image: dict, findings: list[dict], scanned: bool, blocked: str = "") -> dict:
    g = GATES["container"]
    crit = sum(f["severity"] == "CRITICAL" for f in findings)
    high = sum(f["severity"] == "HIGH" for f in findings)
    return _gate("container", [("image built", "yes" if image.get("built") else "no", "yes", bool(image.get("built"))),
                               ("image scanned", "yes" if scanned else "no", "yes", scanned),
                               ("critical CVEs", crit, f"<= {g['critical']}", crit <= g["critical"]),
                               ("high CVEs", high, f"<= {g['high']}", high <= g["high"])], blocked)


def functional_gate(cases: list[dict], healthy: bool, blocked: str = "") -> dict:
    run = [c for c in cases if c["status"] in ("passed", "failed", "error")]
    rate = round(100 * sum(c["status"] == "passed" for c in run) / len(run), 1) if run else 0.0
    return _gate("functional", [("deployment healthy", "yes" if healthy else "no", "yes", healthy),
                                ("functional tests executed", len(run), ">= 1", len(run) >= 1),
                                ("pass rate %", rate, f">= {GATES['functional']['pass_rate']}", rate >= GATES["functional"]["pass_rate"])],
                 blocked)


def ui_gate(cases: list[dict], blocked: str = "") -> dict:
    run = [c for c in cases if c["status"] in ("passed", "failed", "error")]
    rate = round(100 * sum(c["status"] == "passed" for c in run) / len(run), 1) if run else 0.0
    need = GATES["ui"]["pass_rate"]
    return _gate("ui", [("UI tests executed", len(run), ">= 1", len(run) >= 1),
                        ("pass rate %", rate, f">= {need}", rate >= need)], blocked)
