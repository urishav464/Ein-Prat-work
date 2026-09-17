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
DAY_ORDER = {"חמישי": 0, "שישי": 1, "שבת": 2, "מוצאי שבת": 3}
SCHEDULE_DAY = {"חמישי": "חמישי", "שישי": "שישי", "שבת": "שבת", "מוצאי שבת": "שבת"}   # מוצ"ש יושב בלו"ז תחת שבת
NO_ANCHOR = "ללא עוגן"


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
            "events": events, "tasks": tasks, "groups": groups, "recipes": recipes}


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
.page{width:210mm;padding:10mm 10mm 12mm;position:relative}
td,th{padding:1.4mm 2.5mm;font-size:9.5pt;line-height:1.35}
td.event{width:46mm;text-align:center;position:relative}
td.event.has-day{padding-top:9mm}
td.event .day{position:absolute;top:1.4mm;right:2.5mm;font-family:'Rubik',sans-serif;
              font-weight:700;font-size:13.5pt}
td.event .hour{display:block;font-family:'Rubik',sans-serif;font-size:10.5pt}
td.event .name{display:block;font-size:11.5pt;font-weight:600}
td.event .place{display:block;font-size:9pt;color:#5A6572}
td.event.loose{background:#FCE3C6}
td.lines{text-align:center}
.who{font-weight:600;line-height:1.6}
.who .resp{font-weight:400;color:#5A6572}
.who .resp b{font-weight:700;color:#1F2430}
.line{padding:.4mm 0}
.line b{font-family:'Rubik',sans-serif;font-weight:600}
.line .names{color:#3A4552}
.line.all .names{font-style:italic}
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
td.task .note{display:block;margin-top:1mm;font-size:9.5pt;color:#5A6572}
th.names,td.names{width:60mm;font-size:11pt}
.empty{margin-top:8mm;text-align:center;color:#8A94A0;font-size:12pt}
.recipe{margin-top:7mm;border:1px solid #1F2430;padding:4mm 5mm;page-break-inside:avoid}
.recipe h2{font-family:'Rubik',sans-serif;font-size:15pt;display:flex;justify-content:space-between;align-items:baseline}
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
    return "\n".join(out) or "—"


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
    multi_day = len({t["day"] for t in ordered}) > 1
    for t in ordered:
        names = ", ".join(t["names"]) or ("כולם" if t["people"] is None else "")
        day = ""
        if multi_day and t["day"] != last_day:
            day, last_day = '<span class="day">{}</span>'.format(esc(t["day"])), t["day"]
        rows.append('<tr><td class="hour">{day}{hour}</td><td class="task">{task}{note}</td>'
                    '<td class="names">{names}</td></tr>'.format(
                        day=day, hour=esc(hhmm(t["hour"])) or "—", task=esc(t["task"]),
                        note='<span class="note">{}</span>'.format(esc(t["note"])) if t["note"] else "",
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


def task_line(task, members=()):
    hour = hhmm(task["hour"])
    names = ", ".join(task["names"])
    if not names and task["people"] is None and task["group"]:
        names = "כולם"
    if members and set(task["names"]) == set(members):
        names = "כולם"                     # השמות כבר בשורת הכותרת של הקבוצה
    return ('<div class="line{all}"><b>{hour}</b>{sep}{task}'
            '{names}</div>').format(
        all=" all" if names == "כולם" else "", hour=esc(hour), sep=" — " if hour else "",
        task=esc(task["task"]),
        names=' <span class="names">— {}</span>'.format(esc(names)) if names else "")


def shadow_lines(items, groups, introduced):
    """שורות הצל לאירוע אחד. שורת השמות של קבוצה מופיעה בפעם הראשונה שהיא מופיעה;
    אחר כך מספיקים השמות שליד כל משימה."""
    by_group = {g["name"]: g for g in groups}
    seen, out = [], []
    for t in items:                         # קבוצה אחת אחרי השנייה, לפי סדר ההופעה
        if t["group"] not in seen:
            seen.append(t["group"])
    for name in seen:
        group = by_group.get(name)
        members = group["members"] if group else []
        if members and name not in introduced:
            introduced.add(name)
            resp = (group or {}).get("leader")
            out.append('<div class="who">{names}{resp}</div>'.format(
                names=esc(", ".join(members)),
                resp=' <span class="resp">· אחראי/ת: <b>{}</b></span>'.format(esc(resp)) if resp else ""))
        out += [task_line(t, members) for t in items if t["group"] == name]
    return "".join(out)


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
MIN_FIT = 0.72          # מתחת לזה עדיף לחלק לעמודים קריאים מלדחוס עמוד אחד זעיר
FLYER_MIN_FIT = 0.8     # פלייר שגולש מכווץ עד כאן; מעבר לזה — שני עמודים


def shadow_rows(data):
    """שורות לו"ז הצל — אירוע ומי עושה מה לידו. «יום» נשמר בנפרד כדי שאפשר יהיה
    לחזור על כותרת היום בראש כל עמוד."""
    events, groups = data["events"], data["groups"]
    by_event = {id(e): [] for e in events}
    loose = []
    for t in sorted(data["tasks"], key=lambda t: (DAY_ORDER.get(t["day"], 9), t["hour"] is None,
                                                 t["hour"] or datetime.min.time(), t["row"])):
        e = find_event(events, t)
        (by_event[id(e)] if e else loose).append(t)

    rows, introduced = [], set()
    for e in events:
        rows.append({"day": e["day"], "hour": hhmm(e["hour"]), "name": e["name"], "place": e["place"],
                     "note": e["note"], "loose": False,
                     "lines": shadow_lines(by_event[id(e)], groups, introduced) or "&nbsp;"})
    if loose:
        rows.append({"day": None, "hour": "", "name": NO_ANCHOR, "place": None, "note": None,
                     "loose": True, "lines": shadow_lines(loose, groups, introduced)})
    return rows


def shadow_row_html(row, show_day):
    return ('<tr><td class="event{loose}{has_day}">{day}<span class="hour">{hour}</span>'
            '<span class="name">{name}</span>{place}{note}</td><td class="lines">{lines}</td></tr>').format(
        loose=" loose" if row["loose"] else "", has_day=" has-day" if show_day else "",
        day='<span class="day">יום {}:</span>'.format(esc(row["day"])) if show_day else "",
        hour=esc(row["hour"]), name=esc(row["name"]),
        place='<span class="place">{}</span>'.format(esc(row["place"])) if row["place"] else "",
        note='<span class="place">{}</span>'.format(esc(row["note"])) if row["note"] else "",
        lines=row["lines"])


def shadow_html(data, pages, fit=1.0, measure=False, of=None, first=1):
    """מסמך לו"ז הצל. `pages` = רשימת עמודים, כל עמוד רשימת שורות מ-shadow_rows.
    `of`/`first` מאפשרים לרנדר עמוד בודד ועדיין לסמן «עמוד 2 מתוך 3»."""
    total = of or len(pages)
    fixed = measure or fit < 1.0 or total > 1
    sheets = []
    for i, page_rows in enumerate(pages):
        body, last_day = [], None
        for j, row in enumerate(page_rows):
            body.append(shadow_row_html(row, bool(row["day"]) and (j == 0 or row["day"] != last_day)))
            last_day = row["day"] or last_day
        sheets.append('<div class="page{fixed}"><div class="inner">'
                      '<h1>לו"ז שבת ולו"ז צל</h1><div class="when">{when}{part}</div>'
                      '<table><tbody>{rows}</tbody></table>'
                      '<footer>מדרשת עין פרת</footer></div></div>'.format(
                          fixed=" fixed" if fixed else "", when=esc(when_line(data)),
                          part=" · עמוד {} מתוך {}".format(first + i, total) if total > 1 else "",
                          rows="".join(body)))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body>
{sheets}{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, css=SHADOW_CSS, fit=fit,
        sheets="".join(sheets), script=MEASURE_SCRIPT if measure else "")


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


def measure_page(html_text):
    """מריץ עמוד (לו"ז צל או פלייר) ב-Chromium ומחזיר (מקדם התאמה לעמוד אחד, גובה
    פנוי, גובה הכותרת והפוטר, גובה כל שורת טבלה). 1.0 = נכנס לעמוד."""
    chrome = chrome_binary()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "measure.html"
        source.write_text(html_text, encoding="utf-8")
        result = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=8000",
             "--user-data-dir={}/profile".format(tmp), "--dump-dom", source.as_uri()],
            capture_output=True, timeout=180)
        match = re.search(r"FIT:([0-9.]+)\|AVAIL:([0-9]+)\|CHROME:([0-9]+)\|ROWS:([0-9,]*)",
                          result.stdout.decode("utf-8", "replace"))
        if not match:
            return 1.0, 0, 0, []
        ratio = float(match.group(1))
        heights = [int(h) for h in match.group(4).split(",") if h]
        return (1.0 if ratio >= 1.03 else ratio * 0.97,
                int(match.group(2)), int(match.group(3)), heights)


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
            subprocess.run(common + ["--window-size=794,{}".format(1123 * pages),
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
