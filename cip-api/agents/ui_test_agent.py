"""
UI Test Agent (guided flow) – tests the running application in a real browser (Selenium + headless Chrome).

For every web service that came up in dev:
    1. page load      every page linked from the app renders (JavaScript executed), shows content, no error page
    2. console        the browser console has no JavaScript errors on that page
    3. navigation     clicking the app's own navigation links really changes the page
    4. forms          each form can be filled with sample data and submitted without breaking the app
    5. journeys       with an LLM: user journeys written from the real pages (open → type → click → expect text)
Every check records its purpose, what it checks, the exact browser steps, expected vs actual and a screenshot.
The dev containers are removed afterwards. The UI gate is a fixed pass-rate threshold.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import List, Literal
from urllib.parse import urljoin, urlparse

import httpx
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from agent_states.pipeline_state import PipelineState
from core.settings import CHROME_BINARY, CHROMEDRIVER_PATH
from llmapi.llm_provider import LLMProvider
from llmapi.structured_llm import ask_structured
from mcp_services.mcp_clients.mcp_tool_client import docker_client
from services.stream_event_writer import StreamStatus
from utils.agent_events import emit, step_record
from utils.quality_gates import ui_gate

ERROR_TEXT = ("Traceback (most recent call last)", "Internal Server Error", "Cannot GET /", "Application error",
              "502 Bad Gateway", "Unhandled Runtime Error", "Something went wrong")
SAMPLE = {"email": "cip.tester@example.com", "password": "CipTest@12345", "number": "1", "tel": "5551234567",
          "url": "https://example.com", "date": "2026-01-15", "search": "test"}
COLLECT_JS = """
const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
const label = e => (e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || e.placeholder || e.name || e.id || '';
return {
  title: document.title,
  text: (document.body ? document.body.innerText : '').slice(0, 1500),
  links: [...document.querySelectorAll('a[href]')].filter(vis).map(a => ({text: a.innerText.trim().slice(0, 60), href: a.href})).slice(0, 40),
  inputs: [...document.querySelectorAll('input, textarea, select')].filter(vis).map(e => ({type: e.type || e.tagName.toLowerCase(), label: label(e)})).slice(0, 20),
  buttons: [...document.querySelectorAll('button, input[type=submit], [role=button]')].filter(vis).map(b => (b.innerText || b.value || '').trim().slice(0, 40)).filter(Boolean).slice(0, 20),
  forms: document.querySelectorAll('form').length
};"""


API_PAGES = ("swagger-ui", "redoc", "openapi.json", '"openapi":', "graphiql")
UI_PATHS = ("/", "/index.html", "/static/index.html", "/ui/", "/app/")


async def find_ui(url: str) -> str:
    """The URL of a real user-facing HTML page of a running service – not an API doc page (Swagger / ReDoc / OpenAPI),
    not JSON, not an error page. '' when the service has no UI."""
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for path in UI_PATHS:
            try:
                r = await client.get(urljoin(url, path))
            except httpx.HTTPError:
                continue
            body = r.text[:20000]
            if (r.status_code < 400 and "html" in r.headers.get("content-type", "") and "<body" in body.lower()
                    and not any(x in body.lower() for x in API_PAGES) and not any(e in body for e in ERROR_TEXT)
                    and "/docs" not in str(r.url) and "/redoc" not in str(r.url)):
                return str(r.url)
    return ""


class Step(BaseModel):
    action: Literal["open", "click", "type", "expect_text", "expect_url"]
    target: str = Field("", description="open/expect_url: a path like /login · click/type: the visible text, label, "
                                        "placeholder or a CSS selector · expect_text: unused")
    value: str = Field("", description="type: the text to enter · expect_text: text that must be visible")


class UIJourney(BaseModel):
    title: str
    purpose: str = Field(description="what a user wants to achieve, one sentence")
    steps: List[Step]


class UIJourneys(BaseModel):
    journeys: List[UIJourney]


def _driver():
    """Headless Chrome; Selenium Manager finds Chrome and downloads the matching chromedriver when needed."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    opts = webdriver.ChromeOptions()
    for a in ("--headless=new", "--window-size=1366,900", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        opts.add_argument(a)
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    binary = CHROME_BINARY or next((p for p in (os.getenv("CHROME_BIN"), "/opt/pw-browsers/chromium") if p and Path(p).exists()), "")
    if binary:
        opts.binary_location = binary
    service = Service(CHROMEDRIVER_PATH) if CHROMEDRIVER_PATH else Service()
    driver = webdriver.Chrome(options=opts, service=service)
    driver.set_page_load_timeout(30)
    return driver


class Browser:
    """Thin synchronous helpers around one WebDriver session (run in a worker thread)."""

    def __init__(self, driver, shots: Path):
        self.d, self.shots = driver, shots

    def console_errors(self) -> list[str]:
        try:
            logs = self.d.get_log("browser")
        except Exception:  # noqa: BLE001 – some drivers do not expose the log
            return []
        return [x["message"][:300] for x in logs if x.get("level") == "SEVERE" and "favicon" not in x.get("message", "")]

    def open(self, url: str):
        self.d.get(url)
        end = time.time() + 10
        while time.time() < end and self.d.execute_script("return document.readyState") != "complete":
            time.sleep(0.2)
        time.sleep(1.2)                                  # let a single-page app render after load

    def page(self) -> dict:
        return self.d.execute_script(COLLECT_JS)

    def shot(self, case_id: str) -> str:
        name = f"{case_id}.png"
        try:
            self.d.save_screenshot(str(self.shots / name))
            return name
        except Exception:  # noqa: BLE001
            return ""

    def find(self, target: str, typing: bool = False):
        from selenium.webdriver.common.by import By

        t = target.strip()
        if t[:1] in "#.[" or ">" in t or (t.split("[")[0].isalpha() and "[" in t):
            els = self.d.find_elements(By.CSS_SELECTOR, t)
        else:
            q = t.replace('"', "'")
            if typing:
                xp = (f'//input[@placeholder="{q}" or @name="{q}" or @id="{q}" or @aria-label="{q}"] | '
                      f'//textarea[@placeholder="{q}" or @name="{q}" or @aria-label="{q}"] | '
                      f'//label[contains(normalize-space(.), "{q}")]/following::*[self::input or self::textarea][1] | '
                      f'//label[contains(normalize-space(.), "{q}")]//*[self::input or self::textarea]')
            else:
                xp = (f'//*[self::a or self::button or @role="button" or self::input[@type="submit"]]'
                      f'[contains(normalize-space(.), "{q}") or @value="{q}" or @aria-label="{q}"]')
            els = self.d.find_elements(By.XPATH, xp)
        els = [e for e in els if e.is_displayed()]
        if not els:
            raise LookupError(f"no visible element for '{target}'")
        return els[0]


def _case(cid: str, name: str, suite: str, purpose: str, checks: str, how: list[str], expected: str, ok: bool,
          actual: str, t0: float, shot: str, kind: str) -> dict:
    return {"id": cid, "name": name, "suite": suite, "status": "passed" if ok else "failed", "time_s": round(time.time() - t0, 2),
            "message": "" if ok else actual[:600], "purpose": purpose, "checks": checks, "how": how, "expected": expected,
            "actual": actual[:800], "screenshot": shot, "kind": kind,
            "why": (f"Passed: {actual[:300]}" if ok else f"Failed: expected {expected[:200]} – got {actual[:300]}")}


class UITestAgent:
    def __init__(self) -> None:
        self.node_name = "ui_test_agent"

    # ---------------------------------------------------------------- standard checks (worker thread)
    def _standard(self, b: Browser, base: str, comp: str, start: int) -> tuple[list[dict], list[dict]]:
        cases, pages, n = [], [], start
        nxt = lambda: f"TC-UI-{n + len(cases) + 1:03d}"  # noqa: E731
        origin = urlparse(base).netloc

        t0 = time.time()
        b.open(base)
        home = b.page()
        pages.append({"path": "/", **home})
        paths = []
        for link in home["links"]:
            u = urlparse(link["href"])
            if u.netloc == origin and u.path not in paths and u.path != "/" and not u.path.endswith((".png", ".svg", ".pdf", ".zip")):
                paths.append(u.path)
        for path in ["/"] + paths[:9]:
            t0 = time.time()
            if path != "/":
                b.open(urljoin(base, path))
            info = b.page() if path != "/" else home
            if path != "/":
                pages.append({"path": path, **info})
            text = info["text"].strip()
            bad = [e for e in ERROR_TEXT if e in text]
            ok = bool(text) and not bad
            cid = nxt()
            cases.append(_case(cid, f"{comp}: page {path} renders in the browser", comp,
                               f"A user opening {path} sees the page – not a blank screen or an error page.",
                               "The page loads, its JavaScript runs and visible text appears; no error page text.",
                               [f"open {urljoin(base, path)} in headless Chrome", "wait until the page is loaded and rendered",
                                "read the visible text of the page"],
                               "visible content, no error text", ok,
                               (f"rendered '{info['title'] or 'untitled'}' with {len(text)} characters of text" if ok else
                                "blank page – nothing rendered" if not text else f"error text on the page: {bad}"),
                               t0, b.shot(cid), "page load"))
            errors = b.console_errors()
            cid = nxt()
            cases.append(_case(cid, f"{comp}: no JavaScript errors on {path}", comp,
                               f"The page {path} runs without script errors that could break features.",
                               "The browser console contains no SEVERE (error) messages after the page loaded.",
                               [f"open {urljoin(base, path)}", "read the browser console log"],
                               "0 console errors", not errors,
                               "no console errors" if not errors else f"{len(errors)} console error(s): " + " | ".join(errors[:3]),
                               time.time(), "", "console"))

        b.open(base)                                      # navigation: click the app's own links
        for link in [x for x in home["links"] if urlparse(x["href"]).netloc == origin and x["text"]][:5]:
            t0 = time.time()
            target = urlparse(link["href"]).path or "/"
            try:
                b.find(link["text"]).click()
                time.sleep(1.2)
                now = urlparse(b.d.current_url).path or "/"
                text = b.page()["text"].strip()
                ok, actual = now == target and bool(text), f"landed on {now} with {len(text)} characters of content"
            except Exception as e:  # noqa: BLE001
                ok, actual = False, f"could not click the link: {e}"[:300]
            cid = nxt()
            cases.append(_case(cid, f"{comp}: navigation link '{link['text']}' opens {target}", comp,
                               f"A user can reach {target} by clicking '{link['text']}'.",
                               "Clicking the link changes the browser to the linked page and that page shows content.",
                               [f"open {base}", f"click the link '{link['text']}'", "read the new URL and page text"],
                               f"URL path {target} with content", ok, actual, t0, b.shot(cid), "navigation"))
            b.open(base)

        for pg in [p for p in pages if p["forms"] or len(p["inputs"]) >= 2][:3]:   # forms: fill + submit
            t0 = time.time()
            url = urljoin(base, pg["path"])
            b.open(url)
            filled, steps = [], [f"open {url}"]
            try:
                from selenium.webdriver.common.by import By

                for el in [e for e in b.d.find_elements(By.CSS_SELECTOR, "input, textarea") if e.is_displayed()][:8]:
                    kind = (el.get_attribute("type") or "text").lower()
                    if kind in ("hidden", "submit", "button", "checkbox", "radio", "file"):
                        continue
                    value = SAMPLE.get(kind, "CIP test")
                    el.clear()
                    el.send_keys(value)
                    name = el.get_attribute("name") or el.get_attribute("placeholder") or kind
                    filled.append(name)
                    steps.append(f"type '{value}' into '{name}'")
                before = b.console_errors()
                btn = b.d.find_elements(By.CSS_SELECTOR, "form button[type=submit], form input[type=submit], form button, button[type=submit]")
                btn = [x for x in btn if x.is_displayed()]
                if btn:
                    steps.append(f"click '{(btn[0].text or btn[0].get_attribute('value') or 'submit').strip()}'")
                    btn[0].click()
                    time.sleep(1.5)
                after = [e for e in b.console_errors() if e not in before]
                text = b.page()["text"].strip()
                bad = [e for e in ERROR_TEXT if e in text]
                ok = bool(text) and not bad and not after
                actual = (f"after submit the app shows {len(text)} characters at {urlparse(b.d.current_url).path}"
                          + (f"; message: '{text[:120]}'" if len(text) < 400 else "")) if ok else \
                    (f"error page after submit: {bad}" if bad else f"console errors after submit: {after[:2]}" if after else "blank page after submit")
            except Exception as e:  # noqa: BLE001
                ok, actual = False, f"could not fill / submit the form: {e}"[:300]
            cid = nxt()
            cases.append(_case(cid, f"{comp}: form on {pg['path']} can be filled and submitted", comp,
                               f"A user can use the form on {pg['path']} without the app breaking.",
                               "Fields accept input, the submit button works, and the app still renders afterwards "
                               "(a validation message is fine) with no new console errors.",
                               steps, "page still renders, no error page, no new console errors", ok, actual, t0, b.shot(cid), "form"))
        return cases, pages

    # ---------------------------------------------------------------- AI journeys (worker thread)
    def _journeys(self, b: Browser, base: str, comp: str, journeys: list[UIJourney], start: int) -> list[dict]:
        cases = []
        for i, j in enumerate(journeys[:6]):
            t0, steps, ok, actual = time.time(), [], True, ""
            try:
                for st in j.steps[:12]:
                    if st.action == "open":
                        b.open(urljoin(base, st.target or "/"))
                        steps.append(f"open {st.target or '/'}")
                    elif st.action == "click":
                        b.find(st.target).click()
                        time.sleep(1.0)
                        steps.append(f"click '{st.target}'")
                    elif st.action == "type":
                        el = b.find(st.target, typing=True)
                        el.clear()
                        el.send_keys(st.value)
                        steps.append(f"type '{st.value}' into '{st.target}'")
                    elif st.action == "expect_text":
                        steps.append(f"expect to see '{st.value}'")
                        end = time.time() + 5
                        while st.value.lower() not in b.page()["text"].lower() and time.time() < end:
                            time.sleep(0.4)
                        if st.value.lower() not in b.page()["text"].lower():
                            ok, actual = False, f"'{st.value}' was not visible at {urlparse(b.d.current_url).path}"
                            break
                    elif st.action == "expect_url":
                        steps.append(f"expect the URL to contain '{st.target}'")
                        if st.target not in b.d.current_url:
                            ok, actual = False, f"URL was {urlparse(b.d.current_url).path}, expected '{st.target}'"
                            break
                actual = actual or f"all {len(steps)} steps worked, ended on {urlparse(b.d.current_url).path}"
            except Exception as e:  # noqa: BLE001
                ok, actual = False, f"step {len(steps) + 1} failed: {e}"[:300]
            cid = f"TC-UI-{start + i + 1:03d}"
            expected = "; ".join(f"'{s.value}' visible" for s in j.steps if s.action == "expect_text") or "every step succeeds"
            cases.append(_case(cid, f"{comp}: journey – {j.title}", comp, j.purpose,
                               "Each step of the journey works in the real browser and the expected text / URL appears.",
                               steps, expected, ok, actual, t0, b.shot(cid), "AI journey"))
        return cases

    async def run(self, state: PipelineState, config: RunnableConfig) -> PipelineState:
        task_id, t0 = state["task_id"], time.time()
        dep, opts = state.get("deploy") or {}, state.get("options") or {}
        running = [s for s in dep.get("services", []) if s["status"] == "passed" and s.get("url")]
        up = []
        for s in running:                                 # the component kind is only a hint – look at what is served
            ui = await find_ui(s["url"])
            await emit(task_id, self.node_name, StreamStatus.PROGRESS,
                       f"{s['component']}: user-facing UI at {ui}" if ui else f"{s['component']}: no HTML UI (API only) at {s['url']}")
            if ui:
                up.append({**s, "url": ui})
        done = {"step_index": state["step_index"] + 1}

        async def finish(status: str, msg: str, cases: list, gate: dict | None) -> dict:
            """gate None = the UI tests could not run on this machine (tool missing): skipped, no gate, no FAIL."""
            if opts.get("remove_after_ui") and dep.get("network"):
                await docker_client().call_tool("docker_remove", {"names": [f"{dep['network']}-{s['component']}" for s in dep.get("services", [])],
                                                                  "network": dep["network"]})
            await emit(task_id, self.node_name, StreamStatus.END if status == "passed" else StreamStatus.SKIPPED
                       if status in ("skipped", "blocked") else StreamStatus.ERROR, msg)
            steps = {"ui_tests": step_record("ui_tests", "UI browser tests", "ui tests", status, msg, items=cases,
                                             item_type="tests", started=t0,
                                             summary={"browser": "headless Chrome (Selenium)", "tests": len(cases),
                                                      "passed": sum(c["status"] == "passed" for c in cases)})}
            if gate is None:
                return {**done, "steps": steps}
            return {**done, "gates": {"ui": gate},
                    "steps": {**steps,
                              "ui_gate": step_record("ui_gate", "UI gate", "ui tests", "passed" if gate["passed"] else
                                                     ("blocked" if gate.get("blocked") else "failed"),
                                                     gate.get("blocked") or "; ".join(f"{c['name']} = {c['actual']} (needs {c['required']})"
                                                                                      for c in gate["checks"] if not c["passed"]) or "all checks passed",
                                                     items=gate["checks"], item_type="checks")}}

        if not running:
            why = "nothing is running in dev – see the deploy step"
            return await finish("blocked", why, [], ui_gate([], blocked=why))
        if not up:
            return await finish("skipped", "SKIPPED – API only: no user-facing UI (Swagger / ReDoc pages are not a UI)", [], None)
        try:
            driver = await asyncio.to_thread(_driver)
        except Exception as e:  # noqa: BLE001
            why = ("SKIPPED – Selenium is not installed in the API's Python: run `pip install -r requirements.txt` in cip-api "
                   "and restart the API" if isinstance(e, ModuleNotFoundError) else
                   f"SKIPPED – Chrome could not be started ({str(e).splitlines()[0][:200]}): install Google Chrome; Selenium "
                   "downloads the matching driver (or set chrome_binary / chromedriver_path in .env)")
            return await finish("skipped", why, [], None)
        shots = Path(state["run_dir"]) / "ui-screenshots"
        shutil.rmtree(shots, ignore_errors=True)
        shots.mkdir(parents=True, exist_ok=True)
        b, cases = Browser(driver, shots), []
        llm = await LLMProvider().get_llm(state.get("provider"))
        try:
            for s in up:
                await emit(task_id, self.node_name, StreamStatus.START, f"Browser tests of {s['component']} at {s['url']}")
                std, pages = await asyncio.to_thread(self._standard, b, s["url"], s["component"], len(cases))
                cases += std
                if llm and pages:
                    summary = "\n\n".join(f"PAGE {p['path']} – title '{p['title']}'\nvisible text: {p['text'][:700]}\n"
                                          f"inputs: {p['inputs']}\nbuttons: {p['buttons']}\n"
                                          f"links: {[x['text'] + ' -> ' + urlparse(x['href']).path for x in p['links'][:15]]}"
                                          for p in pages[:5])
                    j = await ask_structured(llm, UIJourneys,
                                             "You are a QA engineer writing browser tests. From the real pages below write up to 5 "
                                             "short user journeys a real user would do (navigate, search, fill a form, open an item). "
                                             "Use only links, buttons, labels and texts that appear below; targets for click/type are "
                                             "the visible text / label / placeholder. End each journey with expect_text or expect_url "
                                             "that proves it worked. Do not use real credentials.", summary)
                    if j and j.journeys:
                        cases += await asyncio.to_thread(self._journeys, b, s["url"], s["component"], j.journeys, len(cases))
                for c in cases:
                    if c["suite"] == s["component"]:
                        await emit(task_id, self.node_name, StreamStatus.PROGRESS, f"{c['id']} {c['status'].upper()} {c['name']}")
        finally:
            await asyncio.to_thread(driver.quit)
        gate = ui_gate(cases)
        passed = sum(c["status"] == "passed" for c in cases)
        return await finish("passed" if cases else "failed",           # failed checks colour the ⓘ
                            f"{passed}/{len(cases)} browser checks passed · gate {'PASS' if gate['passed'] else 'FAIL'}", cases, gate)
