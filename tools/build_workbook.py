# -*- coding: utf-8 -*-
"""מחולל הגיליון המתכלל (shabbat-planner.xlsx) — מדרשת עין פרת.

    python3 tools/build_workbook.py

הקובץ נבנה מאפס מתוך data/*.csv ומיועד לייבוא לגוגל שיטס (קובץ ← ייבוא), ולכן
משתמש רק בנוסחאות בסיסיות שעובדות גם שם. השימוש השוטף לא דורש את הסקריפט —
מריצים אותו מחדש רק כשמשנים את מבנה הגיליון.

תשעה גיליונות: לוח בקרה · לוז · משימות · קבוצות · חניכים · היסטוריה · מתכונים · קייטרינג · זמנים.
"""
import csv
import re
from datetime import datetime, time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import PageSetupProperties

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "shabbat-planner.xlsx"

# --- שמות גיליונות (בלי גרשיים — בטוח לנוסחאות ולשיטס) ------------------------
SH_DASH, SH_SCHED, SH_TASKS, SH_GROUPS = "לוח בקרה", "לוז", "משימות", "קבוצות"
SH_STUDENTS, SH_HISTORY = "חניכים", "היסטוריה"
SH_RECIPES, SH_CATERING, SH_ZMAN = "מתכונים", "קייטרינג", "זמנים"

# --- כתובות קבועות שסקריפטים אחרים מסתמכים עליהן ------------------------------
SCHED_DATE = "B3"          # תאריך השבת (קלט)
SCHED_CANDLE = "B4"        # כניסת שבת (נוסחה מ«זמנים»)
SCHED_HAVDALAH = "D4"      # צאת שבת (נוסחה מ«זמנים»)
SCHED_HEADER_ROW = 6       # כותרת טבלת הלו"ז; השורות מתחילות מ-7
SCHED_FIRST_ROW = SCHED_HEADER_ROW + 1
SCHED_ROWS = 30            # שורות לו"ז (כולל רזרבה לאירועים שאורי מוסיף)

TASK_FIRST_ROW = 3
TASK_ROWS = 120
GROUP_FIRST_ROW = 3
GROUP_ROWS = 30
STUDENT_FIRST_ROW = 3
STUDENT_ROWS = 130
HISTORY_FIRST_ROW = 3
HISTORY_ROWS = 3000
RECIPE_ROWS = 80
CATERING_ROWS = 50

# עמודות בגיליון «משימות»
(T_STAGE, T_DAY, T_HOUR, T_GROUP, T_TASK, T_PEOPLE, T_NAMES,
 T_RECIPE, T_ANCHOR, T_NOTE) = range(1, 11)
# עמודות בגיליון «קבוצות»
G_NAME, G_STAGE, G_POINTS, G_LEADER, G_MEMBERS, G_SIZE, G_COUNT = range(1, 8)
# עמודות בגיליון «חניכים»
(S_NAME, S_PROGRAM, S_HAVURA, S_AVAILABLE, S_GROUPS, S_TASKS, S_POINTS,
 S_TOTAL, S_NOTE) = range(1, 10)
# עמודות בגיליון «היסטוריה»
H_DATE, H_NAME, H_STAGE, H_GROUP, H_POINTS = range(1, 6)
# עמודות בגיליון «לוז»
L_DAY, L_HOUR, L_EVENT, L_PLACE, L_NOTE, L_SUGGEST, L_TASKS = range(1, 8)

STAGES = ["הכנות שישי", "תורנות שישי", "תורנות שבת", "תורנות מוצ\"ש"]
DAYS = "חמישי,שישי,שבת,מוצאי שבת"
RECIPE_KINDS = "מאפים,עוגות,סלטים,בישול,ארוחת צהריים שישי"
MEALS = "ארוחת ערב,ארוחת צהריים,סלטים,קידוש,סעודה שלישית"
PLACEHOLDER = re.compile(r"\{([^{}|]+)(?:\|([^{}]*))?\}")      # {ארוחה} או {ארוחה|ברירת מחדל}
SHARED_TAG = "[משותפת]"            # הערה שרלוונטית רק בשבת משותפת עם שנה א'
PREP_NOTE = "בסיום — לרשום «שנה ב'» על הנייר כסף / השקית"
PREP_POINTS = 3
DEFAULT_ANCHOR = {"חמישי": "ערב חמישי", "שישי": "תחילת עבודה", "מוצאי שבת": 'ניקיונות מוצ"ש'}
DAY_ORDER = {"חמישי": 0, "שישי": 1, "שבת": 2, "מוצאי שבת": 3}
SCHED_DAY = {"מוצאי שבת": "שבת"}                   # מוצ"ש יושב בלו"ז תחת שבת
SCHED_TITLE_LABEL, SCHED_TITLE = "E4", "F4"         # שם השבת («שבת סטודנטים»), מ-shabbatot.csv

# סוג השבת: משותפת/נפרדת, ובמשותפת — חלון התנורים של שנה ב' (weeks.csv «תנורים»)
OVENS_EARLY, OVENS_LATE = "עד 11:00", "מ-11:00"
FRIDAY_DINING = "ניקיון חדר האוכל בשישי"
FRIDAY_LUNCH = "ארוחת צהריים שישי"
# מי מצטרף להכנות ובאיזו שעה — הכלל הראשון שהתגית שלו בשבוע («» = תמיד)
HELP_RULES = [("תנורים " + OVENS_LATE, FRIDAY_DINING, "+0"),
              ("נפרדת", "בית מדרש", "08:45"),
              ("", "בית מדרש", "10:00")]
# כשהתנורים שלנו מ-11:00 ההכנות זזות ל-11:00, אבל הבישול לארוחת הצהריים מתחיל ב-9:00
LUNCH_RULES = {"תנורים " + OVENS_LATE: ("09:00", "ארוחת צהריים")}

# --- צבעים ------------------------------------------------------------------
INK, MUTED, LINE, BAND = "1F2430", "6B7280", "C9CFD8", "EDF1F6"
ACCENT, INPUT_BG, CALC_BG, SCRIPT_BG = "2E5C8A", "FFF9E3", "EEF3F8", "E3F4F1"
TAB_INPUT, TAB_SCRIPT, TAB_REF = "E8A33D", "3BA48C", "9AA5B1"
LEGEND = "צהוב = ממלאים · טורקיז = הסקריפט כותב · אפור = מחושב"
DAY_FILLS = {"חמישי": "F0F0F0", "שישי": "E8F0F8", "שבת": "F3EDE3", "מוצאי שבת": "EDEAF5"}
FONT = "Arial"


# ---------------------------------------------------------------------------
# עוזרי עיצוב
# ---------------------------------------------------------------------------
def f(size=11, bold=False, color=INK, italic=False):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


def fill(rgb):
    return PatternFill("solid", fgColor=rgb)


def align(h="right", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap, readingOrder=2)


def box(color=LINE, style="thin"):
    s = Side(style=style, color=color)
    return Border(left=s, right=s, top=s, bottom=s)


def q(sheet):
    return "'{}'!".format(sheet)


def page(ws, tab=None):
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    if tab:
        ws.sheet_properties.tabColor = tab


def widths(ws, mapping):
    for col, w in mapping.items():
        ws.column_dimensions[col].width = w


def title_row(ws, row, text, span="A:F", size=18):
    last = span.split(":")[1]
    ws.merge_cells("A{r}:{c}{r}".format(r=row, c=last))
    c = ws["A{}".format(row)]
    c.value = text
    c.font = f(size, bold=True, color=ACCENT)
    c.alignment = align()
    ws.row_dimensions[row].height = size * 2


def header_row(ws, row, headers, fill_rgb=ACCENT):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = f(11, bold=True, color="FFFFFF")
        c.fill = fill(fill_rgb)
        c.alignment = align(h="center", wrap=True)
        c.border = box()
    ws.row_dimensions[row].height = 24


