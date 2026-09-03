# -*- coding: utf-8 -*-
"""הפקת פליירים לקבוצות ולו"ז צל כ-PDF/PNG מתוך קובץ השבת.

    python3 tools/export_pdf.py 2026-09-04
    python3 tools/export_pdf.py 2026-09-04 --only shadow

הנתונים נקראים מ-shabbatot/<תאריך>.xlsx — רק תאים סטטיים, כך שגם עריכות ידניות
שנעשו באקסל משתקפות בפלייר. הערכים הנגזרים (שעות הלו"ז, רשימת החניכים, הקטגוריה)
מחושבים כאן מחדש לפי אותם כללים שבחוברת.

הרינדור נעשה ב-Chromium שכבר מותקן בסביבה (--print-to-pdf / --screenshot).
"""
import argparse
import base64
import csv
import html
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date as date_cls, datetime, time, timedelta
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
    "chromium", "chromium-browser", "google-chrome",
]

WINDOW_ORDER = ["חמישי", "שישי", "שבת", "מוצאי שבת"]
SPLIT_THRESHOLD = 0.75   # מתחת לזה — מפצלים את הפלייר לתת-קבוצות

# ערכות צבע — תואמות ל-THEMES שבחוברת, עם גוון כהה לכותרות
THEMES = {
    "ורוד":  {"strong": "#E87CA8", "mid": "#F6BFD5", "soft": "#FDEEF4", "ink": "#7A2647", "deco": "sparkles"},
    "ים":    {"strong": "#4E90C9", "mid": "#B3D4EF", "soft": "#EAF3FB", "ink": "#1C4468", "deco": "waves"},
    "ספארי": {"strong": "#DB9A3C", "mid": "#F3D3A0", "soft": "#FDF1DF", "ink": "#6E4410", "deco": "sun"},
    "שדה":   {"strong": "#6BA84F", "mid": "#C6E2B7", "soft": "#EDF6E7", "ink": "#2F5220", "deco": "flowers"},
    "סגול":  {"strong": "#8B6FC7", "mid": "#D3C6EE", "soft": "#F1EBFB", "ink": "#3E2C68", "deco": "sparkles"},
    "ירוק":  {"strong": "#43A98C", "mid": "#B7E4D6", "soft": "#E7F7F2", "ink": "#14503F", "deco": "waves"},
}
DEFAULT_THEME = THEMES["ים"]

DECO = {
    "sparkles": '<path d="M50 6 L57 43 L94 50 L57 57 L50 94 L43 57 L6 50 L43 43 Z"/>',
    "waves": '<path d="M2 60 q16 -18 32 0 t32 0 t32 0" fill="none" stroke="currentColor" '
             'stroke-width="7" stroke-linecap="round"/>'
             '<path d="M2 82 q16 -18 32 0 t32 0 t32 0" fill="none" stroke="currentColor" '
             'stroke-width="7" stroke-linecap="round"/>',
    "sun": '<circle cx="50" cy="50" r="24"/>'
           '<g stroke="currentColor" stroke-width="7" stroke-linecap="round">'
           '<path d="M50 4v14M50 82v14M4 50h14M82 50h14M17 17l10 10M73 73l10 10M83 17L73 27M27 73L17 83"/></g>',
    "flowers": '<g><circle cx="50" cy="28" r="15"/><circle cx="28" cy="52" r="15"/>'
               '<circle cx="72" cy="52" r="15"/><circle cx="50" cy="74" r="15"/></g>',
}


# ---------------------------------------------------------------------------
# קריאת קובץ השבת
# ---------------------------------------------------------------------------
def cell(ws, row, col):
    value = ws.cell(row=row, column=col).value
    if isinstance(value, str):
        value = value.strip()
    return value or None


