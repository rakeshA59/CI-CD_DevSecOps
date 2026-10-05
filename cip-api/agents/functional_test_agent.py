"""
Functional Test Agent – tests the application running in dev.

For each healthy service: explores the web pages it links to (same origin) and checks each one loads without
an error page; for APIs reads the OpenAPI spec and calls every GET endpoint without path parameters. With an LLM
the agent also proposes user-journey checks (page → expected text) and runs them. Containers are removed afterwards.
"""

import re
import time
from typing import List
from urllib.parse import urljoin, urlparse

import httpx
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from agent_states.pipeline_state import PipelineState
from llmapi.llm_provider import LLMProvider
from llmapi.structured_llm import ask_structured
from mcp_services.mcp_clients.mcp_tool_client import docker_client
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.quality_gates import functional_gate

ERRORS = ("Traceback (most recent call last)", "Internal Server Error", "Whitelabel Error Page", "Cannot GET /",
          "Application error", "502 Bad Gateway", "Unhandled Runtime Error")


class Journey(BaseModel):
    title: str
    path: str
    expect_text: str


class Journeys(BaseModel):
    journeys: List[Journey]


class FunctionalTestAgent:
    def __init__(self) -> None:
        self.node_name = "functional_test_agent"

    @staticmethod
    def _explain(case: dict, base: str, path: str, kind: str, expect: str, status_code=None, errs=(), found=None) -> dict:
        """Plain explanation of a functional test case (what / checks / how / expected / actual / why)."""
        url = urljoin(base, path)
        purpose = {"API": f"Checks that the API endpoint GET {path} of the running service answers correctly.",
                   "journey": f"Checks a user journey: a user opening {path} must see '{expect}'.",
                   }.get(kind, f"Checks that the page {path} of the running application loads for a user without an error.")
        checks = ["HTTP status below 400 (the server answered without a client / server error)",
                  "the response does not contain a known error page (stack trace, 'Internal Server Error', 502, …)"]
        if expect:
            checks.append(f"the response contains the text '{expect}'")
        ok = case["status"] == "passed"
        actual = (f"HTTP {status_code}" + (f", error page text found: {', '.join(errs)}" if errs else ", no error page")
                  + (f", text '{expect}' {'found' if found else 'not found'}" if expect else "")
                  if status_code is not None else f"request failed: {case['message']}")
        case.update(kind=kind, purpose=purpose, checks="; ".join(checks) + ".",
                    how=[f"HTTP GET {url} on the container deployed in dev (httpx, 20s timeout, redirects followed)",
                         "status code and body checked by the functional test agent"],
                    expected="; ".join(checks), actual=actual,
                    why=("Passed: the server answered and every check held." if ok else
                         f"Failed: {case['message'] or 'a check did not hold'}." if case["status"] == "failed" else
                         f"Error: the request could not be completed ({case['message']}) – the service is down or not reachable."))
        return case

    async def _case(self, client: httpx.AsyncClient, base: str, path: str, title: str, expect: str = "", kind: str = "page") -> dict:
        t0 = time.time()
        try:
            r = await client.get(urljoin(base, path))
            text = r.text
            errs = [e for e in ERRORS if e in text]
            ok = r.status_code < 400 and not errs and (not expect or expect.lower() in text.lower())
            msg = "" if ok else f"HTTP {r.status_code}" + (f", page shows: {errs}" if errs else "") + (
                f", expected text '{expect}' not found" if expect and expect.lower() not in text.lower() else "")
            case = {"name": title, "suite": base, "status": "passed" if ok else "failed", "time_s": round(time.time() - t0, 2),
                    "message": msg, "html": text[:200_000]}
            return self._explain(case, base, path, kind, expect, r.status_code, errs, bool(expect) and expect.lower() in text.lower())
        except Exception as e:  # noqa: BLE001
            case = {"name": title, "suite": base, "status": "error", "time_s": round(time.time() - t0, 2), "message": str(e)}
            return self._explain(case, base, path, kind, expect)

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        dep = state.get("deploy") or {}
        up = [s for s in dep.get("services", []) if s["status"] == "passed" and s.get("url")]
        if not up:
            gate = functional_gate([], False, blocked="no service is running in dev – see the deploy step")
            await emit(task_id, self.node_name, StreamStatus.SKIPPED, gate["blocked"])
            return {"functional": {"cases": []}, "gates": {"functional": gate}, "step_index": state["step_index"] + 1,
                    "steps": {"functional": step_record("functional", "Functional tests", "functional tests", "blocked", gate["blocked"])}}
        await emit(task_id, self.node_name, StreamStatus.START, f"Testing {len(up)} running service(s)")
        cases: list[dict] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for s in up:
                base = s["url"]
                home = await self._case(client, base, "/", f"{s['component']}: home page loads")
                kind = next((c["kind"] for c in state.get("components", []) if c["name"] == s["component"]), "")
                if kind != "api" or home["status"] == "passed":       # an API without a root page is fine
                    cases.append(home)
                links = {urlparse(urljoin(base, h)).path for h in re.findall(r'href="([^"#?]+)"', home.get("html", ""))}
                for path in sorted(p for p in links if p and p != "/" and not re.search(r"\.(css|js|png|svg|ico|jpg)$", p))[:12]:
                    cases.append(await self._case(client, base, path, f"{s['component']}: page {path} loads"))
                for spec in ("/openapi.json", "/v3/api-docs"):
                    r = await client.get(urljoin(base, spec))
                    if r.status_code == 200 and "paths" in r.text:
                        for path, ops in list(r.json().get("paths", {}).items())[:25]:
                            if "get" in ops and "{" not in path:
                                cases.append(await self._case(client, base, path, f"{s['component']}: GET {path} answers", kind="API"))
                        break
                llm = await LLMProvider().get_llm(state.get("provider"))
                if llm and home.get("html"):
                    j = await ask_structured(llm, Journeys, "You are a QA engineer. Propose up to 6 user-facing checks of this "
                                             "web app: a page path and a short text a user must see there.",
                                             f"Home page HTML:\n{home['html'][:20000]}\nKnown paths: {sorted(links)[:30]}")
                    for x in (j.journeys if j else []):
                        cases.append(await self._case(client, base, x.path, f"{s['component']}: {x.title}", x.expect_text, kind="journey"))
        for i, c in enumerate(cases, 1):
            c.pop("html", None)
            c["id"] = f"TC-FT-{i:03d}"
            await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{c['id']} {c['status'].upper()} {c['name']}")
        if not (state.get("options") or {}).get("keep_running"):
            await docker_client().call_tool("docker_remove", {"names": [f"{dep['network']}-{s['component']}" for s in dep["services"]],
                                                              "network": dep["network"]})
        gate = functional_gate(cases, all(s["status"] == "passed" for s in dep["services"]))
        passed = sum(c["status"] == "passed" for c in cases)
        msg = f"{passed}/{len(cases)} passed · gate {'PASS' if gate['passed'] else 'FAIL'}"
        await emit(task_id, self.node_name, StreamStatus.END, msg)
        return {"functional": {"cases": cases}, "gates": {"functional": gate}, "step_index": state["step_index"] + 1,
                "steps": {"functional": step_record("functional", "Functional tests", "functional tests",
                                                    "passed" if gate["passed"] else "failed", msg, items=cases, item_type="tests", started=t0),
                          "functional_gate": step_record("functional_gate", "Functional gate", "functional tests",
                                                         "passed" if gate["passed"] else "failed", msg, items=gate["checks"], item_type="checks")}}
