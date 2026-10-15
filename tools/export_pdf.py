# -*- coding: utf-8 -*-
"""הפקת הדפים של השבת כ-PDF/PNG מתוך קובץ השבת: לו"ז שבת (עמוד אחד, רק הלו"ז), דף התורנויות
(מי בכל תורנות — בלי שעות) ודף לכל תורנות (מה עושים ומתי, מי, והמתכון המלא).

    python3 tools/export_pdf.py 2026-09-11
    python3 tools/export_pdf.py 2026-09-11 --only schedule

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
IMAGES = "תמונות"       # התמונות לשליחה — תיקייה בתוך shabbatot/<תאריך>/
SCHEDULE_NAME, DUTIES_NAME = 'לו"ז שבת', "תורנויות"   # שמות הקבצים (דרך safe_name: לו״ז שבת)
WINDOWS_BAD = str.maketrans({'"': "״", **{c: "-" for c in '<>:/\\|?*'}})


def safe_name(text):
    """שם קובץ שעובר גם בווינדוס: " (מוצ"ש, לו"ז) הופך לגרשיים ״ ושאר התווים האסורים למקף.
    ווינדוס מדלג בשקט על קובץ ששמו לא חוקי — כך נעלמו 4 מ-22 התמונות של 16.10 בחילוץ ה-zip."""
    return re.sub(r"[\x00-\x1f]", "", text.translate(WINDOWS_BAD)).rstrip(". ")


def image_name(num, name, recipe=False):
    """«03 חלות.png»: המספר של התורנות בדף התורנויות, כך שהתיקייה מסודרת כמו הדף (00 = לו"ז ודף התורנויות).
    עמוד המתכון — «03 חלות — מתכון.png», ליד הדף של התורנות."""
    return "{:02d} {}{}.png".format(num, safe_name(name), " — מתכון" if recipe else "")


# ---------------------------------------------------------------------------
# קריאת קובץ השבת
# ---------------------------------------------------------------------------
def cell(ws, row, col):
    value = ws.cell(row=row, column=col).value
    if isinstance(value, str):
        value = value.strip()
    return value or None


def people_cell(ws, row):
    """«אנשים»: מספר, או None כשהתא ריק (= כל הקבוצה). 0 נשאר 0 — הכנה של מצטרפים בלבד."""
    value = ws.cell(row=row, column=bw.T_PEOPLE).value
    return None if value in (None, "") else int(value)


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
                      "people": people_cell(ws, r), "names": split_names(cell(ws, r, bw.T_NAMES)),
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

# שלושה סוגי דפים, באותה שפה עיצובית (מספר בצבע השלב, «מה עושים» בשורות, שמות רק איפה שמתחלקים):
#   לו"ז שבת   — עמוד אחד, רק הלו"ז: שישי בצד אחד, שבת ומוצ"ש בצד השני
#   תורנויות   — מי בכל תורנות (מספר · שם · כמה אנשים · אחראי/ת, והשמות) — בלי שעות ובלי משימות:
#                כל אחד מוצא את השם שלו, ואז את הדף של התורנות (אותו מספר)
#   דף לכל תורנות — מה עושים ומתי, מי, והמתכון המלא (מצרכים ואופן ההכנה)
STAGE_COLORS = ["#B26B00", "#1F7A72", "#3651A3", "#8A3F86"]   # לפי bw.STAGES
OTHER_COLOR = "#5A6572"
REST = "כל השאר"
HELP_PREFIX = bw.HELP_TASK.format("")                        # «עזרה בהכנת »

CARD_CSS = """
.n{display:inline-block;font-family:'Rubik',sans-serif;font-weight:600;color:#fff;background:var(--c);
   border-radius:1.8mm;min-width:4.6mm;padding:0 1mm;text-align:center;line-height:1.5}
.legend{font-size:9pt;color:#5A6572;display:flex;flex-wrap:wrap;gap:4mm}
.lg i{display:inline-block;width:2.6mm;height:2.6mm;border-radius:.7mm;margin-left:1.2mm;vertical-align:-.2mm}
"""

SCHEDULE_CSS = """
.sheet{padding:12mm 12mm 10mm}
h1{font-size:30pt}
.when{font-size:13.5pt;margin-top:1.5mm}
table.cal{margin-top:8mm;table-layout:fixed}
table.cal td{border:0;padding:0;vertical-align:top;width:50%}
table.cal td + td{padding-right:8mm}
.day + .day{margin-top:9mm}
.dh{font-family:'Rubik',sans-serif;font-weight:700;font-size:19pt;border-bottom:2px solid #1F2430;
    padding-bottom:1mm;margin-bottom:2.5mm;display:flex;align-items:baseline;gap:2.5mm}
.dh small{font-family:'Heebo',sans-serif;font-weight:400;font-size:12pt;color:#5A6572}
.ev{display:grid;grid-template-columns:19mm 1fr;column-gap:3mm;align-items:baseline;padding:2.9mm 0 2.9mm 1mm;
    border-bottom:1px solid #D5DBE3}
.ev .t{font-family:'Rubik',sans-serif;font-weight:700;font-size:17pt;font-variant-numeric:tabular-nums;
       padding-right:1.5mm;white-space:nowrap}
.ev .nm{font-family:'Rubik',sans-serif;font-weight:600;font-size:15.5pt;line-height:1.3}
.ev .sub{display:block;font-size:11.5pt;color:#5A6572;line-height:1.4;margin-top:.5mm}
.ev .all{display:block;font-size:11.5pt;color:#1F2430;font-style:italic;margin-top:.5mm}
.ev.key{background:#F1F3F6;border-right:1.6mm solid #1F2430;border-bottom-color:transparent;border-radius:1mm;
        margin:1mm -3mm 1mm 0;padding-right:1.4mm}
footer{margin-top:7mm}
"""

DUTIES_CSS = """
.page{width:210mm;padding:9mm 10mm 10mm;position:relative}
h1{font-size:22pt}
.when{font-size:10.5pt;margin-top:1mm}
table.grid{margin-top:3mm;border-collapse:collapse}
table.grid td{border:0;padding:0 0 2.6mm;vertical-align:top;font-size:9.5pt;line-height:1.36;text-align:right}
footer{margin-top:2mm}
.intro{display:flex;flex-direction:column;gap:1.4mm;border-bottom:1.4px solid #1F2430;padding-bottom:1.6mm;
       margin-bottom:1.6mm}
.intro .hint{font-size:10.5pt}
.intro .hint b{font-family:'Rubik',sans-serif}
.dayhd{font-family:'Rubik',sans-serif;font-weight:700;font-size:12pt;margin:.6mm 0 1.4mm;
       display:flex;align-items:center;gap:2mm}
.dayhd small{font-family:'Heebo',sans-serif;font-weight:400;font-size:9pt;color:#5A6572}
.dayhd::after{content:"";flex:1;border-top:1px solid #D5DBE3}
.pair{display:flex;gap:2.6mm;align-items:flex-start}
.stack{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:2.6mm}
.card{font-size:9.5pt;line-height:1.36;border:1px solid #D5DBE3;border-right:1.8mm solid var(--c);
      border-radius:1.6mm;padding:1.3mm 2.4mm 1.5mm}
.hd{display:flex;align-items:baseline;flex-wrap:wrap;column-gap:1.6mm}
.hd .n{font-size:9pt;align-self:center}
.hd .nm{font-family:'Rubik',sans-serif;font-weight:700;font-size:11.5pt}
.hd .meta{font-size:9.2pt;color:#5A6572;white-space:nowrap}
.hd .meta b{color:#1F2430;font-weight:600}
.names{font-size:10pt;color:#1F2430;margin-top:.6mm}
.names .none{color:#A33;font-style:italic}
.joined{font-size:8.8pt;color:#5A6572;margin-top:.3mm}
"""

FLYER_CSS = """
.sheet{padding:11mm 12mm 11mm}
.fhead{display:flex;align-items:center;justify-content:center;gap:3mm}
.fhead .n{font-size:16pt;border-radius:2.6mm;min-width:10mm;padding:.4mm 2mm}
.fhead h1{font-size:26pt}
.fsub{text-align:center;font-family:'Rubik',sans-serif;font-size:12pt;color:#5A6572;margin-top:1mm}
.team{margin:4.5mm auto 0;max-width:176mm;background:var(--t);border-right:1.8mm solid var(--c);border-radius:1.6mm;
      padding:2.2mm 4mm;text-align:center}
.team .meta{font-family:'Rubik',sans-serif;font-size:11pt;color:#3A4552}
.team .meta b{color:#1F2430}
.team .names{font-size:12.5pt;line-height:1.6;margin-top:.6mm}
.team .joined{font-size:10pt;color:#3A4552;margin-top:.6mm}
table.route{margin-top:5mm;border-collapse:separate;border-spacing:0}
table.route td{border:0;border-bottom:1px solid #D5DBE3;padding:2.4mm 0;vertical-align:top;font-size:12pt;
               line-height:1.45}
table.route col.p{width:22mm}
table.route td.p{padding-left:3mm}
.pill{display:inline-block;font-family:'Rubik',sans-serif;font-weight:700;font-size:12pt;background:var(--t);
      border-radius:1.6mm;padding:.3mm 2mm;white-space:nowrap;font-variant-numeric:tabular-nums}
.pill.anchor{background:#fff;border:1.2px solid var(--c);font-weight:500;font-size:10.5pt;white-space:normal}
.pill .d{display:block;font-family:'Heebo',sans-serif;font-weight:400;font-size:9pt;color:#5A6572}
.it + .it{margin-top:2mm}
.tx b{font-family:'Rubik',sans-serif;font-weight:600}
.tx ul{list-style:none;margin:.6mm 0 0}
.tx li{position:relative;padding-right:4.5mm}
.tx li::before{content:"";position:absolute;right:.6mm;top:.62em;width:1.6mm;height:1.6mm;border-radius:50%;
               background:var(--c)}
.who{font-weight:600;color:var(--d);font-size:11.5pt}
.who.note{color:#A33}
.who .lb{font-weight:400;color:#5A6572}
.tnote{display:block;margin-top:1mm;font-size:10pt;color:#5A6572;white-space:pre-line}
.start .tx{color:#3A4552}
tr.sec td{border-bottom:2px solid var(--c);padding:4mm 0 1.2mm;font-family:'Rubik',sans-serif;font-weight:700;
          font-size:12.5pt}
tr.sec:first-child td{padding-top:0}
tr.sec td small{font-family:'Heebo',sans-serif;font-weight:400;font-size:10pt;color:#5A6572;margin-right:2mm}
.join{display:grid;grid-template-columns:34mm 1fr;gap:3mm;padding:.8mm 0}
.join + .join{border-top:1px dashed #D5DBE3}
.join b{font-family:'Rubik',sans-serif;font-weight:600}
.join .k{color:#5A6572;font-size:10pt}
.empty{margin-top:8mm;text-align:center;color:#8A94A0;font-size:12pt}
.recipe{margin-top:5.5mm;border:1px solid #D5DBE3;border-top:1.6mm solid var(--c);border-radius:1.6mm;padding:3mm 4.5mm 3.4mm;
        break-inside:avoid}
.recipe h2{font-family:'Rubik',sans-serif;font-size:15pt;display:flex;flex-wrap:wrap;gap:1mm 4mm;
           justify-content:space-between;align-items:baseline}
.recipe h2 span{font-size:10.5pt;font-weight:400;color:#5A6572;font-family:'Heebo',sans-serif}
.recipe .cols{display:flex;gap:6mm;margin-top:2.2mm}
.recipe .col{flex:1;min-width:0}
.recipe .col.ing{flex:0 0 64mm}
.recipe h3{font-family:'Rubik',sans-serif;font-size:10.5pt;color:#5A6572;margin-bottom:1mm}
.recipe h4{font-family:'Rubik',sans-serif;font-size:10.5pt;margin:1.6mm 0 .6mm}
.recipe p{font-size:10.5pt;line-height:1.5;white-space:pre-line}
.recipe p b{display:block;margin-top:1.5mm}
.recipe p b:first-child{margin-top:0}
.recipe ol,.recipe ul{margin:0;padding-right:5mm;font-size:10.5pt;line-height:1.5}
.recipe li ul{list-style:disc;padding-right:4.5mm;margin-top:.5mm}
.recipe ol li,.recipe ul li{margin-bottom:.8mm}
.recipe .note{margin-top:2mm;font-size:9.5pt;color:#5A6572}
.rnext{margin-top:4mm;text-align:center;font-family:'Rubik',sans-serif;font-size:11.5pt;color:var(--d)}
.rhead{text-align:center;font-family:'Rubik',sans-serif;font-size:12pt;color:#5A6572;margin-top:1mm}
"""


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


def minutes(t):
    m = t.hour * 60 + t.minute
    return m + 1440 if m < 300 else m          # לפני 05:00 — אחרי חצות


def sched_day(day):
    return SCHEDULE_DAY.get(day, day)


def day_index(day):
    return DAY_ORDER.get(day, 9)


def stage_color(stage):
    return STAGE_COLORS[bw.STAGES.index(stage) % len(STAGE_COLORS)] if stage in bw.STAGES else OTHER_COLOR


def stage_rank(stage):
    return bw.STAGES.index(stage) if stage in bw.STAGES else len(bw.STAGES)


def mix(hex_color, amount, toward):
    rgb = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(round(c + (toward - c) * amount) for c in rgb))


def colors(stage):
    """משתני הצבע של שלב: --c הצבע, --t גוון בהיר לרקע, --d כהה לטקסט."""
    c = stage_color(stage)
    return "--c:{};--t:{};--d:{}".format(c, mix(c, 0.9, 255), mix(c, 0.28, 0))


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
            sets.append((t, [], ""))                 # בלי שמות ובלי מספר (או 0) — כל הקבוצה

    # השעה מחלקת את כל הקבוצה לחלקים זרים — החלק הגדול הוא «כל השאר»
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


def duty_cards(data):
    """כרטיס לכל קבוצה שיש לה משימות, לפי יום ← שלב ← שעת התחלה — המספר שלה בדף התורנויות ובדף שלה.
    slot = שעה אחת: המשימות שלה ומה כתוב ליד כל אחת. משימות ההצטרפות להכנות («עזרה בהכנת X») של
    קבוצה שעוזרת (בית מדרש) נאספות ל-joins — החלוקה להכנות. הכנה בלי אנשים משלה (בראוניז 0+2):
    החברים הם המצטרפים, ו-joined = הקבוצה שממנה הם באים. מחזיר (כרטיסים, משימות בלי קבוצה)."""
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
        own = [t for t in tasks if not t["task"].startswith(HELP_PREFIX)]
        joins = [t for t in tasks if t["task"].startswith(HELP_PREFIX)]
        members, leader = clean_members(g, own or tasks)
        helps, joined = bw.help_tasks(data["tasks"], name), None
        if not members and helps and all(t["people"] == 0 for t in tasks):
            members = list(dict.fromkeys(n for h in helps for n in h["names"]))
            joined = helps[0]["group"]
            if leader in members:
                members = [leader] + [m for m in members if m != leader]
        short = short_names(members)
        slots = OrderedDict()
        for t in own:
            ev = task_event(events, t)
            day = t["day"] or (ev["day"] if ev else "")
            key = ("t", day, t["hour"]) if t["hour"] else (("a", id(ev)) if ev else ("n", day))
            slots.setdefault(key, {"tasks": [], "event": ev, "day": day, "hour": t["hour"]})["tasks"].append(t)
        for key, s in slots.items():          # משימה בלי שעה — אחרי המשימות המתוזמנות של אותו עוגן
            if key[0] == "t":
                s["sort"] = (day_index(s["day"]), minutes(s["hour"]), 0)
            elif key[0] == "a":
                ev = s["event"]
                same = [minutes(o["hour"]) for k, o in slots.items() if k[0] == "t" and o["event"] is ev]
                s["timed_here"] = bool(same)
                base = max(same) if same else (minutes(ev["hour"]) if ev["hour"] else 2000)
                s["sort"] = (day_index(s["day"] or ev["day"]), base, 1)
            else:
                s["sort"] = (day_index(s["day"]), 9999, 2)
        ordered = sorted(slots.values(), key=lambda s: s["sort"])
        for s in ordered:
            s["who"] = who_for_slot(s["tasks"], members, short)
        split = OrderedDict()                  # החלוקה להכנות: שעה ← {יום, [(הכנה, שמות, כמה)]}
        for t in sorted(joins, key=lambda t: (t["hour"] is None, t["hour"] or datetime.min.time(), t["row"])):
            split.setdefault(t["hour"], {"day": t["day"] or "שישי", "parts": []})["parts"].append(
                (t["task"][len(HELP_PREFIX):], t["names"], t["people"]))
        need = Counter()                       # גודל הקבוצה = השיא בשעה אחת, כמו assign_groups.peak
        for t in tasks:
            need[(t["day"], t["hour"]) if t["hour"] else ("*", t["row"])] += int(t["people"] or 0)
        days = list(dict.fromkeys(s["day"] for s in ordered if s["day"]))
        first = ordered[0] if ordered else {"sort": (9, 9999, 2), "day": ""}
        cards.append({"name": name, "stage": g.get("stage") or tasks[0]["stage"], "leader": leader,
                      "members": members, "slots": ordered, "joins": split, "joined": joined,
                      "start": first["sort"], "days": days, "first_day": first["day"] or "",
                      "peak": max(need.values(), default=0), "row": min(t["row"] for t in tasks),
                      "recipes": list(dict.fromkeys(d for t in own for d in split_dishes(t["recipe"])
                                                    if d in data["recipes"]))})
    cards.sort(key=lambda c: (day_index(c["first_day"]), stage_rank(c["stage"]), c["start"], c["row"]))
    data["cards"] = cards
    return cards, loose


def count_text(card):
    n = len(card["members"])
    if n:
        return "{} אנשים".format(n) if n != 1 else "אדם אחד"
    return "דרושים {}".format(card["peak"]) if card["peak"] else "טרם שובצו"


def leader_text(card):
    return ' · אחראי/ת: <b>{}</b>'.format(esc(card["leader"])) if card["leader"] else ""


def joined_text(card, data, hour=True):
    """הכנת מצטרפים בלבד: מאיזו תורנות הם (שם הניקוד שלהם), ובדף שלה — מתי מגיעים להכנה."""
    if not card["joined"]:
        return ""
    if not hour:
        return "מתורנות «{}»".format(card["joined"])
    hours = sorted({h["hour"] for h in bw.help_tasks(data["tasks"], card["name"]) if h["hour"]})
    return "מתורנות «{}» — מגיעים להכנה{}".format(card["joined"], " ב-" + hhmm(hours[0]) if hours else "")


def legend_html(stages):
    return '<div class="legend">{}</div>'.format("".join(
        '<span class="lg"><i style="background:{}"></i>{}</span>'.format(stage_color(s), esc(s)) for s in stages))


# ---------------------------------------------------------------------------
# לו"ז שבת — עמוד אחד, רק הלו"ז
# ---------------------------------------------------------------------------
KEY_EVENTS = ("הדלקת נרות", "הבדלה")


def schedule_html(data, fit=1.0, measure=False):
    """הלו"ז של השבת בעמוד אחד: שישי (וחמישי) מימין, שבת ומוצ"ש משמאל. הדלקת נרות והבדלה בולטות;
    משימה בלי קבוצה («כולם בבית המדרש…») — מתחת לאירוע שלה."""
    events, notes = data["events"], {}
    for t in data["tasks"]:
        if not t["group"]:
            ev = task_event(events, t)
            if ev:
                notes.setdefault(id(ev), []).append(t["task"].replace("\n", " · "))
    havdalah = minutes(data["havdalah"]) if data["havdalah"] else None
    days = OrderedDict()
    for e in events:
        day = e["day"] or "ללא יום"
        if day == "שבת" and havdalah and e["hour"] and minutes(e["hour"]) > havdalah:
            day = "מוצאי שבת"
        days.setdefault(day, []).append(e)
    date = data["date"]
    dates = {"חמישי": -1, "שישי": 0, "שבת": 1, "מוצאי שבת": 1}

    def day_html(day, evs):
        when = ""
        if date and day in dates:
            d = date + timedelta(days=dates[day])
            when = "<small>{}.{}</small>".format(d.day, d.month)
        rows = []
        for e in evs:
            sub = " · ".join(esc(x) for x in (e["place"], e["note"]) if x)
            rows.append('<div class="ev{k}"><span class="t">{t}</span><div><span class="nm">{n}</span>{s}{a}</div></div>'
                        .format(k=" key" if e["name"] in KEY_EVENTS else "", t=esc(hhmm(e["hour"])) or "—",
                                n=esc(e["name"]), s='<span class="sub">{}</span>'.format(sub) if sub else "",
                                a="".join('<span class="all">{}</span>'.format(esc(x)) for x in notes.get(id(e), []))))
        return '<div class="day"><div class="dh">{}{}</div>{}</div>'.format(
            "יום " + esc(day) if day in ("שישי", "שבת", "חמישי") else esc(day), when, "".join(rows))

    order = list(days)
    right = [d for d in order if d in ("חמישי", "שישי")] or order[:1]
    left = [d for d in order if d not in right]
    cols = "".join("<td>{}</td>".format("".join(day_html(d, days[d]) for d in col)) for col in (right, left))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body><div class="sheet page fixed"><div class="inner">
<h1>לו"ז שבת</h1><div class="when">{when}</div>
<table class="cal"><tbody><tr>{cols}</tr></tbody></table>
<footer>מדרשת עין פרת</footer>
</div></div>{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, css=SCHEDULE_CSS, fit=fit, when=esc(when_line(data)), cols=cols,
        script=MEASURE_SCRIPT if measure else "")


# ---------------------------------------------------------------------------
# תורנויות — מי בכל תורנות (בלי שעות), כרטיסים בשתי עמודות
# ---------------------------------------------------------------------------
def card_html(card, num, data):
    names = esc(", ".join(card["members"])) if card["members"] else '<span class="none">טרם שובצו</span>'
    joined = joined_text(card, data, hour=False)                     # בדף התורנויות — בלי שעות
    return ('<div class="card" style="{c}"><div class="hd"><span class="n" dir="ltr">{num}</span>'
            '<span class="nm">{name}</span><span class="meta">{count}{lead}</span></div>'
            '<div class="names">{names}</div>{joined}</div>').format(
        c=colors(card["stage"]), num=num, name=esc(card["name"]), count=count_text(card), lead=leader_text(card),
        names=names, joined='<div class="joined">{}</div>'.format(esc(joined)) if joined else "")


CARD_PROBE = """<script>
(function(){
  function hs(sel){ var a=[]; var cs=document.querySelectorAll(sel);
    for (var i=0;i<cs.length;i++) a.push(Math.round(cs[i].getBoundingClientRect().height)); return a.join(','); }
  function report(){ document.title = 'HALF:' + hs('.probe.half .card') + '|FULL:' + hs('.probe.full .card'); }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""


def measure_cards(cards, data):
    """גובה כל כרטיס (px) בחצי רוחב וברוחב מלא — מרינדור אחד, כדי לסדר אותם בזוגות."""
    body = "".join(card_html(c, n, data) for n, c in enumerate(cards, 1))
    page = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{f}{b}{k}{c}</style></head><body><div class="page"><div class="inner">
<div class="probe half" style="width:calc((100% - 2.6mm)/2)">{x}</div><div class="probe full">{x}</div>
</div></div>{s}</body></html>""".format(f=font_face_css(), b=BASE_CSS, k=CARD_CSS, c=DUTIES_CSS, x=body, s=CARD_PROBE)
    m = re.search(r"HALF:([0-9,]*)\|FULL:([0-9,]*)", dump_dom(page))
    if not m:
        raise SystemExit("מדידת הכרטיסים של דף התורנויות נכשלה")
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


def duties_rows(data, cards):
    """שורות דף התורנויות (כל שורה — יחידה שלא נחתכת בין עמודים): בלוקים של כרטיסים, יום אחרי יום.
    כותרת היום נכנסת לבלוק הראשון של היום, וההסבר והמקרא — לבלוק הראשון."""
    if not cards:
        return []
    half, full = measure_cards(cards, data)
    days = OrderedDict()
    for i, c in enumerate(cards):
        days.setdefault(c["first_day"], []).append(i)
    rows = []
    for day, idxs in days.items():
        for k, stacks in enumerate(pack_day(idxs, half, full)):
            rows.append({"stacks": stacks, "day": day, "head": k == 0, "cards": cards, "data": data})
    rows[0]["intro"] = list(dict.fromkeys(c["stage"] for c in cards if c["stage"]))
    return rows


def duties_row_html(row, cont=False):
    """`cont` — השורה פותחת עמוד באמצע יום: חוזרים על כותרת היום."""
    head = ""
    if row.get("intro"):
        head += ('<div class="intro"><div class="hint">מוצאים את השם שלכם — ואז את <b>הדף של התורנות</b> '
                 '(עם אותו מספר): שם כתוב מה עושים, מתי, ומי עם מי.</div>{}</div>').format(legend_html(row["intro"]))
    if row["head"] or cont:
        head += '<div class="dayhd">{}{}</div>'.format(esc(row["day"] or "ללא יום"),
                                                       " <small>(המשך)</small>" if cont and not row["head"] else "")
    stacks = "".join('<div class="stack">{}</div>'.format("".join(
        card_html(row["cards"][i], i + 1, row["data"]) for i in st)) for st in row["stacks"])
    return '<tr><td>{}<div class="pair">{}</div></td></tr>'.format(head, stacks)


def duties_html(data, pages, fit=1.0, measure=False, of=None, first=1):
    """דף התורנויות. `pages` = רשימת עמודים, כל עמוד רשימת שורות מ-duties_rows.
    `of`/`first` מאפשרים לרנדר עמוד בודד ועדיין לסמן «עמוד 2 מתוך 3»."""
    total = of or len(pages)
    fixed = measure or fit < 1.0 or total > 1
    sheets = []
    for i, page_rows in enumerate(pages):
        body = "".join(duties_row_html(row, cont=(j == 0 and (i > 0 or first > 1)))
                       for j, row in enumerate(page_rows))
        sheets.append('<div class="page{fixed}"><div class="inner">'
                      '<h1>מי בכל תורנות</h1><div class="when">{when}{part}</div>'
                      '<table class="grid"><tbody>{rows}</tbody></table>'
                      '<footer>מדרשת עין פרת</footer></div></div>'.format(
                          fixed=" fixed" if fixed else "", when=esc(when_line(data)),
                          part=" · עמוד {} מתוך {}".format(first + i, total) if total > 1 else "",
                          rows=body))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{card}{css}:root{{--fit:{fit}}}</style></head><body>
{sheets}{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, card=CARD_CSS, css=DUTIES_CSS, fit=fit,
        sheets="".join(sheets), script=MEASURE_SCRIPT if measure else "")


# ---------------------------------------------------------------------------
# דף לכל תורנות
# ---------------------------------------------------------------------------
def lines_html(text):
    """טקסט משימה: שורה לכל פעולה. שורה ראשונה שנגמרת בנקודתיים — כותרת, והשאר רשימה."""
    lines = [x.strip() for x in (text or "").split("\n") if x.strip()]
    if len(lines) <= 1:
        return esc(lines[0]) if lines else ""
    head = ""
    if lines[0].endswith(":"):
        head, lines = "<b>{}</b>".format(esc(lines[0])), lines[1:]
    return head + "<ul>{}</ul>".format("".join("<li>{}</li>".format(esc(x)) for x in lines))


def ingredients_html(text):
    """שורה לכל מרכיב; שורה שנגמרת בנקודתיים היא כותרת משנה (לבצק / למילוי)."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        out.append("<b>{}</b>".format(esc(line)) if line.endswith(":") else esc(line))
    # <b> הוא בלוק בעצמו — ירידת השורה אחריו רק הייתה מוסיפה שורה ריקה (pre-line)
    return "\n".join(out).replace("</b>\n", "</b>") or "—"


STEP_NUM = re.compile(r"^\d+\s*[.)](?!\d)\s*")    # «3. …» / «3) …» — לא «2.5 כוסות»


def steps_html(text):
    """אופן ההכנה: רשימה ממוספרת. מספור שכבר כתוב בטקסט («1. …») יורד (לא של «2.5 כוסות»). שלב ממוספר שנגמר
    בנקודתיים («4. עיצוב הרצועות:») — שלב עם כותרת, והשורות שאחריו (בלי מספר) מתחתיו; שורה בלי מספר שנגמרת
    בנקודתיים, או שורה קצרה שאחריה טיפים — כותרת משנה; שורה שמתחילה ב-* / • / - — טיפ, ברשימה בלי מספרים."""
    lines = [x.strip() for x in (text or "").split("\n") if x.strip()]
    bullet = lambda x: re.match(r"^[*•\-–]\s*", x)
    out, items, kind, sub = [], [], "ol", None

    def close_sub():
        nonlocal sub
        if sub is not None:
            items[-1] = items[-1].replace("</li>", "<ul>{}</ul></li>".format("".join(sub)), 1) if sub else items[-1]
            sub = None

    def flush():
        close_sub()
        if items:
            out.append("<{0}>{1}</{0}>".format(kind, "".join(items)))
            items.clear()
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        numbered = STEP_NUM.match(line)
        if numbered and line.endswith(":"):                  # שלב עם כותרת, ותתי-שורות אחריו
            if kind != "ol":
                flush()
                kind = "ol"
            close_sub()
            items.append("<li><b>{}</b></li>".format(esc(line[numbered.end():])))
            sub = []
            continue
        if sub is not None and not numbered and not bullet(line) and not line.endswith(":"):
            sub.append("<li>{}</li>".format(esc(line)))
            continue
        close_sub()
        if not numbered and ((line.endswith(":") and len(line) < 40) or
                             (not bullet(line) and bullet(nxt) and len(line) < 30 and not line.endswith("."))):
            flush()
            out.append("<h4>{}</h4>".format(esc(line.rstrip(":") + ":")))
            continue
        b = bullet(line)
        tag, line = ("ul", line[b.end():]) if b else ("ol", STEP_NUM.sub("", line))
        if tag != kind:
            flush()
            kind = tag
        items.append("<li>{}</li>".format(esc(line)))
    flush()
    return "".join(out) or "<p>—</p>"


def recipe_html(recipe):
    """המתכון המלא בדף של התורנות: מצרכים ואופן ההכנה, זה לצד זה."""
    return ('<div class="recipe"><h2>{title}{qty}</h2><div class="cols">'
            '<div class="col ing"><h3>מצרכים</h3><p>{ing}</p></div>'
            '<div class="col"><h3>אופן ההכנה</h3>{steps}</div></div>{note}</div>').format(
        title=esc("מתכון — " + recipe["dish"]),
        qty='<span>כמות: {}</span>'.format(esc(recipe["qty"])) if recipe["qty"] else "",
        ing=ingredients_html(recipe["ingredients"]), steps=steps_html(recipe["steps"]),
        note='<div class="note">{}</div>'.format(esc(recipe["note"])) if recipe["note"] else "")


def slot_pill(card, s, prev_day):
    """(טקסט, מחלקה) לעמודת השעה: השעה; בלי שעה — שעת האירוע, או שמו כשלקבוצה כבר יש שעה סביבו."""
    day = ('<span class="d">{}</span>'.format(esc(s["day"]))
           if len(card["days"]) > 1 and s["day"] and s["day"] != prev_day else "")
    if s["hour"]:
        return day + esc(hhmm(s["hour"])), ""
    ev = s["event"]
    if ev:
        return day + esc(ev["name"] if s.get("timed_here") or not ev["hour"] else hhmm(ev["hour"])), " anchor"
    return day + "ללא שעה", " anchor"


def task_item_html(t, who, kind, gap, alone_event=None):
    tags = []
    if who:
        tags.append('<span class="who {}">{}</span>'.format(kind, esc(who)))
    if gap:
        tags.append('<span class="who note">{}</span>'.format(esc(gap)))
    text = lines_html(t["task"]) or (esc(alone_event) if alone_event else "")
    return '<div class="it"><div class="tx">{text}</div>{tags}{note}</div>'.format(
        text=text, tags='<div>{}</div>'.format(" · ".join(tags)) if tags else "",
        note='<span class="tnote">{}</span>'.format(esc(t["note"])) if t["note"] else "")


def route_rows(card, data):
    """שורות הטבלה של הדף: שעה | מה עושים (ומי, רק כשמתחלקים). קבוצה שעוזרת להכנות — שני חלקים לפי סדר
    הזמנים: מה כולם עושים יחד, והחלוקה להכנות. הכנת מצטרפים בלבד — גם השעות של התורנות שממנה הם באים
    («מתחילים בתורנות…» / «אחר כך — תורנות…»)."""
    rows, prev_day, refs = [], None, []
    if card["joined"]:                         # הכנת מצטרפים: מה עוד הם עושים בתורנות שלהם, במקום שלו בזמן
        source = next((c for c in data["cards"] if c["name"] == card["joined"]), None)
        start = min((s["sort"] for s in card["slots"] if s["hour"]), default=None)
        for s in (source or {}).get("slots", []):
            if not s["hour"] or not s["tasks"]:
                continue
            word = "מתחילים בתורנות" if start is None or s["sort"] < start else "אחר כך — תורנות"
            refs.append((s["sort"], '<tr class="start"><td class="p"><span class="pill">{}</span></td><td><div class="it">'
                         '<div class="tx">{} «{}»: {} — הפירוט בדף שלה</div></div></td></tr>'.format(
                             esc(hhmm(s["hour"])), word, esc(card["joined"]),
                             esc(s["tasks"][0]["task"].split("\n")[0].rstrip(":")))))
    joins = card["joins"]
    entries = [(s["sort"], 1, "slot", s) for s in card["slots"]] + [(k, 0, "ref", html) for k, html in refs]
    for hour, j in joins.items():              # החלוקה להכנות — במקום שלה בזמן (בשבוע של תנורים מ-11:00
        key = (day_index(j["day"]), minutes(hour), -1) if hour else (99, 9999, 9)   # היא לפני הניקיון של 14:00)
        entries.append((key, 0, "split", (hour, j["parts"])))
    entries.sort(key=lambda e: (e[0], e[1]))
    together = True                            # כותרת «כולם יחד» לפני משימות הקבוצה (כשיש גם חלוקה)
    for _, _, kind, x in entries:
        if kind == "ref":
            rows.append(x)
        elif kind == "split":
            hour, parts = x
            rows.append('<tr class="sec"><td colspan="2">{}החלוקה להכנות<small>כל אחד מצטרף להכנה שלו</small>'
                        '</td></tr>'.format(esc(hhmm(hour)) + " · " if hour else ""))
            rows.append('<tr><td class="p"></td><td>{}</td></tr>'.format("".join(
                '<div class="join"><b>{}</b><span>{}{}</span></div>'.format(
                    esc(prep), esc(", ".join(names)) or '<span class="who note">טרם שובצו</span>',
                    ' <span class="k">({})</span>'.format(len(names)) if names else "")
                for prep, names, _ in parts)))
            together = True
        else:
            s = x
            if joins and together:
                rows.append('<tr class="sec"><td colspan="2">{}כולם יחד</td></tr>'.format(
                    esc(hhmm(s["hour"])) + " · " if s["hour"] else ""))
            together = False
            pill, cls = slot_pill(card, s, prev_day)
            prev_day = s["day"] or prev_day
            alone = s["event"]["name"] if s["event"] and not s["hour"] else None
            items = "".join(task_item_html(t, who, k, gap, alone) for t, who, k, gap in s["who"])
            rows.append('<tr><td class="p"><span class="pill{}">{}</span></td><td>{}</td></tr>'.format(cls, pill, items))
    return rows


def flyer_sheet(card, num, data, fit=1.0, fixed=False, part="all"):
    """עמוד של תורנות אחת. part: "all" — הכל; "duty" — בלי המתכון; "recipe" — רק המתכון (עמוד שני)."""
    stage_days = " · ".join(x for x in (card["stage"], " ו".join(card["days"])) if x)
    head = ('<div class="fhead"><span class="n" dir="ltr">{num}</span><h1>{name}</h1></div>'
            '<div class="{sub_cls}">{sub}</div><div class="when">{when}</div>').format(
        num=num, name=esc(card["name"]), sub_cls="rhead" if part == "recipe" else "fsub",
        sub=esc(("מתכון · " if part == "recipe" else "") + stage_days), when=esc(when_line(data)))
    body = ""
    if part in ("all", "duty"):
        joined = joined_text(card, data)
        names = esc(", ".join(card["members"])) if card["members"] else "טרם שובצו"
        body += ('<div class="team"><div class="meta">{count}{lead}</div><div class="names">{names}</div>'
                 '{joined}</div>').format(count=count_text(card), lead=leader_text(card), names=names,
                                          joined='<div class="joined">{}</div>'.format(esc(joined)) if joined else "")
        rows = route_rows(card, data)
        body += ('<table class="route"><colgroup><col class="p"><col></colgroup><tbody>{}</tbody></table>'
                 .format("".join(rows))) if rows else \
            '<div class="empty">אין עדיין משימות לקבוצה</div>'
        if part == "duty" and card["recipes"]:
            body += '<div class="rnext">המתכון ({}) — בעמוד הבא, ובתמונה «{} — מתכון»</div>'.format(
                esc(", ".join(card["recipes"])), esc(card["name"]))
    if part in ("all", "recipe"):
        body += "".join(recipe_html(data["recipes"][d]) for d in card["recipes"])
    return ('<div class="sheet page{fixed}" style="{c};--fit:{fit}"><div class="inner">{head}{body}'
            '<footer>מדרשת עין פרת</footer></div></div>').format(
        fixed=" fixed" if fixed else "", c=colors(card["stage"]), fit=fit, head=head, body=body)


def flyer_html(sheets, measure=False):
    """מסמך של דף תורנות — גיליון אחד או יותר (התורנות, ועמוד מתכון כשהמתכון ארוך)."""
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{card}{css}</style></head><body>
{sheets}{script}</body></html>""".format(
        fonts=font_face_css(), base=BASE_CSS, card=CARD_CSS, css=FLYER_CSS, sheets="".join(sheets),
        script=MEASURE_SCRIPT if measure else "")


RECIPE_MIN_FIT = 0.65   # עמוד מתכון מתכווץ עד כאן; מעבר לזה — ממשיך לעמוד נוסף


def render_flyer(card, num, data, out_dir, png=True):
    """הדף של תורנות: עמוד אחד (מתכווץ עד FLYER_MIN_FIT). לא נכנס ויש מתכון — המתכון עובר לעמוד משלו:
    ה-PDF בשני עמודים, ושתי תמונות: «NN <שם>.png» ו«NN <שם> — מתכון.png». מחזיר את הקבצים שנוצרו."""
    pdf = out_dir / "{}.pdf".format(safe_name(card["name"]))
    image = out_dir / IMAGES / image_name(num, card["name"]) if png else None
    fit = measure_page(flyer_html([flyer_sheet(card, num, data, fixed=True)], measure=True))[0]
    if fit >= FLYER_MIN_FIT or not card["recipes"]:
        fit = fit if fit >= FLYER_MIN_FIT else 1.0          # ארוך מדי לכיווץ סביר ואין מתכון — שני עמודים
        render(flyer_html([flyer_sheet(card, num, data, fit=fit, fixed=fit < 1.0)]), pdf, image)
        return [x for x in (pdf, image) if x]
    fits = []
    for part, low in (("duty", FLYER_MIN_FIT), ("recipe", RECIPE_MIN_FIT)):
        f = measure_page(flyer_html([flyer_sheet(card, num, data, fixed=True, part=part)], measure=True))[0]
        fits.append((part, f if f >= low else 1.0, f >= low))
    sheets = [flyer_sheet(card, num, data, fit=f, fixed=ok, part=part) for part, f, ok in fits]
    render(flyer_html(sheets), pdf)
    made = [pdf]
    if png:
        for (part, f, ok), sheet in zip(fits, sheets):
            out = out_dir / IMAGES / image_name(num, card["name"], recipe=part == "recipe")
            pages = 1 if ok else max(1, render(flyer_html([sheet]), out_dir / ".probe.pdf"))
            render(flyer_html([sheet]), out_png=out, png_pages=pages)
            made.append(out)
        (out_dir / ".probe.pdf").unlink(missing_ok=True)
    return made


# מדידה: כמה העמוד גולש מעמוד אחד, וגובה כל שורת טבלה — כדי לכווץ או לחלק לעמודים.
MEASURE_SCRIPT = """<script>
(function(){
  function report(){
    var page = document.querySelector('.page');
    var inner = document.querySelector('.inner');
    var table = inner.querySelector('table');   // אין טבלה — רק יחס ההתאמה
    var cs = getComputedStyle(page);
    var avail = page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var innerH = inner.getBoundingClientRect().height;
    var heights = [];
    var rows = table ? table.querySelectorAll('tbody tr') : [];
    for (var i = 0; i < rows.length; i++) {
      heights.push(Math.round(rows[i].getBoundingClientRect().height));
    }
    document.title = 'FIT:' + (avail / innerH) +
                     '|AVAIL:' + Math.round(avail) +
                     '|CHROME:' + Math.round(innerH - (table ? table.getBoundingClientRect().height : 0)) +
                     '|ROWS:' + heights.join(',');
  }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""
MIN_FIT = 0.9           # דף התורנויות: מתחת לזה עדיף לחלק לעמודים קריאים מלדחוס עמוד אחד
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
    ap = argparse.ArgumentParser(description="הפקת לו\"ז שבת, דף התורנויות ודף לכל תורנות")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-11")
    ap.add_argument("--only", choices=["flyers", "schedule"],
                    help="flyers — רק הדפים של התורנויות; schedule — רק לו\"ז שבת ודף התורנויות")
    ap.add_argument("--no-png", action="store_true", help="בלי תמונות PNG")
    args = ap.parse_args()

    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    source = ROOT / "shabbatot" / "{}.xlsx".format(d.isoformat())
    if not source.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם tools/new_shabbat.py".format(source))
    data = read_workbook(source)
    cards, _ = duty_cards(data)
    out_dir = ROOT / "shabbatot" / d.isoformat()
    images = out_dir / IMAGES
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in [*out_dir.glob("*.pdf"), *out_dir.glob("*.png"), *out_dir.glob("*.zip"), *images.glob("*.png")]:
        old.unlink()                      # בלי פלטים ישנים מהרצה קודמת (ובלי ה-zip שהיה פעם)
    if args.no_png:
        if images.is_dir() and not any(images.iterdir()):
            images.rmdir()
    else:
        images.mkdir(exist_ok=True)

    made = []
    if args.only != "schedule":
        for num, card in enumerate(cards, 1):
            made += render_flyer(card, num, data, out_dir, png=not args.no_png)
    if args.only != "flyers":
        fit = measure_page(schedule_html(data, measure=True))[0]
        pdf = out_dir / "{}.pdf".format(safe_name(SCHEDULE_NAME))
        png = None if args.no_png else images / image_name(0, SCHEDULE_NAME)
        render(schedule_html(data, fit=fit), pdf, png, png_pages=1)
        made += [x for x in (pdf, png) if x]

        rows = duties_rows(data, cards)
        fit, avail, chrome_h, heights = measure_page(duties_html(data, [rows], measure=True))
        if fit >= MIN_FIT:
            pages = [rows]                # נכנס לעמוד אחד, אולי בכיווץ קל
        else:
            pages, fit = split_pages(rows, heights, avail, chrome_h)
        pdf = out_dir / "{}.pdf".format(DUTIES_NAME)
        render(duties_html(data, pages, fit=fit), pdf)
        made.append(pdf)
        if not args.no_png:               # תמונה לכל עמוד — נוח לשלוח בנפרד
            for i, page_rows in enumerate(pages):
                png = images / image_name(0, DUTIES_NAME if len(pages) == 1 else "{} {}".format(DUTIES_NAME, i + 1))
                render(duties_html(data, [page_rows], fit=fit, of=len(pages), first=i + 1), out_png=png, png_pages=1)
                made.append(png)
        print("  תורנויות: {} עמוד/ים".format(len(pages)))

    for path in made:
        print("  {:<40} {:>8,} bytes".format(str(path.relative_to(out_dir)), path.stat().st_size))
    print("{} קבצים ← {}/{}".format(len(made), out_dir.relative_to(ROOT),
                                   "" if args.no_png else " (התמונות לשליחה ב-{}/)".format(IMAGES)))


if __name__ == "__main__":
    main()
