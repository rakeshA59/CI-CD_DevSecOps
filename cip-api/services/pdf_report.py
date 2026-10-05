"""
PDF report of a run (reportlab, bundled DejaVu fonts so it looks the same on Windows).

Sections: summary (result, root cause, gates) · every step (what ran, result, commands, explanation) ·
test cases · security findings.
"""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
COLOR = {"passed": "#1f7a4d", "PASS": "#1f7a4d", "failed": "#b3261e", "FAIL": "#b3261e", "error": "#b3261e",
         "blocked": "#b3261e", "skipped": "#9a6700", "warning": "#9a6700", "INCOMPLETE": "#9a6700"}


def _font() -> tuple[str, str]:
    try:
        if "CIP" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("CIP", str(FONTS / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("CIP-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))
        return "CIP", "CIP-Bold"
    except Exception:  # noqa: BLE001
        return "Helvetica", "Helvetica-Bold"


def _t(x, n: int = 600) -> str:
    return escape(str(x if x is not None else ""))[:n].replace("\n", "<br/>")


from utils.stage_reports import stage_report  # noqa: E402


def _explain(c: dict) -> str:
    """A test case explained in the PDF: what it is about, what it checks, how, expected / actual, why it passed or failed."""
    how = c.get("how") or []
    how = "; ".join(how) if isinstance(how, list) else str(how)
    parts = [("About", c.get("purpose")), ("Checks", c.get("checks")), ("How", how),
             ("Source", f"{c['file']}:{c.get('line') or ''}" if c.get("file") else ""),
             ("Expected", c.get("expected")), ("Actual", c.get("actual")),
             ("Why", c.get("why")), ("Screenshot", f"ui-screenshots/{c['screenshot']}" if c.get("screenshot") else "")]
    text = "<br/>".join(f"<b>{k}:</b> {_t(v, 400)}" for k, v in parts if v)
    return text or _t(c.get("message", ""), 300)


def write_pdf(state: dict, out: Path) -> Path:
    body, bold = _font()
    s = {"b": ParagraphStyle("b", fontName=body, fontSize=8.5, leading=11.5),
         "h1": ParagraphStyle("h1", fontName=bold, fontSize=16, leading=20, textColor=colors.HexColor("#2b3a67"), spaceAfter=6),
         "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4)}
    W = A4[0] - 30 * mm

    def table(rows, widths):
        cells = [[c if isinstance(c, Paragraph) else Paragraph(_t(c, 900), s["b"]) for c in r] for r in rows]
        t = Table(cells, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d8d2")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f6"))]))
        return t

    def status(word):
        return Paragraph(f"<font color='{COLOR.get(word, '#555')}'><b>{_t(str(word).upper())}</b></font>", s["b"])

    rep, info = state.get("report") or {}, state.get("source_info") or {}
    story = [Paragraph("CI/CD pipeline report", s["h1"]),
             Paragraph(_t(f"{state.get('source')} · {info.get('type', '')} · {info.get('branch', '')} {info.get('commit', '')[:10]} · "
                          f"task {state.get('task_id')} · LLM {state.get('provider')}"), s["b"]), Spacer(1, 4 * mm),
             Paragraph(f"Overall: <font color='{COLOR.get(rep.get('overall'), '#555')}'><b>{_t(rep.get('overall'))}</b></font>", s["h2"])]
    story += [Paragraph(f"• {_t(x)}", s["b"]) for x in rep.get("root_cause", [])]
    if rep.get("explanation"):
        story += [Spacer(1, 2 * mm), Paragraph(_t(rep["explanation"], 2000), s["b"])]
    story += [Paragraph("Quality gates", s["h2"]),
              table([["Gate", "Result", "Checks"]] + [[k, status("PASS" if g["passed"] else "FAIL"),
                                                       g.get("blocked") or "; ".join(f"{c['name']}: {c['actual']} (needs {c['required']})" for c in g["checks"])]
                                                      for k, g in (state.get("gates") or {}).items()], [35 * mm, 18 * mm, W - 53 * mm])]
    story += [Paragraph("Components", s["h2"]),
              table([["Component", "Stack", "Build", "Tests"]] + [[c["name"] + " (" + c["path"] + ")", f"{c['language']} {c['framework']}",
                                                                   " && ".join(c["build_commands"]), c.get("test_command") or "-"]
                                                                  for c in state.get("components", [])], [35 * mm, 30 * mm, W - 110 * mm, 45 * mm])]
    if state.get("spec"):
        story += [Paragraph("Derived pipeline (guided flow)", s["h2"]),
                  table([["Stage", "Runs", "Tools / MCP", "Why"]] + [[x["title"], "yes" if x["included"] else f"no – {x['reason']}",
                                                                     f"{', '.join(x['tools'][:8])} · {x['mcp']}", x["why"]]
                                                                    for x in state["spec"]], [32 * mm, 30 * mm, 55 * mm, W - 117 * mm])]
    if state.get("answers"):
        story += [Paragraph("Questionnaire answers", s["h2"]),
                  table([["Question", "Answer"]] + [[k.replace("_", " "), ", ".join(v) if isinstance(v, list) else str(v)]
                                                    for k, v in state["answers"].items()], [60 * mm, W - 60 * mm])]
    story += [PageBreak(), Paragraph("Stage reports", s["h1"])]
    for st in (state.get("steps") or {}).values():
        r = stage_report(st)
        story += [Paragraph(f"{_t(st['name'])} {('– ' + _t(st['component'])) if st.get('component') else ''}", s["h2"]),
                  table([["Result", "Detail"], [status(st["status"]), st["message"]]], [20 * mm, W - 20 * mm]),
                  table([["", ""], ["What it did", r["what"]], ["Where", "; ".join(r["where"])], ["How", "; ".join(r["how"])],
                         ["Why", r["why"]], ["Result", r["result"]], ["Suggestions", " • ".join(r["suggestions"]) or "-"],
                         ["Blockers", " • ".join(r["blockers"]) or "none"]][1:], [25 * mm, W - 25 * mm])]
        if st.get("explanation"):
            story.append(Paragraph("<b>Agent:</b> " + _t(st["explanation"], 1500), s["b"]))
        if st.get("commands"):
            story.append(table([["Command", "Folder", "Exit"]] + [[c["command"], c["folder"], c["exit_code"]] for c in st["commands"][:15]],
                               [W - 45 * mm, 30 * mm, 15 * mm]))
        if st.get("item_type") == "tests" and st.get("items"):
            if st.get("id") == "publish_tests":     # the combined list – each case is already explained under its own stage
                story.append(table([["ID", "Test", "Result", "Message"]] + [[c.get("id"), c["name"], status(c["status"]), c.get("message", "")[:300]]
                                                                           for c in st["items"][:150]], [20 * mm, 60 * mm, 18 * mm, W - 98 * mm]))
            else:
                story.append(table([["ID", "Test", "Result", "What · checks · how · result · why"]] +
                                   [[c.get("id"), c["name"] + (f" ({c['kind']} test)" if c.get("kind") else ""), status(c["status"]),
                                     Paragraph(_explain(c), s["b"])] for c in st["items"][:150]],
                                   [20 * mm, 45 * mm, 18 * mm, W - 83 * mm]))
        if st.get("item_type") == "findings" and st.get("items"):
            story.append(table([["Severity", "Finding", "Where", "Fix"]] + [
                [f["severity"], f["title"], f"{f.get('file')}:{f.get('line') or ''}",
                 (f.get("triage") or {}).get("fix") or f.get("recommendation", "")] for f in st["items"][:60]],
                [17 * mm, W - 102 * mm, 45 * mm, 40 * mm]))
    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"CIP report {state.get('task_id')}").build(story)
    return out