def note_row(ws, row, text, last_col=4):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    c = ws.cell(row=row, column=1, value=text)
    c.font = f(10, color=MUTED, italic=True)
    c.alignment = align(wrap=True)
    ws.row_dimensions[row].height = 28
    return c


def dv_list(ws, source, target, strict=False):
    dv = DataValidation(type="list", formula1=source, allow_blank=True)
    dv.showErrorMessage = strict
    ws.add_data_validation(dv)
    dv.add(target)
    return dv


def read_csv(name):
    with (DATA / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_shabbat(date):
    """השורה של השבת ב-data/shabbatot.csv (השבתות שסגרנו): שם, אנשי צוות, ספר וזמני האתר — או {}."""
    if date is None or not (DATA / "shabbatot.csv").exists():
        return {}
    for r in read_csv("shabbatot.csv"):
        if (r.get("תאריך") or "").strip() == date.isoformat():
            return {k: (v or "").strip() for k, v in r.items()}
    return {}


def read_week(date=None):
    """מה שמשתנה משבת לשבת:

      data/preps/<תאריך>.csv    — ההכנות שהאחראים בחרו (שורה = משימה)
      data/menu/<תאריך>.csv     — מה מוגש בכל ארוחה: קייטרינג, סלטים וחלוקת העוגות
      data/schedule/<תאריך>.csv — שינויים בלו"ז: מי מעביר, אירועים אופציונליים, מקומות
      data/recipes/<תאריך>.csv  — המתכונים של השבוע (גוברים על recipes.csv)
      data/weeks.csv             — שורה לכל שבת: משותפת עם שנה א', וחלון התנורים שלנו
      data/shabbatot.csv         — שם השבת, אנשי הצוות, הספר וזמני האתר

    בלי תאריך (התבנית) — הכול ריק ושבת «רק אנחנו»."""
    week = {"preps": [], "menu": [], "schedule": [], "recipes": [], "shared": False, "ovens": "", "info": {}}
    if date is None:
        return week
    iso = date.isoformat()
    for key in ("preps", "menu", "schedule", "recipes"):
        path = DATA / key / "{}.csv".format(iso)
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as fh:
                week[key] = [{k: v for k, v in r.items() if k} for r in csv.DictReader(fh)
                             if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    if (DATA / "weeks.csv").exists():
        for r in read_csv("weeks.csv"):
            if (r.get("תאריך") or "").strip() == iso:
                week["shared"] = (r.get("שבת משותפת") or "").strip() == "כן"
                week["ovens"] = (r.get("תנורים") or "").strip()
    week["info"] = read_shabbat(date)
    return week


# ---------------------------------------------------------------------------
# סוג השבת — תגיות, ועמודת «תנאי» בתבנית הלו"ז, בספריית המשימות ובקבוצות
# ---------------------------------------------------------------------------
def tags_for(shared, ovens="", on=(), optional=()):
    """התגיות של שבוע: משותפת/נפרדת, חלון התנורים, ולכל אירוע אופציונלי — שמו או «בלי <שם>».

    «תנורים כל היום» = שבת נפרדת, או משותפת שלא נקבע בה חלון (כמו 18.9)."""
    tags = {"משותפת" if shared else "נפרדת"}
    ovens = (ovens or "").strip() if shared else ""
    tags.add("תנורים " + ovens if ovens in (OVENS_EARLY, OVENS_LATE) else "תנורים כל היום")
    for name in optional:
        tags.add(name if name in on else "בלי " + name)
    return tags


def applies(cond, tags):
    """«תנאי» ריק = תמיד; אחרת רשימה מופרדת ב-; ומספיק שאחת מהתגיות מתקיימת."""
    parts = [c.strip() for c in (cond or "").split(";") if c.strip()]
    return not parts or any(c in tags for c in parts)


def prep_day(p):
    return (p.get("יום") or "").strip() or "שישי"


def prep_anchor(p, tags=()):
    """העוגן של שורת הכנה: המפורש, ואם אין — לפי היום (ארוחת צהריים שישי לפי LUNCH_RULES)."""
    explicit = (p.get("עוגן") or "").strip()
    if explicit:
        return explicit
    day = prep_day(p)
    if (p.get("הכנה") or "").strip() == FRIDAY_LUNCH and day == "שישי" and not (p.get("שעה") or "").strip():
        for tag, (_, anchor) in LUNCH_RULES.items():
            if tag in tags:
                return anchor
    return DEFAULT_ANCHOR.get(day, "")


def _optional(template):
    return [(r["יום"], r["אירוע"]) for r in template if (r.get("אופציונלי") or "").strip() == "כן"]


def week_schedule(week):
    """שורות data/schedule/<תאריך>.csv לפי סדר ההחלה: קודם של הטופס («מקור=טופס»), ואז הידניות —
    כך שורה שאורי הוסיף גוברת על הטופס; ו-{(יום, אירוע)} שבוטלו («פעולה=בטל») — ביטול גובר תמיד."""
    rows = [{k: (v or "").strip() for k, v in w.items() if isinstance(v, str)} for w in week["schedule"]]
    rows = [w for w in rows if w.get("יום") and w.get("אירוע")]
    rows = [w for w in rows if w.get("מקור") == "טופס"] + [w for w in rows if w.get("מקור") != "טופס"]
    cancelled = {(w["יום"], w["אירוע"]) for w in rows if w.get("פעולה") == "בטל"}
    return rows, cancelled


def _optional_on(week, template, all_on=False):
    """האירועים האופציונליים שפעילים השבוע: מופיעים בקובץ הלו"ז של השבוע, או שהכנה מעוגנת אליהם
    — ולא בוטלו."""
    opt = _optional(template)
    if all_on:
        return set(opt)
    rows, cancelled = week_schedule(week)
    listed = {(w["יום"], w["אירוע"]) for w in rows}
    anchored = {(SCHED_DAY.get(prep_day(p), prep_day(p)), prep_anchor(p)) for p in week["preps"]
                if (p.get("הכנה") or "").strip()}
    return {k for k in opt if (k in listed or k in anchored) and k not in cancelled}


def week_tags(date=None, week=None, all_optional=False):
    week = read_week(date) if week is None else week
    template = read_schedule_template()
    on = {name for _, name in _optional_on(week, template, all_optional)}
    return tags_for(week["shared"], week["ovens"], on, [name for _, name in _optional(template)])


# ---------------------------------------------------------------------------
# מתכונים
# ---------------------------------------------------------------------------
RECIPE_FIELDS = ["קטגוריה", "מנה", "כמות", "מרכיבים", "הוראות", "הערה"]


def recipe_rows(date=None):
    """recipes.csv, כשגרסת השבוע (data/recipes/<תאריך>.csv) של מנה מחליפה אותה במקומה."""
    base = read_csv("recipes.csv") if (DATA / "recipes.csv").exists() else []
    week = {r["מנה"].strip(): r for r in read_week(date)["recipes"] if (r.get("מנה") or "").strip()}
    rows = [week.pop(r["מנה"].strip(), r) for r in base if (r.get("מנה") or "").strip()]
    rows += list(week.values())
    if len(rows) > RECIPE_ROWS:
        raise SystemExit("✗ {} מתכונים — יותר מ-{} שורות בגיליון «מתכונים». להגדיל את RECIPE_ROWS."
                         .format(len(rows), RECIPE_ROWS))
    return rows


def match_recipe(name, names):
    """שם המנה כפי שמופיע במתכונים: זהה, או הכלה יחידה («סלט כרוב» → «סלט כרוב מרענן»)."""
    name = (name or "").strip()
    if not name:
        return None
    if name in names:
        return name
    hits = [n for n in names if name in n or n in name]
    return hits[0] if len(hits) == 1 else None


def _recipe_list(text, names, warn):
    """«א;ב» → רק מנות שיש להן מתכון השבוע (השאר נשארות בטקסט המשימה)."""
    out = []
    for dish in (d.strip() for d in (text or "").split(";")):
        if not dish:
            continue
        match = match_recipe(dish, names)
        if match:
            out.append(match)
        elif warn:
            print("⚠ אין מתכון ל«{}» — הפלייר יוצג בלי המצרכים שלו".format(dish))
    return ";".join(dict.fromkeys(out))


def expand_catering(text, menu, warn=True, sep=", "):
    """מחליף {ארוחה} ברשימת המנות של אותה ארוחה בתפריט השבוע.

    {ארוחה|ברירת מחדל} — אם אין לארוחה מנות, נכתבת ברירת המחדל («חימום {טיש|העוגות}»).
    בלי ברירת מחדל ובלי מנות — הסוגריים נשארים גלויים ומודפסת אזהרה, כדי ששום דבר
    לא ייעלם בשקט (ו-shabbat.py נכשל עליהם). בעמודת המתכון sep=";"."""
    if not text or "{" not in text:
        return text
    def sub(m):
        meal, default = m.group(1).strip(), m.group(2)
        dishes = [r["מנה"].strip() for r in menu
                  if (r.get("ארוחה") or "").strip() == meal and (r.get("מנה") or "").strip()]
        if dishes:
            return sep.join(dishes)
        if default is not None:
            return default
        if warn:
            print("⚠ אין בתפריט מנות ל«{}» — המשימה: {}".format(meal, text[:50]))
        return m.group(0)
    return PLACEHOLDER.sub(sub, text)


def expand_info(text, info):
    """{ספר} / {שם} בלו"ז — מהשורה של השבת ב-shabbatot.csv (ברירת המחדל אחרי |, או ריק)."""
    if not text or "{" not in text:
        return text
    return PLACEHOLDER.sub(lambda m: info.get(m.group(1).strip()) or (m.group(2) or ""), text)


def _note(note, shared):
    """הערה שמתחילה ב-[משותפת] נשארת רק בשבת משותפת."""
    note = (note or "").strip()
    if note.startswith(SHARED_TAG):
        return note[len(SHARED_TAG):].strip() if shared else ""
    return note


def _hour(text):
    text = (text or "").strip()
    if text[:1] in "+-":
        return text
    return "{:02d}:{}".format(int(text.split(":")[0]), text.split(":")[1]) if text else ""


def plan_rows(date=None):
    """הקבוצות לשבת: קבוצות ההכנה של השבוע (לפי סדר הופעתן), ואחריהן הקבוצות הקבועות
    שפעילות בסוג השבת הזה («תנאי») ויש להן משימות השבוע."""
    week = read_week(date)
    tags = week_tags(date, week)
    standing = read_csv("group_plan.csv")
    known = {r["קבוצה"] for r in standing}
    new = []
    for p in week["preps"]:
        name = (p.get("הכנה") or "").strip()
        if name and name not in known and name not in [g["קבוצה"] for g in new]:
            new.append({"קבוצה": name, "שלב": STAGES[0], "ניקוד": str(PREP_POINTS),
                        "אחראי מצוות": "", "מוביל/ה": "", "חברים קבועים": ""})
    standing = [r for r in standing if applies(r.get("תנאי"), tags)]
    if date is not None:
        used = {r["קבוצה"] for r in task_rows(date, warn=False)}
        standing = [r for r in standing if r["קבוצה"] in used]
    return new + standing


def week_leaders(date=None):
    """{הכנה: אחראי/ת} מקובץ ההכנות — השורה הראשונה שיש בה שם."""
    leaders = {}
    for p in read_week(date)["preps"]:
        name, who = (p.get("הכנה") or "").strip(), (p.get("אחראי") or "").strip()
        if name and who:
            leaders.setdefault(name, who)
    return leaders


def _task_key(group, day, hour, anchor):
    return (group, day, _hour(hour), anchor)


def task_rows(date=None, times=None, warn=True):
    """כל משימות השבת: ההכנות של השבוע, ואחריהן המשימות הקבועות מ-task_library.csv.

    רק קבוצות ומשימות שה«תנאי» שלהן מתקיים בסוג השבת. שורת הכנה של קבוצה קבועה מחליפה
    את המשימה הקבועה עם אותו (קבוצה, יום, שעה, עוגן), ויורשת ממנה את מה שחסר בה.
    «עזרה = N» מוסיף משימת הצטרפות להכנה לפי HELP_RULES, מיד אחרי משימות הקבוצה שעוזרת.
    מצייני המקום מתמלאים מהתפריט (גם בעמודת המתכון), הערות [משותפת] נשארות רק בשבת משותפת,
    ומשימה שהעוגן שלה הוא אירוע שלא מתקיים השבוע (סעודה שלישית, ערב חברה) נופלת.
    שעה יחסית («-30») מחושבת מזמן אירוע העוגן: times = {(יום, אירוע): time}."""
    week = read_week(date)
    tags = week_tags(date, week)
    say = warn and date is not None
    plan = read_csv("group_plan.csv")
    stage_of = {r["קבוצה"]: r["שלב"] for r in plan}
    off = {r["קבוצה"] for r in plan if not applies(r.get("תנאי"), tags)}
    library = [r for r in read_csv("task_library.csv")
               if r["קבוצה"] not in off and applies(r.get("תנאי"), tags)]
    by_key = {}
    for r in library:
        by_key.setdefault(_task_key(r["קבוצה"], r["יום"], r["שעה"], r["עוגן"]), r)
    help_group, help_hour = next((g, h) for tag, g, h in HELP_RULES if not tag or tag in tags)
    ovens = next((t for t in tags if t in ("תנורים " + OVENS_EARLY, "תנורים " + OVENS_LATE)), "")
    prep_note = " · ".join(x for x in (PREP_NOTE, ovens.replace("תנורים", "התנורים שלנו", 1)) if x)

    preps, helpers, taken = [], [], set()
    for p in week["preps"]:
        name = (p.get("הכנה") or "").strip()
        if not name:
            continue
        if name in off:
            if say:
                print("⚠ «{}» לא פעילה בשבת כזו — השורה שלה בקובץ ההכנות לא נכנסת".format(name))
            continue
        day = prep_day(p)
        anchor = prep_anchor(p, tags)
        hour = _hour(p.get("שעה"))
        if not hour and name == FRIDAY_LUNCH and day == "שישי":
            hour = next((h for tag, (h, _) in LUNCH_RULES.items() if tag in tags), "")
        if not hour and day == "שישי":
            hour = "+0"                                  # עם תחילת העבודה (08:00, או 11:00)
        stage = stage_of.get(name, STAGES[0])
        qty = (p.get("כמות") or "").strip()
        base = by_key.get(_task_key(name, day, hour, anchor), {})
        if not base and (p.get("שעה") or "").strip() and not (p.get("עוגן") or "").strip():
            base = next((r for r in library if r["קבוצה"] == name and r["יום"] == day      # (קבוצה, יום, שעה)
                         and _hour(r["שעה"]) == hour), {})                                    # כמו פעם — והעוגן
            anchor = base.get("עוגן") or anchor                                               # עובר בירושה
        text = (p.get("משימה") or "").strip() or ("{} — {}".format(name, qty) if qty else "") \
            or base.get("משימה") or name
        note = (p.get("הערה") or "").strip() or _note(base.get("הערה"), week["shared"])
        if week["shared"] and stage == STAGES[0] and day == "שישי":
            note = " · ".join(x for x in (prep_note, note) if x)
        preps.append({"שלב": stage, "יום": day, "שעה": hour, "קבוצה": name, "משימה": text,
                      "אנשים": (p.get("אנשים") or "").strip() or base.get("אנשים", ""),
                      "מתכון": (p.get("מתכון") or "").strip() or base.get("מתכון", ""),
                      "עוגן": anchor, "הערה": note})
        taken.add(_task_key(name, day, hour, anchor))
        helpers_n = (p.get("עזרה") or p.get("עזרה מבית המדרש") or "").strip()
        if helpers_n and helpers_n != "0":
            if help_group in off:
                print("⚠ «{}» לא פעילה השבוע — אין מי שיצטרף ל«{}»".format(help_group, name))
                continue
            helpers.append({"שלב": stage_of.get(help_group, STAGES[1]), "יום": "שישי", "שעה": help_hour,
                            "קבוצה": help_group, "משימה": "עזרה בהכנת {}".format(name), "אנשים": helpers_n,
                            "מתכון": "", "עוגן": "תחילת עבודה", "הערה": ""})

    standing = [dict(r, הערה=_note(r.get("הערה"), week["shared"])) for r in library
                if _task_key(r["קבוצה"], r["יום"], r["שעה"], r["עוגן"]) not in taken]
    rows = preps + standing                              # העזרה — מיד אחרי המשימות של הקבוצה שעוזרת
    last = max((i for i, r in enumerate(rows) if r["קבוצה"] == help_group), default=len(rows) - 1)
    rows = rows[:last + 1] + helpers + rows[last + 1:]

    active = known = None
    if date is not None:
        events = schedule_rows(date, week=week)
        active = {(r["יום"], r["אירוע"]) for r in events}
        known = {(r["יום"], r["אירוע"]) for r in read_schedule_template()} | active
    names = {r["מנה"].strip() for r in recipe_rows(date)}
    out = []
    for r in rows:
        key = (SCHED_DAY.get(r["יום"], r["יום"]), r["עוגן"])
        if active is not None and r["עוגן"] and key in known and key not in active:
            continue                                     # אירוע שלא מתקיים השבוע
        r["משימה"] = expand_catering(r["משימה"], week["menu"], warn=say)
        r["מתכון"] = _recipe_list(expand_catering(r.get("מתכון") or "", week["menu"], warn=say, sep=";"),
                                  names, say)
        r["שעה"] = resolve_hour(r["שעה"], (times or {}).get(key))
        out.append(r)
    return out


def write_task_row(ws, r, row):
    """שורה בגיליון «משימות» — גם בתבנית וגם בקובץ השבת."""
    get = lambda k: (row.get(k) or None) if row else None
    data_cell(ws, r, T_STAGE, get("שלב"), center=True)
    data_cell(ws, r, T_DAY, get("יום"), center=True)
    data_cell(ws, r, T_HOUR, as_time(row["שעה"]) if row and row.get("שעה") else None,
              center=True, bold=True, fmt="hh:mm")
    data_cell(ws, r, T_GROUP, get("קבוצה"))
    data_cell(ws, r, T_TASK, get("משימה"), wrap=True)
    data_cell(ws, r, T_PEOPLE, int(row["אנשים"]) if row and row.get("אנשים") else None, center=True)
    names = data_cell(ws, r, T_NAMES, None, wrap=True)
    names.fill = fill(SCRIPT_BG)
    data_cell(ws, r, T_RECIPE, get("מתכון"))
    data_cell(ws, r, T_ANCHOR, get("עוגן"))
    data_cell(ws, r, T_NOTE, get("הערה"), wrap=True)
    if row and row.get("יום"):
        ws.cell(row=r, column=T_DAY).fill = fill(DAY_FILLS.get(row["יום"], BAND))
    ws.row_dimensions[r].height = 30 if row else 18


def write_group_row(ws, r, row):
    data_cell(ws, r, G_NAME, row["קבוצה"] if row else None, bold=True)
    data_cell(ws, r, G_STAGE, (row["שלב"] or None) if row else None, center=True)
    data_cell(ws, r, G_POINTS, int(row["ניקוד"]) if row and row.get("ניקוד") else None, center=True)
    ws.row_dimensions[r].height = 30 if row else 18


def write_menu_row(ws, r, row):
    get = lambda k: (row.get(k) or None) if row else None
    data_cell(ws, r, 1, get("ארוחה"), center=True)
    data_cell(ws, r, 2, get("מנה"))
    data_cell(ws, r, 3, get("כמות"), center=True)
    data_cell(ws, r, 4, get("הערה"), wrap=True)


def as_time(text):
    h, m = text.split(":")
    return time(int(h), int(m))


def data_cell(ws, row, col, value=None, editable=True, wrap=False, center=False,
              bold=False, size=11, fmt=None):
    c = ws.cell(row=row, column=col)
    c.value = value                  # גם None — ws.cell(value=None) לא מוחק ערך קיים
    c.border = box()
    c.alignment = align(h="center" if center else "right", wrap=wrap, v="top" if wrap else "center")
    c.font = f(size, bold=bold)
    if editable:
        c.fill = fill(INPUT_BG)
    if fmt:
        c.number_format = fmt
    return c


# ---------------------------------------------------------------------------
# כללי הלו"ז — מקור יחיד: data/schedule_template.csv
# ---------------------------------------------------------------------------
def read_schedule_template():
    return read_csv("schedule_template.csv")


def _mins(t):
    return t.hour * 60 + t.minute


def _round(total, row):
    """עיגול דקות: «עיגול» בתבנית = עיגול כלפי מעלה לכפולה שלו (15 → לרבע השעה הבאה);
    בלי עיגול — לחמש הדקות הקרובות, כשיש היסט."""
    step = int((row.get("עיגול") or "0").strip() or 0)
    if step:
        return -(-total // step) * step
    return (total + 2) // 5 * 5 if int(row["היסט"]) else total


def suggested_time(row, candle, havdalah, known=None):
    """הזמן המוצע לשורת תבנית, כאובייקט time (או None כשאין עוגן).

    «בסיס»: קבוע · כניסה · צאה · או שם של אירוע אחר באותו יום (טיש = סעודת שבת + 90),
    שהזמן שלו כבר חושב ב-known = {(יום, אירוע): time}. «לא לפני» = רצפה (סעודה לא לפני 19:00)."""
    base, offset = row["בסיס"].strip(), row["היסט"].strip()
    if base == "קבוע":
        return as_time(offset)
    if base == "כניסה":
        anchor = candle
    elif base == "צאה":
        anchor = havdalah
    else:
        anchor = (known or {}).get((row["יום"], base))
    if anchor is None:
        return None
    total = _round(_mins(anchor) + int(offset), row)
    floor = (row.get("לא לפני") or "").strip()
    if floor:
        total = max(total, _mins(as_time(floor)))
    return time((total // 60) % 24, total % 60)


SCHED_FIELDS = ["יום", "אירוע", "מקום", "בסיס", "היסט", "עיגול", "לא לפני", "הערה"]


def schedule_rows(date=None, candle=None, havdalah=None, optional=False, week=None):
    """הלו"ז של השבת, כרשימת שורות עם «שעה» מחושבת (time או None).

    תבנית (data/schedule_template.csv) לפי סוג השבת («תנאי»), בלי אירועים אופציונליים
    שלא הודלקו; ואז data/schedule/<תאריך>.csv: שורה עם אותו (יום, אירוע) מדליקה אותו
    ודורסת את השדות שאינם ריקים, «פעולה=בטל» מוחקת, ושורה חדשה היא אירוע חדש.
    {ספר} / {שם} מתמלאים מ-shabbatot.csv. הזמנים מחושבים לפי סדר ההגדרה (כך אירוע נשען
    על קודמו), ואז הכול ממוין לפי יום ושעה. optional=True — כל האופציונליים דולקים."""
    week = read_week(date) if week is None else week
    template = read_schedule_template()
    on = _optional_on(week, template, optional)
    tags = tags_for(week["shared"], week["ovens"], {n for _, n in on}, [n for _, n in _optional(template)])
    rows = []
    for r in template:
        key = (r["יום"], r["אירוע"])
        if not applies(r.get("תנאי"), tags) or ((r.get("אופציונלי") or "").strip() == "כן" and key not in on):
            continue
        rows.append({k: (r.get(k) or "").strip() for k in SCHED_FIELDS})
    week_rows, cancelled = week_schedule(week)
    rows = [r for r in rows if (r["יום"], r["אירוע"]) not in cancelled]
    for w in week_rows:
        key = (w["יום"], w["אירוע"])
        if key in cancelled:
            continue
        hit = next((r for r in rows if (r["יום"], r["אירוע"]) == key), None)
        if hit is None:
            if not w.get("בסיס") or not w.get("היסט"):
                print("⚠ «{}» בלו\"ז של השבוע בלי שעה (בסיס + היסט) — לא נכנס".format(key[1]))
                continue
            hit = {k: "" for k in SCHED_FIELDS}
            rows.append(hit)
        for k in SCHED_FIELDS:
            if w.get(k):
                hit[k] = w[k]
    have = {(r["יום"], r["אירוע"]) for r in rows}
    for r in rows:
        if r["בסיס"] not in ("קבוע", "כניסה", "צאה") and (r["יום"], r["בסיס"]) not in have:
            raise SystemExit("✗ «{}» נשען על «{}», שלא מתקיים השבוע (data/schedule/{}.csv)".format(
                r["אירוע"], r["בסיס"], date.isoformat() if date else "—"))
    known = {}
    for r in rows:
        r["מקום"], r["הערה"] = expand_info(r["מקום"], week["info"]), expand_info(r["הערה"], week["info"])
        r["שעה"] = known[(r["יום"], r["אירוע"])] = suggested_time(r, candle, havdalah, known)
    return [r for _, r in sorted(enumerate(rows), key=lambda ir: (event_sort_key(ir[1]["יום"], ir[1]["שעה"]), ir[0]))]


def event_sort_key(day, t):
    """(יום, בלי שעה בסוף היום, שעה) — שעה לפני 05:00 נחשבת אחרי חצות."""
    m = None if t is None else _mins(t) + (1440 if _mins(t) < 300 else 0)
    return (DAY_ORDER.get(day, 9), m is None, m or 0)


def active_events(date=None):
    """{(יום, אירוע)} שמתקיימים בשבת הזו — בלי תלות בשעות."""
    return {(r["יום"], r["אירוע"]) for r in schedule_rows(date)}


def event_times(candle, havdalah, date=None):
    """{(יום, אירוע): time} ללו"ז של השבת — כך משימה יחסית («-30») יודעת מתי העוגן שלה."""
    return {(r["יום"], r["אירוע"]): r["שעה"] for r in schedule_rows(date, candle, havdalah)}


def suggestion_formula(row, row_of=None):
    """נוסחת ההצעה לאותה שורה, לעדכון אוטומטי כשמחליפים תאריך בשיטס.
    row_of = {(יום, אירוע): מספר שורה בגיליון} — לבסיס שהוא אירוע אחר."""
    base, offset = row["בסיס"].strip(), row["היסט"].strip()
    if base == "קבוע":
        return as_time(offset)
    if base == "כניסה":
        ref = "$" + SCHED_CANDLE[0] + "$" + SCHED_CANDLE[1:]
    elif base == "צאה":
        ref = "$" + SCHED_HAVDALAH[0] + "$" + SCHED_HAVDALAH[1:]
    else:
        ref = "${}${}".format(col_letter(L_SUGGEST), (row_of or {})[(row["יום"], base)])
    minutes = int(offset)
    step = int((row.get("עיגול") or "0").strip() or 0)
    floor = (row.get("לא לפני") or "").strip()
    sign = "+" if minutes >= 0 else "-"
    expr = "{r}{s}TIME({h},{m},0)".format(r=ref, s=sign, h=abs(minutes) // 60, m=abs(minutes) % 60)
    if step:                                   # כלפי מעלה: ROUNDUP על דקות שלמות (בלי CEILING על זמן)
        core = "ROUNDUP(ROUND(({e})*1440,0)/{s},0)*{s}/1440".format(e=expr, s=step)
    elif minutes:
        core = "ROUND(({e})*288,0)/288".format(e=expr)
    else:
        core = ref
    if floor:                                  # בתוך ה-IF: בלי תאריך — ריק, לא ‎#VALUE!
        t = as_time(floor)
        core = "MAX(TIME({h},{m},0),{c})".format(h=t.hour, m=t.minute, c=core)
    return '=IF({r}="","",{c})'.format(r=ref, c=core)


def write_sched_row(ws, r, row, row_of, hour=True):
    """שורה בגיליון «לוז» — גם בתבנית (hour=False: בלי שעה סטטית) וגם בקובץ השבת."""
    day = row["יום"] if row else None
    data_cell(ws, r, L_DAY, day, center=True, bold=True)
    data_cell(ws, r, L_HOUR, row.get("שעה") if row and hour else None, center=True, bold=True, size=12,
              fmt="hh:mm")
    data_cell(ws, r, L_EVENT, row["אירוע"] if row else None, bold=True)
    data_cell(ws, r, L_PLACE, (row["מקום"] or None) if row else None)
    data_cell(ws, r, L_NOTE, (row["הערה"] or None) if row else None, wrap=True)
    sug = calc_cell(ws, r, L_SUGGEST, suggestion_formula(row, row_of) if row else None, fmt="hh:mm")
    sug.font = f(10, color=MUTED)
    calc_cell(ws, r, L_TASKS, '=IF(C{r}="","",COUNTIF({t},C{r}))'.format(r=r, t=T(T_ANCHOR)))
    if day:
        ws.cell(row=r, column=L_DAY).fill = fill(DAY_FILLS.get(day, BAND))
    ws.row_dimensions[r].height = 22


def write_schedule(ws, rows, hour=True):
    """כל שורות הלו"ז (SCHED_ROWS), עם ניקוי שאריות — מקור אחד לתבנית ולקובץ השבת."""
    if len(rows) > SCHED_ROWS:
        raise SystemExit("✗ {} אירועים — יותר מ-{} שורות בגיליון «לוז»".format(len(rows), SCHED_ROWS))
    row_of = {(t["יום"], t["אירוע"]): SCHED_FIRST_ROW + i for i, t in enumerate(rows)}
    for i in range(SCHED_ROWS):
        write_sched_row(ws, SCHED_FIRST_ROW + i, rows[i] if i < len(rows) else None, row_of, hour)


def resolve_hour(text, anchor_time):
    """שעת משימה: «19:30» קבועה, או «-30» / «+0» יחסית לאירוע העוגן (עיגול ל-5 דקות).
    יחסית בלי זמן לעוגן (בתבנית) → ריק."""
    text = (text or "").strip()
    if not text or text[0] not in "+-":
        return text
    if anchor_time is None:
        return ""
    total = (_mins(anchor_time) + int(text) + 2) // 5 * 5
    return "{:02d}:{:02d}".format((total // 60) % 24, total % 60)


# ---------------------------------------------------------------------------
# זמני השבת — zmanim.csv (חישוב), וזמני האתר מ-shabbatot.csv גוברים
# ---------------------------------------------------------------------------
def read_zmanim():
    """[{תאריך (date), פרשה, כניסת שבת, צאת שבת, מקור}] לכל שבת בלוח."""
    site = {}
    if (DATA / "shabbatot.csv").exists():
        for r in read_csv("shabbatot.csv"):
            if (r.get("כניסת שבת") or "").strip() and (r.get("צאת שבת") or "").strip():
                site[r["תאריך"].strip()] = (r["כניסת שבת"].strip(), r["צאת שבת"].strip())
    rows = []
    for r in read_csv("zmanim.csv"):
        d = datetime.strptime(r["תאריך"], "%d/%m/%Y").date()
        candle, havdalah, source = r["כניסת שבת"], r["צאת שבת"], "חישוב (ירושלים)"
        if d.isoformat() in site:
            (candle, havdalah), source = site[d.isoformat()], "אתר ישיבה (כפר אדומים)"
        rows.append({"תאריך": d, "פרשה": r["פרשה"], "כניסת שבת": candle, "צאת שבת": havdalah, "מקור": source})
    return rows


def zmanim_for(date):
    return next((z for z in read_zmanim() if z["תאריך"] == date), None)


# ---------------------------------------------------------------------------
# עוזרי טווחים (בנוסחאות)
# ---------------------------------------------------------------------------
def col_letter(n):
    return chr(64 + n)


def rng(sheet, col, first, count):
    return "{}${c}${a}:${c}${b}".format(q(sheet), c=col_letter(col), a=first, b=first + count - 1)


T = lambda col: rng(SH_TASKS, col, TASK_FIRST_ROW, TASK_ROWS)
S = lambda col: rng(SH_STUDENTS, col, STUDENT_FIRST_ROW, STUDENT_ROWS)
G = lambda col: rng(SH_GROUPS, col, GROUP_FIRST_ROW, GROUP_ROWS)
H = lambda col: rng(SH_HISTORY, col, HISTORY_FIRST_ROW, HISTORY_ROWS)
L = lambda col: rng(SH_SCHED, col, SCHED_FIRST_ROW, SCHED_ROWS)


def calc_cell(ws, row, col, formula, center=True, bold=False, size=11, fmt=None, bg=CALC_BG):
    c = data_cell(ws, row, col, formula, editable=False, center=center, bold=bold, size=size, fmt=fmt)
    c.fill = fill(bg)
    return c


# ---------------------------------------------------------------------------
# גיליון: לוח בקרה — דף הפתיחה
# ---------------------------------------------------------------------------
STEPS = [
    ("1", "«לוז» — בוחרים תאריך, מתקנים שעות ומקומות. «הצעה» מתעדכנת לבד; «שעה» היא מה שנשלח."),
    ("2", "«משימות» — לכל משימה: שלב, יום, שעה, קבוצה, כמה אנשים, מתכון (לצוות הכנה) ועוגן בלו\"ז."),
    ("3", "python3 tools/assign_groups.py <תאריך> — ממלא «שמות», «קבוצות», «חניכים» ו«היסטוריה»."),
    ("4", "python3 tools/export_pdf.py <תאריך> — לו\"ז צל + פלייר לכל קבוצת עבודה. ערכת בשיטס? הורד כ-xlsx והרץ שוב."),
]

STATUS = [
    ("נוכחים השבת", '=COUNTIF({c},"כן")+COUNTIF({c},"לא")', "מתוך רשימת הנוכחות"),
    ("זמינים לתורנות", '=COUNTIF({c},"כן")', ""),
    ("בתורנות", '=COUNTA({g})', "חניכים עם קבוצה אחת לפחות"),
    ("זמינים בלי תורנות", '=COUNTIFS({c},"כן",{g},"")', ""),
    ("משימות", '=COUNTA({t})', ""),
    ("משימות בלי שמות", '=COUNTA({t})-COUNTA({n})', "להריץ שיבוץ, או להשלים ידנית"),
    ("משימות בלי עוגן", '=COUNTA({t})-COUNTA({a})', "לא יופיעו ליד אירוע בלו\"ז הצל"),
    ("קבוצות עבודה", '=COUNTA({gr})', "פלייר לכל אחת"),
]


def build_dashboard(wb):
    ws = wb.create_sheet(SH_DASH)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 26, "B": 14, "C": 44, "D": 4, "E": 70})
    title_row(ws, 1, "הכנת שבת — מדרשת עין פרת", span="A:E", size=20)
    sub = ws.cell(row=2, column=1, value=LEGEND)
    sub.font = f(10, color=MUTED, italic=True)
    sub.alignment = align()
    ws.merge_cells("A2:E2")

    z = q(SH_SCHED)
    for r, label, formula, fmt in (
            (4, "שבת", "=IF({z}{d}=\"\",\"— בחר תאריך ב«לוז» —\",{z}{d})".format(z=z, d=SCHED_DATE), "dd/mm/yyyy"),
            (5, "כניסת שבת", "={z}{c}".format(z=z, c=SCHED_CANDLE), "hh:mm"),
            (6, "צאת שבת", "={z}{h}".format(z=z, h=SCHED_HAVDALAH), "hh:mm")):
        lab = ws.cell(row=r, column=1, value=label)
        lab.font = f(11, bold=True)
        lab.alignment = align()
        lab.fill = fill(BAND)
        lab.border = box()
        calc_cell(ws, r, 2, formula, bold=True, size=12, fmt=fmt)
        ws.row_dimensions[r].height = 22

    header_row(ws, 8, ["מצב ההכנה", "", "הערה"])
    ws.merge_cells("A8:B8")
    refs = {"c": S(S_AVAILABLE), "g": S(S_GROUPS), "t": T(T_TASK), "n": T(T_NAMES),
            "a": T(T_ANCHOR), "gr": G(G_NAME)}
    for i, (label, formula, note) in enumerate(STATUS):
        r = 9 + i
        lab = ws.cell(row=r, column=1, value=label)
        lab.font = f(11, bold=True)
        lab.alignment = align()
        lab.fill = fill(BAND)
        lab.border = box()
        calc_cell(ws, r, 2, formula.format(**refs), bold=True, size=12)
        n = ws.cell(row=r, column=3, value=note or None)
        n.font = f(10, color=MUTED, italic=True)
        n.alignment = align()
        n.border = box()
        ws.row_dimensions[r].height = 22

    head = ws.cell(row=4, column=5, value="סדר העבודה")
    head.font = f(13, bold=True, color=ACCENT)
    head.alignment = align()
    for i, (key, text) in enumerate(STEPS):
        r = 5 + i
        k = ws.cell(row=r, column=4, value=key)
        k.font = f(11, bold=True, color=ACCENT)
        k.alignment = align(h="center", v="top")
        t = ws.cell(row=r, column=5, value=text)
        t.font = f(11)
        t.alignment = align(v="top", wrap=True)
        ws.row_dimensions[r].height = max(ws.row_dimensions[r].height or 0, 34)

    tips = [
        "שלבים: הכנות שישי (בוקר) · תורנות שישי (צהריים–אחה\"צ) · תורנות שבת (ערב ושבת). חניך יכול להיות בקבוצה אחת בכל שלב.",
        "גודל קבוצה = שיא האנשים שנדרשים בו-זמנית במשימות שלה. משימה בלי שעה = כל הקבוצה. משימה בלי קבוצה = בלו\"ז הצל בלי שמות.",
        "עוגן = האירוע בלו\"ז שלידו המשימה מופיעה בלו\"ז הצל. הרשימה הנגללת נלקחת מעמודת «אירוע» ב«לוז».",
        "«ניקוד» יושב ב«קבוצות» (1 טיש וקידוש, 2 ארוחות שבת, 3 הכנות שישי) ונצבר ל«חניכים» ול«היסטוריה» — מי שצבר פחות משובץ קודם.",
        "מצרכים על הפלייר: ב«משימות» בוחרים מנה בעמודת «מתכון» (כמה מנות — מופרדות ב-;), ורשימת המצרכים מ«מתכונים» מודפסת בפלייר של הקבוצה.",
    ]
    head = ws.cell(row=11, column=5, value="איך זה עובד")
    head.font = f(13, bold=True, color=ACCENT)
    head.alignment = align()
    for i, text in enumerate(tips):
        r = 12 + i
        k = ws.cell(row=r, column=4, value="•")
        k.font = f(11, bold=True, color=ACCENT)
        k.alignment = align(h="center", v="top")
        t = ws.cell(row=r, column=5, value=text)
        t.font = f(11)
        t.alignment = align(v="top", wrap=True)
        ws.row_dimensions[r].height = max(ws.row_dimensions[r].height or 0, 34)
    return ws


# ---------------------------------------------------------------------------
# גיליון: לוז — טבלה ידנית עם עמודת הצעה
# ---------------------------------------------------------------------------
def build_schedule(wb):
    ws = wb.create_sheet(SH_SCHED)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 12, "B": 11, "C": 30, "D": 18, "E": 32, "F": 11, "G": 10})
    title_row(ws, 1, "לו\"ז השבת", span="A:G", size=20)

    z = q(SH_ZMAN)
    labels = {(3, 1): "תאריך השבת", (3, 3): "פרשה", (4, 1): "כניסת שבת", (4, 3): "צאת שבת", (4, 5): "שם השבת"}
    for (r, c), text in labels.items():
        lab = ws.cell(row=r, column=c, value=text)
        lab.font = f(11, bold=True)
        lab.alignment = align()
        lab.fill = fill(BAND)
        lab.border = box()
    data_cell(ws, 3, 2, center=True, fmt="dd/mm/yyyy", size=12, bold=True)
    dv_list(ws, "{}$A$3:$A$400".format(z), SCHED_DATE, strict=True)
    calc_cell(ws, 3, 4, '=IFERROR(VLOOKUP($B$3,{}$A$3:$D$400,2,FALSE),"")'.format(z), center=False)
    for ref, col in ((SCHED_CANDLE, 3), (SCHED_HAVDALAH, 4)):
        c = ws[ref]
        c.value = '=IFERROR(VLOOKUP($B$3,{}$A$3:$D$400,{},FALSE),"")'.format(z, col)
        c.number_format = "hh:mm"
        c.font = f(12, bold=True, color=ACCENT)
        c.fill = fill(CALC_BG)
        c.alignment = align(h="center")
        c.border = box()
    ws.row_dimensions[3].height = ws.row_dimensions[4].height = 22
    hint = ws.cell(row=3, column=5, value="בחר תאריך מהרשימה — כניסה, צאה ופרשה נטענות מ«זמנים»")
    hint.font = f(10, color=MUTED, italic=True)
    hint.alignment = align()

    data_cell(ws, 4, 6, None, bold=True).fill = fill(SCRIPT_BG)          # SCHED_TITLE — new_shabbat כותב
    header_row(ws, SCHED_HEADER_ROW, ["יום", "שעה", "אירוע", "מקום", "הערה", "הצעה", "משימות"])
    write_schedule(ws, schedule_rows(), hour=False)      # תבנית: שבת נפרדת, בלי אירועים אופציונליים
    dv_list(ws, '"{}"'.format(DAYS), "A{}:A{}".format(SCHED_FIRST_ROW, SCHED_FIRST_ROW + SCHED_ROWS - 1))
    ws.freeze_panes = "A{}".format(SCHED_FIRST_ROW)
    note_row(ws, SCHED_FIRST_ROW + SCHED_ROWS + 1,
             "«שעה» היא הלו\"ז שנשלח בפועל — עורכים בה חופשי. «הצעה» מחושבת מכניסת/צאת השבת "
             "(הכללים ב-data/schedule_template.csv). «משימות» = כמה משימות מעוגנות לאירוע בלו\"ז הצל.", last_col=7)
    return ws


# ---------------------------------------------------------------------------
# גיליון: משימות — המקור היחיד לתורנויות
# ---------------------------------------------------------------------------
def build_tasks(wb):
    ws = wb.create_sheet(SH_TASKS)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 13, "B": 10, "C": 8, "D": 26, "E": 50, "F": 7, "G": 42, "H": 16, "I": 18, "J": 22})
    title_row(ws, 1, "משימות השבת — מי עושה מה ומתי", span="A:J", size=18)
    header_row(ws, 2, ["שלב", "יום", "שעה", "קבוצה", "משימה", "אנשים", "שמות", "מתכון", "עוגן בלו\"ז", "הערה"])

    rows = task_rows()
    for i in range(TASK_ROWS):
        write_task_row(ws, TASK_FIRST_ROW + i, rows[i] if i < len(rows) else None)

    last = TASK_FIRST_ROW + TASK_ROWS - 1
    span = lambda col: "{c}{a}:{c}{b}".format(c=col_letter(col), a=TASK_FIRST_ROW, b=last)
    dv_list(ws, '"{}"'.format(",".join(STAGES)), span(T_STAGE))
    dv_list(ws, '"{}"'.format(DAYS), span(T_DAY))
    dv_list(ws, G(G_NAME), span(T_GROUP))
    dv_list(ws, rng(SH_RECIPES, 2, 3, RECIPE_ROWS), span(T_RECIPE))
    dv_list(ws, L(L_EVENT), span(T_ANCHOR))
    ws.freeze_panes = "A{}".format(TASK_FIRST_ROW)
    note_row(ws, last + 2,
             "«אנשים» = כמה צריך למשימה; ריק = כל הקבוצה. «שמות» מתמלא ע\"י השיבוץ ואפשר לתקן ידנית. "
             "«מתכון» = מנה מ«מתכונים»; כמה מנות מופרדות ב-; (משימה שמכינה שני סלטים). "
             "«עוגן» = האירוע בלו\"ז שלידו המשימה תופיע בלו\"ז הצל. הניקוד יושב ב«קבוצות».", last_col=10)
    return ws


# ---------------------------------------------------------------------------
# גיליון: קבוצות
# ---------------------------------------------------------------------------
def build_groups(wb):
    ws = wb.create_sheet(SH_GROUPS)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 28, "B": 14, "C": 8, "D": 18, "E": 58, "F": 8, "G": 10})
    title_row(ws, 1, "קבוצות העבודה השבת", span="A:G", size=18)
    header_row(ws, 2, ["קבוצה", "שלב", "ניקוד", "אחראי/ת", "חניכים", "גודל", "משימות"])

    plan = plan_rows()
    for i in range(GROUP_ROWS):
        r = GROUP_FIRST_ROW + i
        row = plan[i] if i < len(plan) else None
        write_group_row(ws, r, row)
        leader = data_cell(ws, r, G_LEADER, None)
        leader.fill = fill(SCRIPT_BG)
        members = data_cell(ws, r, G_MEMBERS, None, wrap=True)
        members.fill = fill(SCRIPT_BG)
        calc_cell(ws, r, G_SIZE, '=IF(E{r}="","",LEN(E{r})-LEN(SUBSTITUTE(E{r},",",""))+1)'.format(r=r))
        calc_cell(ws, r, G_COUNT, '=IF(A{r}="","",COUNTIF({t},A{r}))'.format(r=r, t=T(T_GROUP)))
        ws.row_dimensions[r].height = 30 if row else 18
    last = GROUP_FIRST_ROW + GROUP_ROWS - 1
    dv_list(ws, '"{}"'.format(",".join(STAGES)), "B{}:B{}".format(GROUP_FIRST_ROW, last))
    dv_list(ws, '"1,2,3"', "C{}:C{}".format(GROUP_FIRST_ROW, last))
    ws.freeze_panes = "A{}".format(GROUP_FIRST_ROW)
    note_row(ws, last + 2,
             "המבנה הקבוע ב-data/group_plan.csv. «ניקוד» = כמה שווה התורנות הזו לחניך "
             "(3 הכנות שישי · 2 ארוחת ערב וצהריים · 1 טיש וקידוש). «אחראי/ת» ו«חניכים» "
             "נכתבים ע\"י השיבוץ. פלייר נוצר לכל קבוצה כאן.", last_col=7)
    return ws


