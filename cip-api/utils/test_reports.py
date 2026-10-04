"""
Read test results and coverage written by any test runner into one shape:

    cases:    [{"id": "TC-UT-001", "name", "suite", "status": passed|failed|error|skipped, "time_s", "message"}]
    coverage: line coverage percent or None

Formats: JUnit XML (pytest, surefire, gradle, vitest, phpunit …), Jest JSON, `go test -json`,
Cobertura XML / coverage.xml, JaCoCo CSV, Istanbul coverage-summary.json, Go cover profile summary.
"""

import csv
import glob
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _status(tc: ET.Element) -> tuple[str, str]:
    for tag, status in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
        el = tc.find(tag)
        if el is not None:
            return status, ((el.get("message") or "") + "\n" + (el.text or "")).strip()[:3000]
    return "passed", ""


def parse_results(folder: Path, patterns: list[str]) -> list[dict]:
    """All test cases from the report files matching the glob patterns (relative to the component folder)."""
    cases: list[dict] = []
    for pat in patterns:
        for f in sorted(glob.glob(str(folder / pat), recursive=True, include_hidden=True)):
            p = Path(f)
            text = p.read_text(encoding="utf-8", errors="replace")
            if p.suffix == ".xml" and "<testsuite" in text:
                for tc in ET.fromstring(text).iter("testcase"):
                    st, msg = _status(tc)
                    cases.append({"name": tc.get("name", ""), "suite": tc.get("classname") or tc.get("file") or p.stem,
                                  "status": st, "time_s": float(tc.get("time") or 0), "message": msg})
            elif p.suffix == ".json" and '"testResults"' in text:          # Jest --json
                for suite in json.loads(text).get("testResults", []):
                    for a in suite.get("assertionResults", []):
                        cases.append({"name": a.get("fullName") or a.get("title"), "suite": Path(suite.get("name", "")).name,
                                      "status": {"passed": "passed", "failed": "failed"}.get(a.get("status"), "skipped"),
                                      "time_s": (a.get("duration") or 0) / 1000, "message": "\n".join(a.get("failureMessages", []))[:3000]})
            elif p.suffix == ".json" and '"Action"' in text:              # go test -json
                for line in text.splitlines():
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("Test") and ev.get("Action") in ("pass", "fail", "skip") and "/" not in ev["Test"]:
                        cases.append({"name": ev["Test"], "suite": ev.get("Package", ""), "time_s": ev.get("Elapsed", 0),
                                      "status": {"pass": "passed", "fail": "failed", "skip": "skipped"}[ev["Action"]], "message": ""})
    for i, c in enumerate(cases, 1):
        c["id"] = f"TC-UT-{i:03d}"
    return cases


SKIP = {"node_modules", ".git", ".cip-venv", ".venv", "venv", "__pycache__", ".gradle"}


def _find(folder: Path, match) -> list[str]:
    """Files under the component whose name matches – .cip/ and build folders included, dependency folders skipped."""
    out = []
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP]
        out += [os.path.join(dirpath, f) for f in files if match(f)]
    return out


def coverage_percent(folder: Path) -> float | None:
    """Line coverage from whichever coverage report the runner produced."""
    for f in _find(folder, lambda n: n == "coverage-summary.json"):
        try:
            return round(json.loads(Path(f).read_text())["total"]["lines"]["pct"], 1)
        except (ValueError, KeyError):
            pass
    for f in _find(folder, lambda n: n == "jacoco.csv"):
        missed = covered = 0
        for row in csv.DictReader(open(f, encoding="utf-8")):
            missed += int(row.get("LINE_MISSED") or 0)
            covered += int(row.get("LINE_COVERED") or 0)
        if missed + covered:
            return round(100 * covered / (missed + covered), 1)
    for f in _find(folder, lambda n: n == "cover.out"):                    # Go cover profile
        total = covered = 0
        for line in Path(f).read_text(errors="replace").splitlines()[1:]:
            parts = line.rsplit(" ", 2)
            if len(parts) == 3 and parts[1].isdigit():
                total += int(parts[1])
                covered += int(parts[1]) if parts[2].strip() != "0" else 0
        if total:
            return round(100 * covered / total, 1)
    for f in _find(folder, lambda n: n.endswith(".xml") and n.startswith(("coverage", "cobertura"))):
        m = re.search(r'<coverage[^>]*line-rate="([\d.]+)"', Path(f).read_text(errors="replace")[:2000])
        if m:
            return round(float(m.group(1)) * 100, 1)
    return None


def summarize(cases: list[dict]) -> dict:
    run = [c for c in cases if c["status"] in ("passed", "failed", "error")]
    passed = sum(c["status"] == "passed" for c in run)
    return {"total": len(cases), "executed": len(run), "passed": passed, "failed": len(run) - passed,
            "skipped": len(cases) - len(run), "pass_rate": round(100 * passed / len(run), 1) if run else 0.0}