def read_workbook(path):
    wb = load_workbook(path, data_only=False)
    zm, st = wb["זמנים"], wb["הגדרות"]

    shabbat_date = st["B4"].value
    if isinstance(shabbat_date, datetime):
        shabbat_date = shabbat_date.date()

    parasha = candle = havdalah = None
    for r in range(3, zm.max_row + 1):
        value = cell(zm, r, 1)
        if isinstance(value, datetime):
            value = value.date()
        if value == shabbat_date:
            parasha = cell(zm, r, 2)
            candle, havdalah = cell(zm, r, 3), cell(zm, r, 4)
            break
    candle = st["B8"].value or candle
    havdalah = st["B9"].value or havdalah

    places = {key: cell(st, row, 2) for key, row in
              (("קבלת שבת ישראלית", 14), ("קידוש", 15), ("חבורות", 16), ("טיש", 17),
               ("חבורה", 18), ("סעודה שלישית", 19))}
    staff = {key: cell(st, row, 2) for key, row in
             (("טיש", 22), ("חבורה", 23), ("כריכה", 24))}

    groups = []
    gr = wb["קבוצות"]
    for r in range(3, gr.max_row + 1):
        name = cell(gr, r, 1)
        if name:
            groups.append({"name": name, "leader": cell(gr, r, 2),
                           "parent": cell(gr, r, 3), "theme": cell(gr, r, 5) or "ים",
                           "members": []})

    students = wb["חניכים"]
    by_name = {g["name"]: g for g in groups}
    for r in range(3, students.max_row + 1):
        name, group = cell(students, r, 1), cell(students, r, 2)
        if name and group in by_name:
            by_name[group]["members"].append(name)

    categories = {}
    tasks_sheet = wb["מאגר משימות"]
    for r in range(3, tasks_sheet.max_row + 1):
        task, category = cell(tasks_sheet, r, 4), cell(tasks_sheet, r, 1)
        if task:
            categories[task] = category

    assignments = []
    asg = wb["שיבוץ"]
    for r in range(3, asg.max_row + 1):
        task = cell(asg, r, 4)
        if not task:
            continue
        hour = asg.cell(row=r, column=3).value
        if isinstance(hour, datetime):
            hour = hour.time()
        assignments.append({
            "group": cell(asg, r, 1), "window": cell(asg, r, 2), "hour": hour,
            "task": task, "details": cell(asg, r, 6), "anchor": cell(asg, r, 7),
            "category": categories.get(task, ""),
        })

    for g in groups:
        g["label"] = g["name"].split(" · ")[-1] if " · " in g["name"] else g["name"]

    return {"date": shabbat_date, "parasha": parasha, "candle": candle,
            "havdalah": havdalah, "places": places, "staff": staff,
            "groups": groups, "assignments": assignments}


# ---------------------------------------------------------------------------
# גזירת הלו"ז — אותם כללים שבנוסחאות החוברת
# ---------------------------------------------------------------------------
def _mins(value):
    return value.hour * 60 + value.minute