# ---------------------------------------------------------------------------
# גיליון: חניכים — מעקב עומס
# ---------------------------------------------------------------------------
def build_students(wb):
    ws = wb.create_sheet(SH_STUDENTS)
    page(ws, tab=TAB_SCRIPT)
    widths(ws, {"A": 26, "B": 10, "C": 10, "D": 9, "E": 42, "F": 9, "G": 9, "H": 9, "I": 28})
    title_row(ws, 1, "חניכים — מי נמצא, מי בתורנות, וכמה עומס", span="A:I", size=18)
    header_row(ws, 2, ["שם", "תוכנית", "חבורה", "זמין/ה", "קבוצות השבת", "משימות השבת",
                       "ניקוד השבת", "ניקוד מצטבר", "הערה"])

    students = read_csv("students.csv")
    for i in range(STUDENT_ROWS):
        r = STUDENT_FIRST_ROW + i
        row = students[i] if i < len(students) else None
        data_cell(ws, r, S_NAME, row["שם"] if row else None)
        data_cell(ws, r, S_PROGRAM, (row.get("תוכנית") or None) if row else None, center=True)
        for col in (S_HAVURA, S_AVAILABLE, S_GROUPS, S_POINTS, S_NOTE):
            data_cell(ws, r, col, None,
                      center=(col in (S_HAVURA, S_AVAILABLE, S_POINTS))).fill = fill(SCRIPT_BG)
        calc_cell(ws, r, S_TASKS, '=IF(A{r}="","",COUNTIF({n},"*"&A{r}&"*"))'.format(r=r, n=T(T_NAMES)))
        calc_cell(ws, r, S_TOTAL, '=IF(A{r}="","",SUMIF({hn},A{r},{hp}))'.format(
            r=r, hn=H(H_NAME), hp=H(H_POINTS)))
    last = STUDENT_FIRST_ROW + STUDENT_ROWS - 1
    dv_list(ws, '"כן,לא"', "D{}:D{}".format(STUDENT_FIRST_ROW, last))
    ws.freeze_panes = "A{}".format(STUDENT_FIRST_ROW)
    note_row(ws, last + 2,
             "חבורה, זמינות, קבוצות השבת וניקוד השבת נכתבים ע\"י השיבוץ מרשימת הנוכחות. "
             "«משימות השבת» נספר מ«משימות»; «ניקוד מצטבר» מסוכם מ«היסטוריה» (כל השבתות).", last_col=9)
    return ws


