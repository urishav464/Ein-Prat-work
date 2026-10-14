# -*- coding: utf-8 -*-
"""הפקת לו"ז הצל ופלייר לכל קבוצת עבודה כ-PDF/PNG מתוך קובץ השבת.

    python3 tools/export_pdf.py 2026-09-11
    python3 tools/export_pdf.py 2026-09-11 --only shadow

הנתונים נקראים מ-shabbatot/<תאריך>.xlsx — רק תאים סטטיים («שעה» ו«אירוע» ב«לוז»,
«שמות» ב«משימות»), כך שגם עריכות שנעשו בגוגל שיטס והורדו כ-xlsx משתקפות בפלט.
הרינדור נעשה ב-Chromium שמותקן בסביבה.
"""
import argparse
import base64
import html
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_workbook as bw

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
    "chromium", "chromium-browser", "google-chrome",
]
DAY_ORDER = bw.DAY_ORDER
SCHEDULE_DAY = {"חמישי": "חמישי", "שישי": "שישי", "שבת": "שבת", "מוצאי שבת": "שבת"}   # מוצ"ש יושב בלו"ז תחת שבת


# ---------------------------------------------------------------------------
# קריאת קובץ השבת
# ---------------------------------------------------------------------------
def cell(ws, row, col):
    value = ws.cell(row=row, column=col).value
    if isinstance(value, str):
        value = value.strip()
    return value or None


def as_time(value):
    return value.time() if isinstance(value, datetime) else value


def split_names(text):
    return [n.strip() for n in (text or "").split(",") if n.strip()]


def split_dishes(text):
    """עמודת «מתכון» יכולה להחזיק כמה מנות, מופרדות ב-; (משימה שמכינה שני סלטים)."""
    return [d.strip() for d in (text or "").split(";") if d.strip()]


def read_workbook(path):
    wb = load_workbook(path)
    sched, zm = wb[bw.SH_SCHED], wb[bw.SH_ZMAN]

    shabbat_date = sched[bw.SCHED_DATE].value
    if isinstance(shabbat_date, datetime):
        shabbat_date = shabbat_date.date()
    parasha = candle = havdalah = None
    for r in range(3, zm.max_row + 1):
        value = cell(zm, r, 1)
        if isinstance(value, datetime):
            value = value.date()
        if value == shabbat_date:
            parasha, candle, havdalah = cell(zm, r, 2), as_time(cell(zm, r, 3)), as_time(cell(zm, r, 4))
            break
    title = sched[bw.SCHED_TITLE].value or ""          # «שבת סטודנטים» — ריק בקבצים ישנים

    events, day = [], None
    for r in range(bw.SCHED_FIRST_ROW, sched.max_row + 1):
        name = cell(sched, r, bw.L_EVENT)
        if not name:
            continue
        day = cell(sched, r, bw.L_DAY) or day
        events.append({"day": day, "hour": as_time(cell(sched, r, bw.L_HOUR)), "name": name,
                       "place": cell(sched, r, bw.L_PLACE), "note": cell(sched, r, bw.L_NOTE)})

    tasks = []
    ws = wb[bw.SH_TASKS]
    for r in range(bw.TASK_FIRST_ROW, ws.max_row + 1):
        task = cell(ws, r, bw.T_TASK)
        if not task:
            continue
        tasks.append({"row": r, "stage": cell(ws, r, bw.T_STAGE) or "", "day": cell(ws, r, bw.T_DAY) or "",
                      "hour": as_time(cell(ws, r, bw.T_HOUR)), "group": cell(ws, r, bw.T_GROUP), "task": task,
                      "people": cell(ws, r, bw.T_PEOPLE), "names": split_names(cell(ws, r, bw.T_NAMES)),
                      "recipe": cell(ws, r, bw.T_RECIPE), "anchor": cell(ws, r, bw.T_ANCHOR),
                      "note": cell(ws, r, bw.T_NOTE)})

    groups = []
    ws = wb[bw.SH_GROUPS]
    for r in range(bw.GROUP_FIRST_ROW, ws.max_row + 1):
        name = cell(ws, r, bw.G_NAME)
        if name:
            groups.append({"name": name, "stage": cell(ws, r, bw.G_STAGE) or "", "leader": cell(ws, r, bw.G_LEADER),
                           "members": split_names(cell(ws, r, bw.G_MEMBERS))})

    recipes = {}
    ws = wb[bw.SH_RECIPES]
    for r in range(3, ws.max_row + 1):
        dish = cell(ws, r, 2)
        if dish:
            recipes[dish] = {"kind": cell(ws, r, 1), "dish": dish, "qty": cell(ws, r, 3),
                             "ingredients": cell(ws, r, 4), "steps": cell(ws, r, 5), "note": cell(ws, r, 6)}

    return {"date": shabbat_date, "parasha": parasha, "candle": candle, "havdalah": havdalah,
            "title": str(title).strip(), "events": events, "tasks": tasks, "groups": groups, "recipes": recipes}


# ---------------------------------------------------------------------------
# עזרי תצוגה
# ---------------------------------------------------------------------------
def hhmm(value):
    return "{:02d}:{:02d}".format(value.hour, value.minute) if value else ""


def esc(value):
    return html.escape(str(value)) if value else ""


def hebrew_date_range(d):
    return "{}-{}.{}".format(d.day, (d + timedelta(days=1)).day, d.month)


def when_line(data):
    when = "שבת {}".format(hebrew_date_range(data["date"])) if data["date"] else "שבת"
    if data.get("title"):
        when = "{} · {}".format(data["title"], when)
    if data["parasha"]:
        when += " · פרשת {}".format(data["parasha"])
    if data["candle"] and data["havdalah"]:
        when += " · כניסה {} · צאה {}".format(hhmm(data["candle"]), hhmm(data["havdalah"]))
    return when


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
body{font-family:'Heebo',sans-serif;direction:rtl;color:#1F2430;background:#fff;
     -webkit-print-color-adjust:exact;print-color-adjust:exact}