def _time(total):
    return time((total // 60) % 24, total % 60)


def schedule(data):
    candle, havdalah = data["candle"], data["havdalah"]
    if not (candle and havdalah):
        return []
    c, h = _mins(candle), _mins(havdalah)
    kabalat = c + 15
    meal = max(kabalat + 90, _mins(time(18, 30)))
    places, staff = data["places"], data["staff"]
    rows = [
        ("שישי", _time(c - 60), "קבלת שבת ישראלית", places["קבלת שבת ישראלית"], None),
        ("שישי", _time(c), "כניסת שבת", None, None),
        ("שישי", _time(kabalat), "קבלת שבת וערבית", "בית מיכאל", None),
        ("שישי", _time(meal), "סעודת שבת", "חדר אוכל", None),
        ("שישי", _time(meal + 90), "טיש עם איש צוות", places["טיש"], staff["טיש"]),
        ("שבת", time(11, 0), "קידוש", places["קידוש"], None),
        ("שבת", time(11, 45), "חבורות חניכים", places["חבורות"], None),
        ("שבת", time(12, 30), "ארוחת צהריים", "חדר אוכל", None),
        ("שבת", time(15, 0), "חבורה עם איש צוות", places["חבורה"], staff["חבורה"]),
        ("שבת", _time(h - 90), "סעודה שלישית", places["סעודה שלישית"], None),
        ("שבת", _time(h), "הבדלה", None, None),
        ("מוצאי שבת", _time(h + 10), "ניקיונות וארגון הקמפוס", "הקמפוס", None),
        ("מוצאי שבת", _time(-(-(h + 120) // 30) * 30), "כריכה לכריכה", None, staff["כריכה"]),
    ]
    return [{"window": w, "hour": t, "name": n, "place": p, "staff": s}
            for w, t, n, p, s in rows]


# ---------------------------------------------------------------------------
# עזרי תצוגה
# ---------------------------------------------------------------------------
def hhmm(value):
    return "{:02d}:{:02d}".format(value.hour, value.minute) if value else ""


def esc(value):
    return html.escape(str(value)) if value else ""


def hebrew_date_range(d):
    return "{}-{}.{}".format(d.day, (d + timedelta(days=1)).day, d.month)


def font_face_css():
    faces = []
    for family in ("Heebo", "Rubik"):
        for subset in ("hebrew", "latin"):
            path = FONTS / "{}-{}.woff2".format(family, subset)
            if not path.exists():
                continue
            data = base64.b64encode(path.read_bytes()).decode()
            faces.append(
                "@font-face{{font-family:'{f}';font-style:normal;font-weight:100 900;"
                "src:url(data:font/woff2;base64,{d}) format('woff2');}}".format(f=family, d=data))
    return "\n".join(faces)


BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:0}
body{font-family:'Heebo',sans-serif;direction:rtl;color:#25303B;
     -webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{width:210mm;height:297mm;position:relative;overflow:hidden;page-break-after:always}
.page:last-child{page-break-after:auto}
h1,h2,h3{font-family:'Rubik',sans-serif}
"""

FLYER_CSS = """
.page{padding:11mm 10mm 9mm}
.inner{transform-origin:top center;transform:scale(var(--fit,1))}
.frame{position:absolute;inset:5mm;border:2.5px solid var(--mid);border-radius:10mm;pointer-events:none}
.frame::after{content:'';position:absolute;inset:2.5mm;border:1px solid var(--mid);
              border-radius:8mm;opacity:.55}
.deco{position:absolute;color:var(--mid);fill:var(--mid);opacity:.42;pointer-events:none}
.d1{top:7mm;left:9mm;width:22mm;height:22mm}
.d2{bottom:7mm;right:9mm;width:26mm;height:26mm;opacity:.3}
.d3{bottom:26mm;left:12mm;width:14mm;height:14mm;opacity:.25}
header{text-align:center;position:relative;z-index:1;padding-top:2mm}
h1{font-size:33pt;font-weight:700;color:var(--ink);line-height:1.05}
.when{margin-top:2.5mm;font-size:12.5pt;color:var(--ink);opacity:.8;font-weight:500}
.meta{margin:4mm auto 0;display:flex;gap:4mm;justify-content:center;flex-wrap:wrap}
.chip{background:var(--strong);color:#fff;border-radius:99px;padding:1.6mm 6mm;
      font-size:11pt;font-weight:700;font-family:'Rubik',sans-serif}
.chip.ghost{background:#fff;color:var(--ink);border:2px solid var(--mid)}
.members{margin:5mm 0 0;background:var(--soft);border:1.5px solid var(--mid);border-radius:5mm;
         padding:4mm 6mm;text-align:center;font-size:11.5pt;line-height:1.75;font-weight:500}
.members b{display:block;font-size:9.5pt;letter-spacing:.06em;color:var(--ink);opacity:.65;
           margin-bottom:1.5mm;font-family:'Rubik',sans-serif}
.team{margin:0 0 4mm;border:1.5px solid var(--mid);border-radius:4mm;overflow:hidden}
.team > h3{background:var(--mid);color:var(--ink);font-size:12.5pt;padding:1.6mm 5mm;
           display:flex;justify-content:space-between;align-items:baseline}
.team > h3 span{font-size:9.5pt;font-weight:400;opacity:.8;font-family:'Heebo',sans-serif}
.team .who{padding:2.2mm 5mm;font-size:10.5pt;font-weight:500;background:var(--soft);
           line-height:1.6}
.team .jobs{padding:1.5mm 3mm 2.5mm}
.strip{margin:4mm 0 0;display:flex;justify-content:space-between;gap:1.5mm;
       border-top:1.5px dashed var(--mid);border-bottom:1.5px dashed var(--mid);padding:2.5mm 0}
.strip div{text-align:center;flex:1}
.strip span{display:block;font-size:8.5pt;color:#6B7280}
.strip strong{font-size:13pt;color:var(--ink);font-family:'Rubik',sans-serif}
main{margin-top:4mm;flex:1;position:relative;z-index:1}
.day{margin-bottom:3.5mm}
.day > h2{font-size:14pt;color:#fff;background:var(--strong);border-radius:99px;
          display:inline-block;padding:1mm 7mm;margin-bottom:2.5mm}
.task{display:flex;gap:3mm;align-items:flex-start;padding:2.2mm 3mm;border-radius:3mm;
      border-right:4px solid var(--mid)}
.task:nth-child(even){background:var(--soft)}
.hour{min-width:15mm;font-family:'Rubik',sans-serif;font-weight:700;font-size:11.5pt;
      color:var(--ink);text-align:center;padding-top:.3mm}
.hour.none{color:var(--mid)}
.body{flex:1}
.body .t{font-size:11.5pt;font-weight:500;line-height:1.45}
.body .d{font-size:9.5pt;color:#5A6572;margin-top:.6mm;line-height:1.4}
.tag{font-size:8pt;color:var(--ink);background:#fff;border:1px solid var(--mid);
     border-radius:99px;padding:.4mm 2.5mm;white-space:nowrap;margin-top:.8mm}
footer{margin-top:6mm;text-align:center;font-size:9pt;color:#8A94A0}
.empty{padding:6mm;text-align:center;color:#8A94A0;font-size:11pt;border:1.5px dashed var(--mid);
       border-radius:4mm}
"""


# מתאים את תוכן הפלייר לעמוד אחד: אם הוא גולש — מכווץ אותו במעט לפני ההדפסה.
MEASURE_SCRIPT = """<script>
(function(){
  function report(){
    var page = document.querySelector('.page');
    var inner = document.querySelector('.inner');
    var cs = getComputedStyle(page);
    var avail = page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    document.title = 'FIT:' + (avail / inner.getBoundingClientRect().height);
  }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""


def deco_svg(kind, css_class):
    return ('<svg class="deco {c}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">{p}</svg>'
            .format(c=css_class, p=DECO.get(kind, DECO["sparkles"])))


def strip_items(events):
    keep = ["כניסת שבת", "סעודת שבת", "קידוש", "ארוחת צהריים", "הבדלה"]
    labels = {"כניסת שבת": "כניסת שבת", "סעודת שבת": "סעודה", "קידוש": "קידוש",
              "ארוחת צהריים": "צהריים", "הבדלה": "הבדלה"}
    by_name = {e["name"]: e for e in events}
    return [(labels[n], hhmm(by_name[n]["hour"])) for n in keep if n in by_name]


def task_rows_html(rows):
    out = []
    for window in WINDOW_ORDER:
        items = [a for a in rows if a["window"] == window]
        if not items:
            continue
        tasks = []
        for item in items:
            hour = hhmm(item["hour"])
            tasks.append(
                '<div class="task"><div class="hour {cls}">{hour}</div><div class="body">'
                '<div class="t">{task}</div>{details}</div>'
                '<div class="tag">{tag}</div></div>'.format(
                    cls="" if hour else "none", hour=hour or "", task=esc(item["task"]),
                    details='<div class="d">{}</div>'.format(esc(item["details"]))
                            if item["details"] else "",
                    tag=esc(item["category"] or "")))
        out.append('<section class="day"><h2>{}</h2>{}</section>'.format(
            esc(window), "".join(tasks)))
    return "".join(out)


def flyer_html(bundle, data, events):
    """פלייר לקבוצת אם אחת, עם מקטע לכל תת-קבוצה."""
    theme = THEMES.get(bundle["theme"], DEFAULT_THEME)
    single = len(bundle["teams"]) == 1
    strip = "".join('<div><span>{}</span><strong>{}</strong></div>'.format(esc(l), esc(t))
                    for l, t in strip_items(events))

    if single:
        team = bundle["teams"][0]
        body = ('<div class="members"><b>חניכי הקבוצה · {n}</b>{who}</div>'
                '<div class="strip">{strip}</div><main>{days}</main>').format(
            n=len(team["members"]), who=esc(", ".join(team["members"])) or "—",
            strip=strip, days=task_rows_html(team["tasks"]) or
                  '<div class="empty">אין עדיין משימות משובצות</div>')
    else:
        sections = []
        for team in bundle["teams"]:
            jobs = task_rows_html(team["tasks"])
            sections.append(
                '<div class="team"><h3>{label}{leader}</h3>'
                '<div class="who">{who}</div>{jobs}</div>'.format(
                    label=esc(team["label"]),
                    leader='<span>מוביל/ה: {}</span>'.format(esc(team["leader"]))
                           if team["leader"] else "",
                    who=esc(", ".join(team["members"])) or "—",
                    jobs='<div class="jobs">{}</div>'.format(jobs) if jobs else ""))
        body = '<div class="strip">{}</div><main>{}</main>'.format(strip, "".join(sections))

    total = sum(len(t["members"]) for t in bundle["teams"])
    chips = ['<div class="chip">{} חניכים</div>'.format(total)]
    if single and bundle["teams"][0]["leader"]:
        chips.append('<div class="chip ghost">מוביל/ה: {}</div>'.format(
            esc(bundle["teams"][0]["leader"])))
    elif not single:
        chips.append('<div class="chip ghost">{} תת-קבוצות</div>'.format(len(bundle["teams"])))

    when = "שבת {}".format(hebrew_date_range(data["date"])) if data["date"] else "שבת"
    if data["parasha"]:
        when += " · פרשת {}".format(data["parasha"])

    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{flyer}
:root{{--strong:{strong};--mid:{mid};--soft:{soft};--ink:{ink};--fit:{fitv}}}
body{{background:linear-gradient(180deg,{soft} 0%,#fff 42%)}}</style></head><body>
<div class="page"><div class="frame"></div>{d1}{d2}{d3}
<div class="inner">
<header><h1>{title}</h1><div class="when">{when}</div>
<div class="meta">{chips}</div></header>
{body}
<footer>מדרשת עין פרת · הכנת שבת</footer>
</div>
</div>{fit}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, flyer=FLYER_CSS,
        fit=MEASURE_SCRIPT if bundle.get("measure") else "", fitv=bundle.get("fit", 1.0),
        strong=theme["strong"], mid=theme["mid"], soft=theme["soft"], ink=theme["ink"],
        d1=deco_svg(theme["deco"], "d1"), d2=deco_svg(theme["deco"], "d2"),
        d3=deco_svg(theme["deco"], "d3"),
        title=esc(bundle["title"]), when=esc(when), chips="".join(chips), body=body)


def bundles_from(data):
    """מקבץ את קבוצות העלה לפי קבוצת אם — פלייר אחד לכל אם."""
    order, bundles = [], {}
    for group in data["groups"]:
        parent = group.get("parent") or group["name"]
        if parent not in bundles:
            order.append(parent)
            bundles[parent] = {"title": parent, "theme": group["theme"], "teams": []}
        bundles[parent]["teams"].append({
            "label": group["label"], "leader": group["leader"],
            "members": group["members"],
            "tasks": [a for a in data["assignments"] if a["group"] == group["name"]],
        })
    return [bundles[name] for name in order]


SHADOW_CSS = """
.sheet{width:210mm;padding:12mm 11mm 14mm}
thead{display:table-header-group}
tr{page-break-inside:avoid;break-inside:avoid}
h1{font-size:24pt;color:#1F3A56;text-align:center}
.when{text-align:center;font-size:12pt;color:#5A6572;margin-top:1.5mm;font-weight:500}
.cover{margin:4mm auto 5mm;text-align:center;font-size:10.5pt;font-weight:700;
       background:#EDF1F6;border:1px solid #C9CFD8;border-radius:99px;padding:2mm 6mm;
       display:table}
.cover.warn{background:#FCE3C6;border-color:#E8A33D;color:#8A4B00}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th{background:#2E5C8A;color:#fff;font-family:'Rubik',sans-serif;font-size:10.5pt;
   padding:2mm;border:1px solid #2E5C8A}
td{border:1px solid #C9CFD8;padding:2mm 2.5mm;vertical-align:top;font-size:10pt;line-height:1.45}
td.hour{width:16mm;text-align:center;font-family:'Rubik',sans-serif;font-weight:700;
        font-size:11pt;color:#1F3A56}
td.event{width:44mm;font-weight:700;background:#F4F7FA}
td.event.pre{background:#F7F9FC;color:#5A6572}
td.event.loose{background:#FCE3C6;color:#8A4B00}
tr.blank td.lines{color:#AEB6BF}
.line{padding:.5mm 0}
.line + .line{border-top:1px dashed #DCE2E8}
footer{margin-top:5mm;text-align:center;font-size:8.5pt;color:#8A94A0}
"""

# ארבעה עוגנים שלפני השבת, ואז אירועי הלו"ז לפי סדר הופעתם
PRE_ANCHORS = ["חמישי — הכנות", "שישי — ארוחת בוקר", "שישי — הכנות ועבודה",
               "שישי — ארוחת צהריים"]
NO_ANCHOR = "(ללא עוגן)"


def shadow_line(item):
    parts = []
    if item["hour"]:
        parts.append(hhmm(item["hour"]) + " · ")
    parts.append(esc(item["task"]))
    if item["group"]:
        parts.append(" — <b>{}</b>".format(esc(item["group"])))
    if item["details"]:
        parts.append(' <span style="color:#6B7280">({})</span>'.format(esc(item["details"])))
    return "".join(parts)


def shadow_html(data, events):
    by_anchor = {}
    for item in data["assignments"]:
        by_anchor.setdefault(item["anchor"] or NO_ANCHOR, []).append(item)

    rows = []
    order = PRE_ANCHORS + [e["name"] for e in events] + [NO_ANCHOR]
    hours = {e["name"]: hhmm(e["hour"]) for e in events}
    for name in order:
        items = by_anchor.get(name, [])
        kind = "pre" if name in PRE_ANCHORS else ("loose" if name == NO_ANCHOR else "")
        if name == NO_ANCHOR and not items:
            continue
        lines = "".join('<div class="line">{}</div>'.format(shadow_line(i)) for i in items)
        rows.append(
            '<tr class="{blank}"><td class="hour">{hour}</td>'
            '<td class="event {kind}">{name}</td>'
            '<td class="lines">{lines}</td></tr>'.format(
                blank="" if items else "blank", hour=hours.get(name, ""),
                kind=kind, name=esc(name), lines=lines or "&nbsp;"))

    total = len(data["assignments"])
    loose = len(by_anchor.get(NO_ANCHOR, []))
    cover = "משימות בשיבוץ: {} · עוגנו: {} · ללא עוגן: {}{}".format(
        total, total - loose, loose,
        "  ✔ הכל מופיע כאן" if loose == 0 else "  ⚠ ראו «ללא עוגן» בתחתית")

    when = "שבת {}".format(hebrew_date_range(data["date"])) if data["date"] else ""
    if data["parasha"]:
        when += " · פרשת {}".format(data["parasha"])
    if data["candle"] and data["havdalah"]:
        when += " · כניסה {} · צאה {}".format(hhmm(data["candle"]), hhmm(data["havdalah"]))

    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}</style></head><body><div class="sheet">
<h1>לו"ז צל — מי עושה מה ומתי</h1><div class="when">{when}</div>
<div class="cover {warn}">{cover}</div>
<table><thead><tr><th>שעה</th><th>בלו"ז</th><th>מה קורה מאחורי הקלעים</th></tr></thead>
<tbody>{rows}</tbody></table>
<footer>מדרשת עין פרת · נוצר מגיליון «שיבוץ»</footer>
</div></body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, css=SHADOW_CSS, when=esc(when),
        warn="warn" if loose else "", cover=esc(cover), rows="".join(rows))


# ---------------------------------------------------------------------------
# רינדור ב-Chromium
# ---------------------------------------------------------------------------
def chrome_binary():
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    raise SystemExit("לא נמצא דפדפן Chromium להפקת ה-PDF")


def measure_fit(html_text):
    """מריץ את העמוד ב-Chromium ומחזיר את מקדם ההתאמה לעמוד אחד."""
    chrome = chrome_binary()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "measure.html"
        source.write_text(html_text, encoding="utf-8")
        result = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=8000", "--user-data-dir={}/profile".format(tmp),
             "--dump-dom", source.as_uri()],
            capture_output=True, timeout=180)
        match = re.search(r"FIT:([0-9.]+)", result.stdout.decode("utf-8", "replace"))
        if not match:
            return 1.0
        ratio = float(match.group(1))
        return 1.0 if ratio >= 1.03 else max(0.55, ratio * 0.97)


def render(html_text, out_pdf, out_png=None):
    chrome = chrome_binary()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "page.html"
        source.write_text(html_text, encoding="utf-8")
        # virtual-time-budget: בלעדיו Chromium מצלם לפני שסקריפט ההתאמה לעמוד רץ
        common = [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                  "--hide-scrollbars", "--virtual-time-budget=6000",
                  "--user-data-dir={}/profile".format(tmp)]
        subprocess.run(common + ["--no-pdf-header-footer", "--print-to-pdf-no-header",
                                 "--print-to-pdf={}".format(out_pdf), source.as_uri()],
                       check=True, capture_output=True, timeout=180)
        if out_png:
            subprocess.run(common + ["--window-size=794,1123", "--force-device-scale-factor=2",
                                     "--screenshot={}".format(out_png), source.as_uri()],
                           check=True, capture_output=True, timeout=180)


def main():
    ap = argparse.ArgumentParser(description="הפקת פליירים ולו\"ז צל")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-04")
    ap.add_argument("--only", choices=["flyers", "shadow"], help="להפיק רק חלק")
    ap.add_argument("--no-png", action="store_true", help="בלי תמונות PNG")
    args = ap.parse_args()

    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    source = ROOT / "shabbatot" / "{}.xlsx".format(d.isoformat())
    if not source.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם tools/new_shabbat.py".format(source))

    data = read_workbook(source)
    events = schedule(data)
    out_dir = ROOT / "shabbatot" / d.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    if args.only != "shadow":
        for bundle in bundles_from(data):
            fit = measure_fit(flyer_html(dict(bundle, measure=True), data, events))
            # קבוצה עמוסה מדי לעמוד אחד — פלייר נפרד לכל תת-קבוצה, כדי שיישאר קריא
            targets = ([bundle] if fit >= SPLIT_THRESHOLD or len(bundle["teams"]) == 1
                       else [dict(bundle, title="{} · {}".format(bundle["title"], t["label"]),
                                  teams=[t]) for t in bundle["teams"]])
            if len(targets) > 1:
                print("  ({} פוצל ל-{} פליירים — צפוף מדי לעמוד אחד)".format(
                    bundle["title"], len(targets)))
            for target in targets:
                pdf = out_dir / "{}.pdf".format(target["title"])
                png = None if args.no_png else out_dir / "{}.png".format(target["title"])
                target_fit = (fit if len(targets) == 1
                              else measure_fit(flyer_html(dict(target, measure=True), data, events)))
                render(flyer_html(dict(target, fit=target_fit), data, events), pdf, png)
                made += [x for x in (pdf, png) if x]
    if args.only != "flyers":
        pdf = out_dir / "לוז צל.pdf"
        render(shadow_html(data, events), pdf)
        made.append(pdf)

    for path in made:
        print("  {:<34} {:>8,} bytes".format(path.name, path.stat().st_size))
    print("{} קבצים ← {}/".format(len(made), out_dir.relative_to(ROOT)))


if __name__ == "__main__":
    main()