# ---------------------------------------------------------------------------
# גיליון: היסטוריה — הזיכרון של המערכת
# ---------------------------------------------------------------------------
def build_history(wb):
    ws = wb.create_sheet(SH_HISTORY)
    page(ws, tab=TAB_SCRIPT)
    widths(ws, {"A": 13, "B": 28, "C": 16, "D": 30, "E": 9})
    title_row(ws, 1, "היסטוריית תורנויות — רשומה לכל תורנות של כל חניך", span="A:E", size=18)
    header_row(ws, 2, ["תאריך", "שם", "שלב", "קבוצה", "ניקוד"])
    for i, row in enumerate(read_history()):
        r = HISTORY_FIRST_ROW + i
        write_history_row(ws, r, row)
    ws.freeze_panes = "A{}".format(HISTORY_FIRST_ROW)
    return ws


HISTORY_FIELDS = ["תאריך", "שם", "שלב", "קבוצה", "ניקוד"]


def read_history():
    path = DATA / "duty_history.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("שם")]


def write_history_row(ws, r, row):
    d = datetime.strptime(row["תאריך"], "%Y-%m-%d").date()
    for col, val, fmt in ((H_DATE, d, "dd/mm/yyyy"), (H_NAME, row["שם"], None),
                          (H_STAGE, row.get("שלב") or None, None),
                          (H_GROUP, row.get("קבוצה") or None, None),
                          (H_POINTS, int(row.get("ניקוד") or 1), None)):
        c = ws.cell(row=r, column=col, value=val)
        c.font = f(10)
        c.alignment = align(h="center" if col in (H_DATE, H_STAGE, H_POINTS) else "right")
        if fmt:
            c.number_format = fmt


