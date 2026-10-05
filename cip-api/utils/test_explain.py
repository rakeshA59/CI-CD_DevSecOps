"""
Test-case explanations – every test case gets a plain explanation the report can show:

    purpose   what the test is about (what behaviour of the application it protects)
    checks    what exactly it verifies (the assertions / expected outcome)
    how       how it was run: test file + line, runner, the steps (and `code` = the test's own source)
    expected  what had to be true
    actual    what happened
    why       why it passed / failed

Unit tests: the test's source is found in the repository (file, line, assertions) – deterministic. With an LLM the
purpose / checks / why are then written in plain English in batches. Functional and UI tests fill these fields
themselves when they run (they know their own steps).
"""

import os
import re
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from llmapi.structured_llm import ask_structured

TEST_FILE = re.compile(r"(\.(test|spec)\.[jt]sx?$|^test_.*\.py$|_test\.py$|Tests?\.java$|_test\.go$|Test\.kt$)")
SKIP = {"node_modules", ".git", ".venv", "venv", ".cip-venv", "dist", "build", "target", "__pycache__", ".cip"}
ASSERT = re.compile(r"\b(expect\(|assert|assertEquals|assertThat|assertTrue|assertFalse|should\.|t\.(Error|Fatal)|"
                    r"toBe|toEqual|toHave|toContain|toMatch|toThrow)")


class Explanation(BaseModel):
    id: str
    purpose: str = Field(description="what behaviour of the application this test protects – one plain sentence")
    checks: str = Field(description="what exactly it verifies – the expected outcome / assertions, one sentence")
    why: str = Field(description="why it passed or failed, in plain words (for a failure: the likely cause)")


class Explanations(BaseModel):
    items: List[Explanation]


def _test_files(folder: Path) -> list[Path]:
    out = []
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP]
        out += [Path(dirpath) / f for f in files if TEST_FILE.search(f) or "cip_generated_tests" in dirpath]
    return out[:400]


def _locate(title: str, files: dict[Path, list[str]]) -> tuple[str, int, str]:
    """(file, line, code) of the test whose title / function name matches."""
    names = [title] + ([title.split(".")[-1]] if "." in title else [])
    for path, lines in files.items():
        for i, line in enumerate(lines):
            if any(f"'{n}'" in line or f'"{n}"' in line or f"`{n}`" in line or re.search(rf"\b(def|func|void|fun)\s+{re.escape(n)}\b", line)
                   for n in names if n):
                indent = len(line) - len(line.lstrip())
                body = [line]
                for nxt in lines[i + 1:i + 40]:
                    body.append(nxt)
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent and nxt.strip()[:1] in ("}", ")") or \
                            (path.suffix == ".py" and nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent and len(body) > 2):
                        break
                return str(path), i + 1, "\n".join(body).rstrip()
    return "", 0, ""


def _humanize(name: str) -> str:
    return re.sub(r"[_]+", " ", re.sub(r"^test_?", "", name, flags=re.I)).strip()


def explain_unit_tests(cases: list[dict], folder: Path, runner: str = "") -> list[dict]:
    """Fill the explanation fields of unit test cases from the repository's own test source (no LLM)."""
    files = {}
    for f in _test_files(folder):
        try:
            files[f] = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
    for c in cases:
        title = c["name"].split(" > ")[-1].strip()
        path, line, code = _locate(title, files)
        rel = os.path.relpath(path, folder).replace("\\", "/") if path else ""
        asserts = [ln.strip() for ln in code.splitlines() if ASSERT.search(ln)][:5]
        suite = " > ".join(c["name"].split(" > ")[:-1]) or c.get("suite", "")
        c.setdefault("kind", "unit")
        c.setdefault("purpose", f"Unit test '{_humanize(title.split('.')[-1])}'" + (f" of {suite}" if suite else "")
                     + " – it calls the code under test and compares the result with what the developer expects.")
        c.setdefault("checks", "  ·  ".join(a.rstrip(";") for a in asserts) if asserts else "the test's own assertions (see the code)")
        c.setdefault("how", [f"test {rel}:{line}" if rel else f"test '{title}' in suite {c.get('suite', '')}",
                             f"run by the repo's test runner{': ' + runner[:160] if runner else ''}"])
        c.setdefault("code", code[:2500])
        c.setdefault("file", rel)
        c.setdefault("line", line)
        c.setdefault("expected", "all assertions hold" + (f" ({len(asserts)} shown in the code)" if asserts else ""))
        first = (c.get("message") or "").strip().splitlines()[:1]
        c.setdefault("actual", "all assertions held" + (f" in {c['time_s']}s" if c.get("time_s") else "") if c["status"] == "passed"
                     else "skipped by the test runner" if c["status"] == "skipped" else (first[0][:400] if first else c["status"]))
        c.setdefault("why", "Passed: every assertion in the test held." if c["status"] == "passed" else
                     "Skipped: the test is marked skip / todo in the repository." if c["status"] == "skipped" else
                     f"Failed: {c['actual']}")
    return cases


async def explain_with_llm(llm, cases: list[dict], limit: int = 200) -> list[dict]:
    """Plain-English purpose / checks / why for each case (batches of 30); keeps the deterministic text on failure."""
    if not llm:
        return cases
    todo = cases[:limit]
    for i in range(0, len(todo), 30):
        batch = todo[i:i + 30]
        listing = "\n\n".join(f"[{c['id']}] {c['name']} · {c['status'].upper()}\ncode:\n{(c.get('code') or '')[:700]}"
                              + (f"\nfailure: {(c.get('message') or '')[:400]}" if c["status"] in ("failed", "error") else "")
                              for c in batch)
        res = await ask_structured(llm, Explanations,
                                   "You explain automated tests to a product owner who does not read code. For every test: "
                                   "purpose = what behaviour of the application it protects; checks = what exactly it verifies; "
                                   "why = why it passed (what that proves) or why it failed (the likely cause, application vs test). "
                                   "One short sentence each, concrete, no jargon.", listing)
        for e in (res.items if res else []):
            c = next((x for x in batch if x["id"] == e.id), None)
            if c:
                c.update(purpose=e.purpose, checks=e.checks, why=e.why)
    return cases