.sheet{width:210mm;padding:12mm 12mm 14mm}
.fixed{height:297mm;overflow:hidden}
.inner{transform-origin:top center;transform:scale(var(--fit,1))}
h1{font-family:'Rubik',sans-serif;font-size:22pt;text-align:center;color:#1F2430}
.when{text-align:center;font-size:11pt;color:#5A6572;margin-top:1.5mm}
table{width:100%;border-collapse:collapse;table-layout:fixed;margin-top:5mm}
tr{page-break-inside:avoid;break-inside:avoid}
td,th{border:1px solid #1F2430;padding:2.2mm 3mm;vertical-align:middle;font-size:10.5pt;line-height:1.5}
th{background:#F1F3F6;font-family:'Rubik',sans-serif;font-weight:600}
footer{margin-top:6mm;text-align:center;font-size:8.5pt;color:#8A94A0}
"""

SHADOW_CSS = """
.page{width:210mm;padding:9mm 10mm 10mm;position:relative}
h1{font-size:20pt}
.when{font-size:10.5pt;margin-top:1mm}
table.grid{margin-top:3.5mm;border-collapse:collapse}
table.grid td{border:0;padding:0 0 2.6mm;vertical-align:top;font-size:9.5pt;line-height:1.36;text-align:right}
footer{margin-top:2mm}
.sec{display:flex;align-items:baseline;flex-wrap:wrap;column-gap:2.5mm;border-bottom:1.4px solid #1F2430;
     padding-bottom:.8mm;margin-bottom:1.6mm}
.sec b{font-family:'Rubik',sans-serif;font-weight:700;font-size:12.5pt}
.sec .hint{font-size:9pt;color:#5A6572}
.cols{display:flex;gap:7mm}
.col{flex:1 1 0;min-width:0}
.day + .day{margin-top:2mm}
.dh{font-family:'Rubik',sans-serif;font-weight:700;font-size:11pt;margin-bottom:.6mm}
.pt{display:grid;grid-template-columns:12.5mm 1fr;align-items:start}
.pt .t{font-family:'Rubik',sans-serif;font-size:9.5pt;padding-top:.35mm;white-space:nowrap;font-variant-numeric:tabular-nums}
.pt.du .t{color:#5A6572;font-weight:400}
.pt.ev .t{font-weight:600}
.pt .c{position:relative;border-right:1.4px solid #C9D0DA;padding:.15mm 3.2mm .3mm 0;min-height:4.8mm}
.pt .c::before{content:"";position:absolute;right:-1.55mm;top:1.6mm;width:2.4mm;height:2.4mm;border-radius:50%;
               background:#1F2430}
.pt.du .c::before{background:#fff;border:1.3px solid #8A94A0;width:1.6mm;height:1.6mm;right:-1.3mm;top:1.95mm}
.evn{font-weight:600;font-size:10pt}
.pl{color:#5A6572;font-size:9pt}
.nt{font-style:italic;color:#3A4552}
.chip{display:inline-flex;align-items:center;gap:1mm;background:var(--t);border-radius:2.2mm;
      padding:0 1.5mm 0 .4mm;margin:.2mm 0 .2mm 1mm;font-size:8.8pt;line-height:1.45;white-space:nowrap;
      vertical-align:middle}
.chip .n,.hd .n{font-family:'Rubik',sans-serif;font-weight:600;color:#fff;background:var(--c);border-radius:1.8mm;
         min-width:4.2mm;padding:0 .9mm;text-align:center;font-size:8.2pt;line-height:1.45}
.legend{margin-top:1.6mm;font-size:9pt;color:#5A6572;display:flex;flex-wrap:wrap;gap:4mm}
.lg i{display:inline-block;width:2.6mm;height:2.6mm;border-radius:.7mm;margin-left:1.2mm;vertical-align:-.2mm}
.dayhd{font-family:'Rubik',sans-serif;font-weight:700;font-size:11pt;margin:.4mm 0 1.2mm;
       display:flex;align-items:center;gap:2mm}
.dayhd small{font-family:'Heebo',sans-serif;font-weight:400;font-size:9pt;color:#5A6572}
.dayhd::after{content:"";flex:1;border-top:1px solid #D5DBE3}
.pair{display:flex;gap:2.6mm;align-items:flex-start}
.stack{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:2.6mm}
.card{font-size:9.5pt;line-height:1.36;border:1px solid #D5DBE3;border-right:1.8mm solid var(--c);border-radius:1.6mm;padding:1.1mm 2.4mm 1.3mm}
.hd{display:flex;align-items:baseline;flex-wrap:wrap;column-gap:1.6mm;row-gap:0}
.hd .n{font-size:8.6pt;min-width:4.6mm;padding:0 1mm;align-self:center;line-height:1.5}
.hd .nm{font-family:'Rubik',sans-serif;font-weight:700;font-size:11pt}
.hd .meta{font-size:9.2pt;color:#5A6572;white-space:nowrap}
.hd .meta b{color:#1F2430;font-weight:600}
.names{font-size:9.5pt;color:#1F2430;margin-top:.3mm}
.names .none{color:#A33;font-style:italic}
.route{display:grid;grid-template-columns:auto 1fr;column-gap:2mm;row-gap:.4mm;margin-top:.9mm;
       padding-top:.9mm;border-top:1px dashed #D5DBE3;align-items:start}
.pill{font-family:'Rubik',sans-serif;font-weight:600;font-size:9pt;background:var(--t);color:#1F2430;
      border-radius:1.3mm;padding:0 1.4mm;text-align:center;white-space:nowrap;line-height:1.5;margin-top:.15mm}
.pill.anchor{background:#fff;border:1px solid var(--c);font-weight:500;font-size:8.6pt;line-height:1.4}
.its{min-width:0}
.it{color:#2E3644}
.it.help{color:#5A6572}
.who{font-weight:600;color:var(--d)}
.who.note{color:#A33}
.who.note,.who.rest,.who.but{white-space:nowrap}
"""

FLYER_CSS = """
h1{font-size:26pt}
.stage{text-align:center;font-family:'Rubik',sans-serif;font-size:12pt;color:#5A6572;margin-top:1mm}
.lead{text-align:center;font-size:12pt;margin-top:3mm}
.members{margin:5mm auto 0;text-align:center;font-size:12pt;line-height:1.8;max-width:170mm}
.members b{display:block;font-family:'Rubik',sans-serif;font-size:10pt;color:#5A6572}
th.hour,td.hour{width:20mm;text-align:center;font-family:'Rubik',sans-serif;font-weight:700;font-size:12pt}
td.hour .day{display:block;font-family:'Heebo',sans-serif;font-weight:400;font-size:9pt;color:#5A6572;margin-bottom:.5mm}
td.task{font-size:12pt}
td.task .note{display:block;margin-top:1mm;font-size:9.5pt;color:#5A6572;white-space:pre-line}
th.names,td.names{width:60mm;font-size:11pt}
.empty{margin-top:8mm;text-align:center;color:#8A94A0;font-size:12pt}
.recipe{margin-top:7mm;border:1px solid #1F2430;padding:4mm 5mm;page-break-inside:avoid}
.recipe h2{font-family:'Rubik',sans-serif;font-size:15pt;display:flex;flex-wrap:wrap;gap:1mm 4mm;justify-content:space-between;align-items:baseline}
td.task .help{color:#5A6572}
.recipe h2 span{font-size:10.5pt;font-weight:400;color:#5A6572;font-family:'Heebo',sans-serif}
.recipe .cols{display:flex;gap:6mm;margin-top:2.5mm}
.recipe .col{flex:1}
.recipe .col.ing{flex:0 0 62mm}
.recipe.ing-only .col.ing{flex:1 1 auto}
.ing-grid{display:flex;gap:5mm;align-items:flex-start;margin-top:6mm}
.ing-grid .recipe{flex:1 1 0;min-width:0;margin-top:0}
.recipe.ing-only h2{font-size:13pt}
.recipe.ing-only p{font-size:10pt;line-height:1.45}
.recipe h3{font-family:'Rubik',sans-serif;font-size:10.5pt;color:#5A6572;margin-bottom:1mm}
.recipe p{font-size:10.5pt;line-height:1.5;white-space:pre-line}
.recipe p b{display:block;margin-top:1.5mm}
.recipe p b:first-child{margin-top:0}
.recipe ol{margin:0;padding-right:5mm;font-size:10.5pt;line-height:1.5}
.recipe ol li{margin-bottom:.8mm}
.recipe .note{margin-top:2mm;font-size:9.5pt;color:#5A6572}
"""


def ingredients_html(text):
    """שורה לכל מרכיב; שורה שנגמרת בנקודתיים היא כותרת משנה (לבצק / למילוי)."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        out.append("<b>{}</b>".format(esc(line)) if line.endswith(":") else esc(line))
    # <b> הוא בלוק בעצמו — ירידת השורה אחריו רק הייתה מוסיפה שורה ריקה (pre-line)
    return "\n".join(out).replace("</b>\n", "</b>") or "—"


def steps_html(text):
    steps = [s.strip() for s in (text or "").split("\n") if s.strip()]
    if not steps:
        return "<p>—</p>"
    return "<ol>{}</ol>".format("".join("<li>{}</li>".format(esc(s)) for s in steps))


def recipe_html(recipe, with_steps=False):
    """בלוק המנה על הפלייר. ברירת המחדל — מצרכים וכמות בלבד; אופן ההכנה רק לפי בקשה."""
    steps = ('<div class="col"><h3>הכנה</h3>{}</div>'.format(steps_html(recipe["steps"]))
             if with_steps else "")
    return ('<div class="recipe{cls}"><h2>{title}{qty}</h2><div class="cols">'
            '<div class="col ing">{head}<p>{ing}</p></div>'
            '{steps}</div>{note}</div>').format(
        cls="" if with_steps else " ing-only",
        head="<h3>מרכיבים</h3>" if with_steps else "",
        title=esc(recipe["dish"] if with_steps else "מצרכים — " + recipe["dish"]),
        qty='<span>כמות: {}</span>'.format(esc(recipe["qty"])) if recipe["qty"] else "",
        ing=ingredients_html(recipe["ingredients"]), steps=steps,
        note='<div class="note">{}</div>'.format(esc(recipe["note"])) if recipe["note"] else "")


def flyer_html(group, tasks, data, with_recipes=False, fit=1.0, measure=False):
    """פלייר לקבוצת עבודה אחת: משימות עם שעה ושמות, ומצרכים לכל מנה שמופיעה במשימותיה.
    `fit` < 1 מכווץ לעמוד אחד; `measure` מוסיף את סקריפט המדידה."""
    rows, last_day = [], None
    ordered = sorted(tasks, key=lambda t: (DAY_ORDER.get(t["day"], 9), t["hour"] is None,
                                           t["hour"] or datetime.min.time(), t["row"]))
    # מי שמצטרף/ת להכנה הזו מקבוצה אחרת (העזרה מבית המדרש ב-8:45) — שורה בפלייר של ההכנה
    helping = sorted((t for t in data["tasks"] if t["group"] != group["name"]
                      and t["task"] == bw.HELP_TASK.format(group["name"])),
                     key=lambda t: (t["hour"] is None, t["hour"] or datetime.min.time(), t["row"]))
    shown = sorted(ordered + helping, key=lambda t: (DAY_ORDER.get(t["day"], 9), t["hour"] is None,
                                                     t["hour"] or datetime.min.time(), t["row"]))
    multi_day = len({t["day"] for t in shown}) > 1
    timed = any(t["hour"] for t in ordered)
    for t in shown:
        names = ", ".join(t["names"]) or ("כולם" if t["people"] is None else "")
        day = ""
        if multi_day and t["day"] != last_day:
            day, last_day = '<span class="day">{}</span>'.format(esc(t["day"])), t["day"]
        hour = esc(hhmm(t["hour"]))
        if not hour and not timed:          # בלי שעה בכלל (ניקיונות מוצ"ש) — השעה של האירוע שהיא מעוגנת אליו
            ev = find_event(data["events"], t)
            if ev and ev["hour"]:
                day, hour = '<span class="day">{}</span>'.format(esc(ev["name"])), esc(hhmm(ev["hour"]))
        task = esc(t["task"]) if t in ordered else \
            '<span class="help">מצטרפים מ«{}» לעזרה</span>'.format(esc(t["group"]))
        rows.append('<tr><td class="hour">{day}{hour}</td><td class="task">{task}{note}</td>'
                    '<td class="names">{names}</td></tr>'.format(
                        day=day, hour=hour or "—", task=task,
                        note='<span class="note">{}</span>'.format(esc(t["note"])) if t["note"] and t in ordered else "",
                        names=esc(names)))
    table = ('<table><thead><tr><th class="hour">שעה</th><th>משימה</th><th class="names">מי</th></tr></thead>'
             '<tbody>{}</tbody></table>'.format("".join(rows))) if rows else \
        '<div class="empty">אין עדיין משימות לקבוצה</div>'
    dishes = []                 # המצרכים תמיד על הפלייר; אופן ההכנה רק עם --with-recipes
    for t in ordered:
        for dish in split_dishes(t["recipe"]):
            if dish in data["recipes"] and dish not in dishes:
                dishes.append(dish)
    recipes = "".join(recipe_html(data["recipes"][d], with_recipes) for d in dishes)
    if recipes and not with_recipes:        # שתי רשימות מצרכים יושבות זו לצד זו
        recipes = '<div class="ing-grid">{}</div>'.format(recipes)
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body><div class="sheet page{fixed}"><div class="inner">
<h1>{title}</h1><div class="stage">{stage}</div><div class="when">{when}</div>
{lead}
<div class="members"><b>חברי הקבוצה · {n}</b>{members}</div>
{table}{recipes}
<footer>מדרשת עין פרת</footer>
</div></div>{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, css=FLYER_CSS, title=esc(group["name"]),
        fit=fit, fixed=" fixed" if (measure or fit < 1.0) else "", script=MEASURE_SCRIPT if measure else "",
        stage=esc(group["stage"]), when=esc(when_line(data)),
        lead='<div class="lead">אחראי/ת: <b>{}</b></div>'.format(esc(group["leader"])) if group["leader"] else "",
        n=len(group["members"]), members=esc(", ".join(group["members"])) or "—", table=table, recipes=recipes)


# ---------------------------------------------------------------------------
# לו"ז צל
# ---------------------------------------------------------------------------
def find_event(events, task):
    """האירוע שהמשימה עוגנה אליו; משימה שאין לה עוגן בלו"ז → None."""
    if not task["anchor"]:
        return None
    hits = [e for e in events if e["name"] == task["anchor"]]
    if len(hits) > 1:
        same_day = [e for e in hits if e["day"] == SCHEDULE_DAY.get(task["day"], task["day"])]
        hits = same_day or hits
    return hits[0] if hits else None


def task_event(events, task):
    """כמו find_event; בקבצים ישנים העוגן ישב בעמודת ההערה."""
    e = find_event(events, task)
    if e is None and task.get("note") and any(x["name"] == task["note"] for x in events):
        e = find_event(events, dict(task, anchor=task["note"]))
    return e


# לו"ז הצל בשני חלקים מתואמים, כמו בשם המסמך: «לו"ז שבת» — ציר זמן לכל יום, ובו ליד כל שעה שתורנות
# עובדת בה המספר שלה; «לו"ז צל» — כרטיס אחיד אחד לכל תורנות: מספר · שם · N אנשים · אחראי/ת, השמות,
# והשעות. כך תורנות שמתפרסת על כמה אירועים (הכנת ארוחת ערב 14:00→19:30) מופיעה פעם אחת ושלמה, והציר
# שומר על סדר הזמנים. ליד שעה כותבים שמות רק כשהקבוצה מתחלקת: «בלי X», שמות, או «כל השאר».
STAGE_COLORS = ["#B26B00", "#1F7A72", "#3651A3", "#8A3F86"]   # לפי bw.STAGES
OTHER_COLOR = "#5A6572"
SINGLE_LABEL = 110     # תורנות עם שורת שעה אחת — הטקסט כמעט במלואו
LINE_CHARS = 48        # שורת שעה בכרטיס חצי-רוחב, כולל השמות
MULTI_LABEL = 44       # כמה שורות שעה — רק הפסוקית הראשונה
REST = "כל השאר"


def minutes(t):
    m = t.hour * 60 + t.minute
    return m + 1440 if m < 300 else m          # לפני 05:00 — אחרי חצות


def sched_day(day):
    return SCHEDULE_DAY.get(day, day)


def day_index(day):
    return DAY_ORDER.get(sched_day(day), 9)


def stage_color(stage):
    return STAGE_COLORS[bw.STAGES.index(stage) % len(STAGE_COLORS)] if stage in bw.STAGES else OTHER_COLOR


def mix(hex_color, amount, toward):
    rgb = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(c + (toward - c) * amount) for c in rgb))


def clean_members(group, tasks):
    """חברי הקבוצה והאחראי/ת. נוסחה שלא חושבה (קבצים ישנים) אינה רשימת שמות; רשימה בעמודת
    האחראי/ת היא רשימת החברים של המבנה הישן; ואם אין — כל מי שמופיע במשימות."""
    members = list(group.get("members") or [])
    if any(m.startswith("=") for m in members):
        members = []
    leader = group.get("leader")
    if leader and "," in leader:
        members = members or split_names(leader)
        leader = None
    if not members:
        for t in tasks:
            members += [n for n in t["names"] if n not in members]
    if leader in members:                       # האחראי/ת ראשון/ה ברשימה
        members = [leader] + [m for m in members if m != leader]
    return members, leader


def short_names(members):
    """שם פרטי, ואם הוא חוזר בקבוצה (אלה גוטליב / אלה מאיר) — עם אות משם המשפחה, ואם גם זה — השם המלא."""
    def first(full):
        words = full.split()
        if len(words) > 1 and words[0].endswith("-"):        # «שי- לי»
            return words[0] + words[1]
        return words[0] if words else full
    firsts = {m: first(m) for m in members}
    count = Counter(firsts.values())
    out = {}
    for m in members:
        last = m.split()[-1] if len(m.split()) > 1 else ""
        out[m] = firsts[m] if count[firsts[m]] == 1 else ("{} {}׳".format(firsts[m], last[0]) if last else m)
    again = Counter(out.values())
    return {m: out[m] if again[out[m]] == 1 else m for m in members}


def strip_group(text, group):
    """«חלות — 10 ק"ג קמח» בכרטיס «חלות» → «10 ק"ג קמח»; משימה ששמה הוא שם הקבוצה → ריק."""
    if not group:
        return text
    if text == group or text in group:
        return ""
    for sep in (" — ", ": ", " - ", " – "):
        if text.startswith(group + sep):
            return text[len(group) + len(sep):].strip()
    return text


def ellipsize(text, limit):
    """ראש וזנב עם … באמצע («הכנסת הגסטרונומים … לתנור החימום»): הפועל והמושא נשמרים, צירוף
    סמיכות («חדר האוכל») לא נחתך, והזנב לא מתחיל באמצע צירוף (מילה ב-ה)."""
    words = text.split()
    head, rest = words[:2], words[2:]
    while rest and len(" ".join(head + rest[:1])) <= limit * 0.75 and \
            (len(" ".join(head + rest[:1])) <= limit * 0.5 or rest[0].startswith("ה")):
        head.append(rest.pop(0))
    while len(head) > 2 and len(head[-1]) <= 2:     # לא לסיים ב«של» / «את» תלויים
        rest.insert(0, head.pop())
    room, tail = limit - len(" ".join(head)), []
    while rest and len(" ".join([rest[-1]] + tail)) <= room:
        tail.insert(0, rest.pop())
    while tail and tail[0].startswith("ה"):
        rest.append(tail.pop(0))
    if not rest:
        return " ".join(head + tail)
    return " ".join(head) + (" … " + " ".join(tail) if tail else "…")


def shorten(text, limit):
    """תווית קצרה לשורת שעה (הטקסט המלא בפלייר). כמה שעות — רק הפסוקית הראשונה, בלי הרשימה שאחרי
    «:» / « — »; פעולה נוספת אחרי « · ו…» («וחיבור מיחמים») נשארת. פסוקית ארוכה מדי — עד הפסיק (…),
    או ראש וזנב; פסוקית של שתי פעולות («…, וסידור …») נשארת שלמה ונשברת לשורה נוספת."""
    if limit >= SINGLE_LABEL:
        return text if len(text) <= limit else ellipsize(text, limit)
    parts = text.split(" · ")
    first, more = parts[0], [x.strip() for x in parts[1:] if x.strip().startswith("ו")]
    cut = len(first)
    for sep in (":", " — ", " ("):
        i = first.find(sep)
        if 0 < i < cut:
            cut = i
    label = first[:cut].strip()
    if len(label) > limit + 3 and not re.search(r", ו\S", label):
        comma = label.rfind(",", 0, limit + 1)
        if comma > 0 and len(label[:comma].split()) >= 2:
            label = label[:comma] + "…"
        else:
            label = ellipsize(label, limit)
    return " · ".join([label] + more)


def join_he(names):
    names = list(names)
    return " ו".join(names) if len(names) == 2 else ", ".join(names)


def who_for_slot(tasks, members, short):
    """לכל משימה בשעה אחת — מה כתוב לידה: "" (כל הקבוצה), «בלי X», «כל השאר» או שמות קצרים, ו«חסרים N»
    כששובצו פחות מ«אנשים» (כמו האזהרה ב-shabbat.py). מחזיר [(משימה, טקסט, סוג, חסרים)]; «כל השאר» אחרון."""
    mset = set(members)
    sets = []
    for t in tasks:
        if t["names"]:
            sets.append((t, list(t["names"]), None))
        elif t["people"] and (not members or t["people"] < len(members)):
            sets.append((t, None, "טרם שובצו · {}".format(t["people"])))
        else:
            sets.append((t, [], ""))                 # בלי שמות ובלי מספר — כל הקבוצה

    # השעה מחלקת את כל הקבוצה לחלקים זרים (עזרה בחלות / בעוגת שמרים) — החלק הגדול הוא «כל השאר»
    explicit = [(t, n) for t, n, txt in sets if txt is None and set(n) != mset]
    rest_task = None
    if len(explicit) >= 2 and members:
        parts = [set(n) for _, n in explicit]
        if sum(len(p) for p in parts) == len(set().union(*parts)) and set().union(*parts) == mset:
            sizes = [len(p) for p in parts]
            big = max(sizes)
            if big >= 3:
                rest_task = explicit[max(i for i, s in enumerate(sizes) if s == big)][0]

    out = []
    for t, names, txt in sets:
        if txt is not None:
            out.append((t, txt, "note" if txt else "all"))
        elif set(names) == mset:
            out.append((t, "", "all"))
        elif t is rest_task:
            out.append((t, REST, "rest"))
        else:
            missing = [m for m in members if m not in names]
            if len(members) >= 3 and set(names) <= mset and 1 <= len(missing) <= 2 and len(missing) < len(names):
                out.append((t, "בלי " + join_he(short[m] for m in missing), "but"))
            else:
                out.append((t, ", ".join(short.get(n, n) for n in names), "names"))
    gap = lambda t: "חסרים {}".format(int(t["people"]) - len(t["names"])) \
        if t["names"] and int(t["people"] or 0) > len(t["names"]) else ""
    out = [(t, who, kind, gap(t)) for t, who, kind in out]
    out.sort(key=lambda x: x[2] == "rest")
    return out


def shadow_cards(data):
    """כרטיס לכל קבוצה שיש לה משימות, לפי סדר ההתחלה: [{name, stage, leader, members, slots, …}],
    ומשימות בלי קבוצה (הודעה כללית בציר). slot = שעה אחת בכרטיס: המשימות שלה, ומי מצטרף/ת לעזרה."""
    events = data["events"]
    groups = OrderedDict((g["name"], g) for g in data["groups"])
    by_group, loose = OrderedDict(), []
    for t in data["tasks"]:
        if t["group"]:
            by_group.setdefault(t["group"], []).append(t)
            groups.setdefault(t["group"], {"name": t["group"], "stage": t["stage"], "leader": None, "members": []})
        else:
            loose.append(t)

    cards = []
    for name, g in groups.items():
        tasks = by_group.get(name, [])
        if not tasks:
            continue
        members, leader = clean_members(g, tasks)
        short = short_names(members)
        slots = OrderedDict()

        def slot(key, day, hour, ev):
            return slots.setdefault(key, {"tasks": [], "help": [], "event": ev, "day": day, "hour": hour})

        for t in tasks:
            ev = task_event(events, t)
            day = t["day"] or (ev["day"] if ev else "")
            key = ("t", sched_day(day), t["hour"]) if t["hour"] else (("a", id(ev)) if ev else ("n", sched_day(day)))
            slot(key, day, t["hour"], ev)["tasks"].append(t)
        # מי שמצטרף/ת להכנה הזו מקבוצה אחרת (העזרה מבית המדרש ב-8:45) — שורה בכרטיס של ההכנה
        for t in data["tasks"]:
            if t["group"] != name and t["task"] == bw.HELP_TASK.format(name) and t["hour"]:
                s = slot(("t", sched_day(t["day"]), t["hour"]), t["day"], t["hour"], None)
                s["help"].append((t["group"], len(t["names"]) or t["people"] or 0))
        for key, s in slots.items():          # משימה בלי שעה — אחרי המשימות המתוזמנות של אותו עוגן
            if key[0] == "t":
                s["sort"] = (day_index(s["day"]), minutes(s["hour"]), 0)
            elif key[0] == "a":
                ev = s["event"]
                same = [minutes(o["hour"]) for k, o in slots.items() if k[0] == "t" and o["event"] is ev]
                s["timed_here"] = bool(same)
                base = max(same) if same else (minutes(ev["hour"]) if ev["hour"] else 2000)
                s["sort"] = (day_index(ev["day"]), base, 1)
            else:
                s["sort"] = (day_index(s["day"]), 9999, 2)
        ordered = sorted(slots.values(), key=lambda s: s["sort"])
        work = [s for s in ordered if s["tasks"]]
        single = len(work) == 1 and len(work[0]["tasks"]) == 1
        for s in ordered:
            s["who"] = who_for_slot(s["tasks"], members, short)
            s["labels"] = [shorten(strip_group(t["task"], name), SINGLE_LABEL if single else
                                   max(22, min(MULTI_LABEL, LINE_CHARS - len(" · ".join(x for x in (who, gap) if x))
                                               - (3 if who or gap else 0))))
                           for t, who, _, gap in s["who"]]
        need = Counter()               # גודל הקבוצה = השיא בשעה אחת, כמו assign_groups.peak
        for t in tasks:
            need[(t["day"], t["hour"]) if t["hour"] else ("*", t["row"])] += int(t["people"] or 0)
        cards.append({"name": name, "stage": g.get("stage") or tasks[0]["stage"], "leader": leader,
                      "members": members, "slots": ordered, "start": work[0]["sort"],
                      "multi_day": len({sched_day(s["day"]) for s in work}) > 1, "first_day": work[0]["day"] or "",
                      "peak": max(need.values(), default=0), "row": min(t["row"] for t in tasks)})

    stage_rank = lambda st: bw.STAGES.index(st) if st in bw.STAGES else len(bw.STAGES)
    cards.sort(key=lambda c: (c["start"], stage_rank(c["stage"]), c["row"]))
    return cards, loose


def chip(num, label, color):
    return '<span class="chip" style="--c:{c};--t:{t}"><span class="n" dir="ltr">{n}</span>{l}</span>'.format(
        c=color, t=mix(color, 0.88, 255), n=esc(num), l=esc(label))


def chips_html(nums, cards):
    """שבבים לשעה אחת בציר. רצף של 3+ כרטיסים מאותו שלב → שבב טווח אחד («2–8 הכנות שישי»)."""
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j, stage = i, cards[nums[i] - 1]["stage"]
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1 and cards[nums[j + 1] - 1]["stage"] == stage:
            j += 1
        if j - i >= 2:
            out.append(chip("{}–{}".format(nums[i], nums[j]), stage or "", stage_color(stage)))
        else:
            out += [chip(k, cards[k - 1]["name"], stage_color(cards[k - 1]["stage"])) for k in range(nums[i], nums[j] + 1)]
        i = j + 1
    return "".join(out)


def timeline_html(data, cards, loose):
    """«לו"ז שבת»: ציר לכל יום — האירועים (נקודה מלאה), השעות שרק תורנויות עובדות בהן (נקודה ריקה),
    וליד כל שעה המספרים של התורנויות. מוצ"ש יושב תחת שבת, כמו בלו"ז."""
    events = data["events"]
    days = OrderedDict((d, []) for d in sorted(
        {sched_day(e["day"]) for e in events if e["day"]} |
        {sched_day(s["day"]) for c in cards for s in c["slots"] if s["day"]}, key=lambda d: DAY_ORDER.get(d, 9)))
    points = {}

    def point(day, sort, ev=None, hour=None):
        key = (day, ("e", id(ev)) if ev else ("t", sort))
        if key not in points:
            points[key] = {"sort": sort, "event": ev, "hour": hour, "nums": [], "notes": []}
            days.setdefault(day, []).append(points[key])
        return points[key]

    last, ev_day = {}, {}
    for i, e in enumerate(events):
        day = sched_day(e["day"]) if e["day"] else next(iter(days), "")
        ev_day[id(e)] = day
        last[day] = minutes(e["hour"]) if e["hour"] else last.get(day, 0)
        point(day, (last[day], 0, i), ev=e, hour=e["hour"])
    at = {(d, p["sort"][0]): p for (d, _), p in points.items() if p["event"] and p["hour"]}

    def place(day, hour, ev):
        if hour:
            return at.get((day, minutes(hour))) or point(day, (minutes(hour), 1, 0), hour=hour)
        if ev:
            return points[(ev_day[id(ev)], ("e", id(ev)))]
        return point(day, (99999, 2, 0))

    for num, c in enumerate(cards, 1):
        for s in c["slots"]:
            if not s["tasks"]:
                continue                        # שורת עזרה — השבב בכרטיס של הקבוצה שלה
            place(sched_day(s["day"]) if s["day"] else "", s["hour"], s["event"])["nums"].append(num)
    for t in loose:
        ev = task_event(events, t)
        day = sched_day(t["day"]) if t["day"] else (sched_day(ev["day"]) if ev else "")
        place(day, t["hour"], ev)["notes"].append(t["task"] + (" — " + ", ".join(t["names"]) if t["names"] else ""))

    def day_html(day, pts):
        lines = []
        for p in sorted(pts, key=lambda p: p["sort"]):
            e, bits = p["event"], []
            if e:
                extra = "".join("&nbsp;· {}".format(esc(x)) for x in (e["place"], e["note"]) if x)
                bits.append('<span class="evn">{}</span>{}'.format(
                    esc(e["name"]), '<span class="pl">{}</span>'.format(extra) if extra else ""))
            bits += ['<span class="nt">{}</span>'.format(esc(n)) for n in p["notes"]]
            if p["nums"]:
                bits.append(chips_html(p["nums"], cards))
            if bits:
                time = "ללא שעה" if p["sort"][0] == 99999 else (hhmm(p["hour"]) or "—")
                lines.append('<div class="pt {k}"><span class="t">{t}</span><span class="c">{b}</span></div>'.format(
                    k="ev" if e else "du", t=esc(time), b=" ".join(bits)))
        return '<div class="day"><div class="dh">{}</div>{}</div>'.format(esc(day or "ללא יום"), "".join(lines))

    order = [d for d in days if days[d]]
    cols = [order[:-1], order[-1:]] if len(order) >= 2 else [order]   # שישי (וחמישי) | שבת ומוצ"ש
    stages = list(dict.fromkeys(c["stage"] for c in cards if c["stage"]))
    return ('<div class="sec"><b>לו"ז שבת</b><span class="hint">ליד כל שעה — המספרים של התורנויות שעובדות בה; '
            'הכרטיס עם המספר — בלו"ז הצל</span></div><div class="cols">{cols}</div>'
            '<div class="legend">{legend}</div>').format(
        cols="".join('<div class="col">{}</div>'.format("".join(day_html(d, days[d]) for d in col)) for col in cols),
        legend="".join('<span class="lg"><i style="background:{}"></i>{}</span>'.format(stage_color(s), esc(s))
                       for s in stages))


def card_html(card, num):
    """«לו"ז צל»: כרטיס אחיד — מספר · שם · N אנשים · אחראי/ת / כל השמות / שעה ומה עושים בה."""
    color, n = stage_color(card["stage"]), len(card["members"])
    count = ("{} אנשים".format(n) if n != 1 else "אדם אחד") if n else \
        ("דרושים {}".format(card["peak"]) if card["peak"] else "טרם שובצו")
    meta = count + (' · אחראי/ת: <b>{}</b>'.format(esc(card["leader"])) if card["leader"] else "")
    names = esc(", ".join(card["members"])) if card["members"] else '<span class="none">טרם שובצו</span>'
    route, prev_day = [], None
    for s in card["slots"]:
        if s["hour"]:
            pill, cls = hhmm(s["hour"]), ""
        elif s["event"]:          # בלי שעה: שעת האירוע, ואם לקבוצה כבר יש שעה סביבו («בסיום הטיש») — שמו
            ev = s["event"]
            pill, cls = (ev["name"] if s.get("timed_here") or not ev["hour"] else hhmm(ev["hour"])), " anchor"
        else:
            pill, cls = "ללא שעה", " anchor"
        if card["multi_day"] and s["day"] and sched_day(s["day"]) != prev_day:
            pill = "{} {}".format(s["day"], pill)
        prev_day = sched_day(s["day"])
        items = ['<div class="it">{l}{sep}{w}{g}</div>'.format(
            l=esc(label), sep=" — " if label and (who or gap) else "",
            w='<span class="who {}">{}</span>'.format(kind, esc(who)) if who else "",
            g='{}<span class="who note">{}</span>'.format(" · " if who else "", esc(gap)) if gap else "")
            for (t, who, kind, gap), label in zip(s["who"], s["labels"]) if label or who or gap]
        if not items and s["tasks"] and s["event"] and not s["hour"]:
            items = ['<div class="it">{}</div>'.format(esc(s["event"]["name"]))]   # ניקיונות מוצ"ש
        items += ['<div class="it help">מצטרפים מ«{}» לעזרה — {}</div>'.format(esc(g), k) for g, k in s["help"]]
        route.append('<span class="pill{}">{}</span><div class="its">{}</div>'.format(
            cls, esc(pill), "".join(items) or '<div class="it">&nbsp;</div>'))
    return ('<div class="card" style="--c:{c};--t:{t};--d:{d}"><div class="hd"><span class="n" dir="ltr">{num}</span>'
            '<span class="nm">{name}</span><span class="meta">{meta}</span></div>'
            '<div class="names">{names}</div><div class="route">{route}</div></div>').format(
        c=color, t=mix(color, 0.9, 255), d=mix(color, 0.28, 0), num=num, name=esc(card["name"]),
        meta=meta, names=names, route="".join(route))


CARD_PROBE = """<script>
(function(){
  function hs(sel){ var a=[]; var cs=document.querySelectorAll(sel);
    for (var i=0;i<cs.length;i++) a.push(Math.round(cs[i].getBoundingClientRect().height)); return a.join(','); }
  function report(){ document.title = 'HALF:' + hs('.probe.half .card') + '|FULL:' + hs('.probe.full .card'); }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""


def measure_cards(cards):
    """גובה כל כרטיס (px) בחצי רוחב וברוחב מלא — מרינדור אחד, כדי לסדר אותם בזוגות."""
    body = "".join(card_html(c, n) for n, c in enumerate(cards, 1))
    page = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{f}{b}{c}</style></head><body><div class="page"><div class="inner">
<div class="probe half" style="width:calc((100% - 2.6mm)/2)">{x}</div><div class="probe full">{x}</div>
</div></div>{s}</body></html>""".format(f=font_face_css(), b=BASE_CSS, c=SHADOW_CSS, x=body, s=CARD_PROBE)
    m = re.search(r"HALF:([0-9,]*)\|FULL:([0-9,]*)", dump_dom(page))
    if not m:
        raise SystemExit("מדידת הכרטיסים של לו\"ז הצל נכשלה")
    return [[int(x) for x in g.split(",") if x] for g in m.groups()]


GAP = 10                # px בין כרטיסים בעמודה (2.6mm)
BLOCK_GAP = 10          # px בין בלוקים (ריפוד התא)
MAX_BLOCK = 300         # בלוק גבוה מזה אסור — בלוקים קטנים = חלוקה טובה לעמודים
BLOCK_PENALTY = 3       # px לכל כרטיס מעבר לזוג — בשוויון עדיף זוגות (קריאה בשורות)


def pack_day(idxs, half, full):
    """חלוקה של כרטיסי יום אחד, לפי הסדר, לבלוקים: כרטיס יחיד ברוחב מלא, או שתי עמודות — רצף
    בימין והמשכו בשמאל. תכנון דינמי על הגבהים שנמדדו: סכום הגבהים הקטן ביותר, בלי בלוק מעל MAX_BLOCK."""
    n = len(idxs)
    pre = [0]
    for i in idxs:
        pre.append(pre[-1] + half[i])
    col = lambda a, b: (pre[b] - pre[a]) + GAP * (b - a - 1) if b > a else 0
    best, how = [0] + [float("inf")] * n, [None] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            if j - i == 1:
                h, opt = full[idxs[i]], (i, j, None)
            else:
                h, k = min((max(col(i, k), col(k, j)), k) for k in range(i + 1, j))
                if h > MAX_BLOCK:
                    continue
                h, opt = h + BLOCK_PENALTY * (j - i - 2), (i, j, k)
            if best[i] + h + BLOCK_GAP < best[j]:
                best[j], how[j] = best[i] + h + BLOCK_GAP, opt
    blocks, j = [], n
    while j > 0:
        i, j2, k = how[j]
        blocks.append([idxs[i:j2]] if k is None else [idxs[i:k], idxs[k:j2]])
        j = i
    return blocks[::-1]


def shadow_rows(data):
    """שורות הטבלה של לו"ז הצל (כל שורה — יחידה שלא נחתכת בין עמודים): הציר, ואחריו בלוקים של
    כרטיסים יום אחרי יום. כותרת היום נכנסת לבלוק הראשון של היום, וכותרת «לו"ז צל» לבלוק הראשון."""
    cards, loose = shadow_cards(data)
    rows = [{"band": timeline_html(data, cards, loose)}]
    if not cards:
        return rows
    half, full = measure_cards(cards)
    days = OrderedDict()
    for i, c in enumerate(cards):
        days.setdefault(c["first_day"], []).append(i)
    for day, idxs in days.items():
        for k, stacks in enumerate(pack_day(idxs, half, full)):
            rows.append({"stacks": stacks, "day": day, "head": k == 0, "cards": cards})
    rows[1]["section"] = True
    return rows


def shadow_row_html(row, cont=False):
    """`cont` — השורה פותחת עמוד באמצע יום: חוזרים על כותרת היום."""
    if "band" in row:
        return "<tr><td>{}</td></tr>".format(row["band"])
    head = ""
    if row.get("section"):
        head += ('<div class="sec"><b>לו"ז צל</b><span class="hint">כרטיס לכל תורנות · ליד שעה בלי שמות — '
                 'כל הקבוצה · «בלי X» — כולם חוץ מ-X</span></div>')
    if row["head"] or cont:
        head += '<div class="dayhd">{}{}</div>'.format(esc(row["day"] or "ללא יום"),
                                                       " <small>(המשך)</small>" if cont and not row["head"] else "")
    stacks = "".join('<div class="stack">{}</div>'.format("".join(card_html(row["cards"][i], i + 1) for i in st))
                     for st in row["stacks"])
    return '<tr><td>{}<div class="pair">{}</div></td></tr>'.format(head, stacks)


def shadow_html(data, pages, fit=1.0, measure=False, of=None, first=1):
    """מסמך לו"ז הצל. `pages` = רשימת עמודים, כל עמוד רשימת שורות מ-shadow_rows.
    `of`/`first` מאפשרים לרנדר עמוד בודד ועדיין לסמן «עמוד 2 מתוך 3»."""
    total = of or len(pages)
    fixed = measure or fit < 1.0 or total > 1
    sheets = []
    for i, page_rows in enumerate(pages):
        body = "".join(shadow_row_html(row, cont=(j == 0 and (i > 0 or first > 1)))
                       for j, row in enumerate(page_rows))
        sheets.append('<div class="page{fixed}"><div class="inner">'
                      '<h1>לו"ז שבת ולו"ז צל</h1><div class="when">{when}{part}</div>'
                      '<table class="grid"><tbody>{rows}</tbody></table>'
                      '<footer>מדרשת עין פרת</footer></div></div>'.format(
                          fixed=" fixed" if fixed else "", when=esc(when_line(data)),
                          part=" · עמוד {} מתוך {}".format(first + i, total) if total > 1 else "",
                          rows=body))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body>
{sheets}{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, css=SHADOW_CSS, fit=fit,
        sheets="".join(sheets), script=MEASURE_SCRIPT if measure else "")

# מדידת לו"ז הצל: כמה הוא גולש מעמוד אחד, וגובה כל שורה — כדי לכווץ או לחלק לעמודים.
MEASURE_SCRIPT = """<script>
(function(){
  function report(){
    var page = document.querySelector('.page');
    var inner = document.querySelector('.inner');
    var table = inner.querySelector('table');
    var cs = getComputedStyle(page);
    var avail = page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var innerH = inner.getBoundingClientRect().height;
    var heights = [];
    var rows = table.querySelectorAll('tbody tr');
    for (var i = 0; i < rows.length; i++) {
      heights.push(Math.round(rows[i].getBoundingClientRect().height));
    }
    document.title = 'FIT:' + (avail / innerH) +
                     '|AVAIL:' + Math.round(avail) +
                     '|CHROME:' + Math.round(innerH - table.getBoundingClientRect().height) +
                     '|ROWS:' + heights.join(',');
  }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""
MIN_FIT = 0.9           # לו"ז הצל: מתחת לזה עדיף לחלק לעמודים קריאים מלדחוס עמוד אחד
FLYER_MIN_FIT = 0.8     # פלייר שגולש מכווץ עד כאן; מעבר לזה — שני עמודים


PAGE_SAVE_FIT = 0.9     # כיווץ קל עד כאן מותר אם הוא חוסך עמוד שלם


def split_pages(rows, heights, avail, chrome):
    """חלוקת השורות לעמודים לפי הגובה שנמדד, בלי לחתוך שורה באמצע.
    מחזיר (עמודים, מקדם כיווץ): אם כיווץ קל חוסך עמוד שלם — מכווצים; ואז מאזנים
    בין העמודים, כי עמוד אחרון עם שורה בודדת נראה רע."""
    def chunk(cap):
        pages, cur, used = [], [], 0
        for row, h in zip(rows, heights):
            if cur and used + h > cap:
                pages.append(cur)
                cur, used = [], 0
            cur.append(row)
            used += h
        return pages + ([cur] if cur else [])

    # הגבהים נמדדו ללא כיווץ; בכיווץ f נכנסים לעמוד (avail/f − chrome) מהם.
    # 0.97 — מרווח לכותרת היום שחוזרת בראש עמוד המשך.
    capacity = lambda f: (avail / f - chrome) * 0.97
    fit, pages = 1.0, chunk(capacity(1.0))
    if len(pages) > 1:
        n, f = len(pages) - 1, 1.0         # הכיווץ הקטן ביותר שמכניס הכל ב-n עמודים
        while f > PAGE_SAVE_FIT:
            f = round(f - 0.01, 2)
            if len(chunk(capacity(f))) <= n:
                fit, pages = f, chunk(capacity(f))
                break
    if len(pages) > 1:                     # פיזור שווה, כל עוד מספר העמודים לא גדל
        balanced = chunk(max(sum(heights) / len(pages) * 1.08, max(heights)))
        if len(balanced) == len(pages):
            pages = balanced
    return pages, fit


# ---------------------------------------------------------------------------
# רינדור ב-Chromium
# ---------------------------------------------------------------------------
def chrome_binary():
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    raise SystemExit("לא נמצא דפדפן Chromium להפקת ה-PDF")


def shot_binary():
    """הדפדפן לצילומי PNG. ב-chrome המלא חלון בגובה 1123 מצייר רק כ-1036px (תחתית העמוד —
    שורות אחרונות ופוטר — נעלמת מהתמונה); headless_shell מצייר את כל החלון, ולכן הוא קודם."""
    for candidate in CHROME_CANDIDATES:
        if "headless_shell" in candidate and Path(candidate).exists():
            return candidate
    return chrome_binary()


def dump_dom(html_text):
    """מריץ את העמוד ב-Chromium ומחזיר את ה-DOM אחרי הסקריפטים (סקריפט מדידה כותב ל-document.title)."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "measure.html"
        source.write_text(html_text, encoding="utf-8")
        result = subprocess.run(
            [chrome_binary(), "--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=8000",
             "--user-data-dir={}/profile".format(tmp), "--dump-dom", source.as_uri()],
            capture_output=True, timeout=180)
    return result.stdout.decode("utf-8", "replace")


def measure_page(html_text):
    """מריץ עמוד (לו"ז צל או פלייר) ב-Chromium ומחזיר (מקדם התאמה לעמוד אחד, גובה
    פנוי, גובה הכותרת והפוטר, גובה כל שורת טבלה). 1.0 = נכנס לעמוד."""
    match = re.search(r"FIT:([0-9.]+)\|AVAIL:([0-9]+)\|CHROME:([0-9]+)\|ROWS:([0-9,]*)", dump_dom(html_text))
    if not match:
        return 1.0, 0, 0, []
    ratio = float(match.group(1))
    heights = [int(h) for h in match.group(4).split(",") if h]
    return (1.0 if ratio >= 1.03 else ratio * 0.97, int(match.group(2)), int(match.group(3)), heights)


def render(html_text, out_pdf=None, out_png=None, png_pages=None):
    """מרנדר את ה-HTML ל-PDF ו/או ל-PNG. `png_pages` = כמה עמודים התמונה מכסה
    (ברירת מחדל: מספר העמודים ב-PDF שנוצר); מסמך שכבר מחולק לעמודים מצלם עמוד אחד."""
    chrome = chrome_binary()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "page.html"
        source.write_text(html_text, encoding="utf-8")
        common = [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                  "--virtual-time-budget=6000", "--user-data-dir={}/profile".format(tmp)]
        if out_pdf:
            subprocess.run(common + ["--no-pdf-header-footer", "--print-to-pdf-no-header",
                                     "--print-to-pdf={}".format(out_pdf), source.as_uri()],
                           check=True, capture_output=True, timeout=180)
        if out_png:
            pages = png_pages or (pdf_pages(out_pdf) if out_pdf else 1)
            subprocess.run([shot_binary()] + common[1:] + ["--window-size=794,{}".format(1123 * pages),
                                     "--force-device-scale-factor=2",
                                     "--screenshot={}".format(out_png), source.as_uri()],
                           check=True, capture_output=True, timeout=180)
    return pdf_pages(out_pdf) if out_pdf else 1


def pdf_pages(path):
    return max(1, len(re.findall(rb"/Type\s*/Page[^s]", Path(path).read_bytes())))


def main():
    ap = argparse.ArgumentParser(description="הפקת לו\"ז צל ופליירים")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-11")
    ap.add_argument("--only", choices=["flyers", "shadow"], help="להפיק רק חלק")
    ap.add_argument("--no-png", action="store_true", help="בלי תמונות PNG")
    ap.add_argument("--with-recipes", action="store_true",
                    help="להוסיף גם את אופן ההכנה (ברירת מחדל: מצרכים בלבד)")
    args = ap.parse_args()

    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    source = ROOT / "shabbatot" / "{}.xlsx".format(d.isoformat())
    if not source.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם tools/new_shabbat.py".format(source))
    data = read_workbook(source)
    out_dir = ROOT / "shabbatot" / d.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("*.pdf")) + list(out_dir.glob("*.png")):
        old.unlink()                      # בלי פלטים ישנים מהרצה קודמת

    made = []
    if args.only != "shadow":
        for group in data["groups"]:
            tasks = [t for t in data["tasks"] if t["group"] == group["name"]]
            pdf = out_dir / "{}.pdf".format(group["name"])
            png = None if args.no_png else out_dir / "{}.png".format(group["name"])
            fit = measure_page(flyer_html(group, tasks, data, args.with_recipes, measure=True))[0]
            if fit < FLYER_MIN_FIT:
                fit = 1.0                 # ארוך מדי לכיווץ סביר — עדיף שני עמודים קריאים
            render(flyer_html(group, tasks, data, args.with_recipes, fit=fit), pdf, png)
            made += [x for x in (pdf, png) if x]
    if args.only != "flyers":
        rows = shadow_rows(data)
        fit, avail, chrome_h, heights = measure_page(shadow_html(data, [rows], measure=True))
        if fit >= MIN_FIT:
            pages = [rows]                # נכנס לעמוד אחד, אולי בכיווץ קל
        else:
            pages, fit = split_pages(rows, heights, avail, chrome_h)
        pdf = out_dir / "לוז צל.pdf"
        render(shadow_html(data, pages, fit=fit), pdf)
        made.append(pdf)
        if not args.no_png:               # תמונה לכל עמוד — נוח לשלוח בנפרד
            for i, page_rows in enumerate(pages):
                png = out_dir / ("לוז צל.png" if len(pages) == 1
                                 else "לוז צל {}.png".format(i + 1))
                render(shadow_html(data, [page_rows], fit=fit, of=len(pages), first=i + 1),
                       out_png=png, png_pages=1)
                made.append(png)
        print("  לו\"ז צל: {} עמוד/ים".format(len(pages)))

    for path in made:
        print("  {:<40} {:>8,} bytes".format(path.name, path.stat().st_size))
    print("{} קבצים ← {}/".format(len(made), out_dir.relative_to(ROOT)))


if __name__ == "__main__":
    main()