# ---------------------------------------------------------------------------
# גיליונות חופשיים: מתכונים, קייטרינג
# ---------------------------------------------------------------------------
def build_recipes(wb):
    ws = wb.create_sheet(SH_RECIPES)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 18, "B": 26, "C": 12, "D": 50, "E": 50, "F": 24})
    title_row(ws, 1, "מתכונים — עוגות, סלטים, מטבוחה וארוחת צהריים שישי", span="A:F", size=18)
    header_row(ws, 2, ["קטגוריה", "מנה", "כמות", "מרכיבים", "הוראות", "הערה"])
    write_recipes(ws, recipe_rows())
    dv_list(ws, '"{}"'.format(RECIPE_KINDS), "A3:A{}".format(2 + RECIPE_ROWS))
    ws.freeze_panes = "A3"
    note_row(ws, RECIPE_ROWS + 4,
             "שם המנה (עמודה B) הוא מה שבוחרים בעמודת «מתכון» ב«משימות» — והמצרכים מודפסים על הפלייר של הקבוצה "
             "(ההוראות רק עם --with-recipes). "
             "מרכיבים והוראות: שורה לכל פריט (Alt+Enter לשורה חדשה בתא).", last_col=6)
    return ws


def write_recipes(ws, recipes):
    """כל שורות «מתכונים» (RECIPE_ROWS), עם ניקוי שאריות — לתבנית ולקובץ השבת."""
    for i in range(RECIPE_ROWS):
        r = 3 + i
        row = recipes[i] if i < len(recipes) else None
        get = lambda k: (row.get(k) or None) if row else None
        data_cell(ws, r, 1, get("קטגוריה"), center=True)
        data_cell(ws, r, 2, get("מנה"), bold=True)
        data_cell(ws, r, 3, get("כמות"), center=True)
        data_cell(ws, r, 4, get("מרכיבים"), wrap=True)
        data_cell(ws, r, 5, get("הוראות"), wrap=True)
        data_cell(ws, r, 6, get("הערה"), wrap=True)
        ws.row_dimensions[r].height = 120 if row else None


def build_catering(wb):
    ws = wb.create_sheet(SH_CATERING)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 18, "B": 34, "C": 12, "D": 44})
    title_row(ws, 1, "קייטרינג — מה מגיע לכל ארוחה", span="A:D", size=18)
    header_row(ws, 2, ["ארוחה", "מנה", "כמות", "הערה"])
    for i in range(CATERING_ROWS):
        write_menu_row(ws, 3 + i, None)
    dv_list(ws, '"{}"'.format(MEALS), "A3:A{}".format(2 + CATERING_ROWS))
    ws.freeze_panes = "A3"
    note_row(ws, CATERING_ROWS + 4,
             "המקור הוא data/menu/<תאריך>.csv. משימה שכתוב בה {ארוחת ערב}, {סלטים}, {טיש|העוגות} וכו' "
             "מקבלת את מה שמוגש באותה ארוחה — כך התפריט וחלוקת העוגות מתעדכנים בכל המשימות בבת אחת.", last_col=4)
    return ws


# ---------------------------------------------------------------------------
# גיליון: זמנים
# ---------------------------------------------------------------------------
def build_zmanim(wb):
    ws = wb.create_sheet(SH_ZMAN)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 16, "B": 26, "C": 14, "D": 14, "E": 24, "F": 46})
    title_row(ws, 1, "לוח שבתות — כניסה וצאה", span="A:F", size=16)
    header_row(ws, 2, ["תאריך", "פרשה", "כניסת שבת", "צאת שבת", "מקור", "ניתן לעריכה"])
    for i, row in enumerate(read_zmanim()):
        r = 3 + i
        for col, val, fmt in ((1, row["תאריך"], "dd/mm/yyyy"), (2, row["פרשה"], None),
                              (3, as_time(row["כניסת שבת"]), "hh:mm"),
                              (4, as_time(row["צאת שבת"]), "hh:mm"), (5, row["מקור"], None)):
            data_cell(ws, r, col, val, editable=(col in (3, 4)), center=(col != 2), fmt=fmt)
    ws.freeze_panes = "A3"
    hint = ws.cell(row=3, column=6,
                   value="בשבתות שלנו (data/shabbatot.csv) — הזמנים מאתר ישיבה לכפר אדומים. "
                         "בשאר — חישוב לירושלים (כניסה 40 דק' לפני השקיעה, צאה 40 דק' אחריה). "
                         "new_shabbat כותב מחדש את שורת השבת שלו.")
    ws.merge_cells("F3:F8")
    hint.font = f(10, color=MUTED, italic=True)
    hint.alignment = align(v="top", wrap=True)
    return ws


# ---------------------------------------------------------------------------
def main():
    wb = Workbook()
    wb.remove(wb.active)
    build_dashboard(wb)
    build_schedule(wb)
    build_tasks(wb)
    build_groups(wb)
    build_students(wb)
    build_history(wb)
    build_recipes(wb)
    build_catering(wb)
    build_zmanim(wb)
    wb.active = 0
    wb.save(OUT)
    print("נבנה: {} ({} גיליונות)".format(OUT.relative_to(ROOT), len(wb.sheetnames)))


if __name__ == "__main__":
    main()
