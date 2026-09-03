# -*- coding: utf-8 -*-
"""מחולל חוברת "תכנון שבת" (shabbat-planner.xlsx) — מדרשת עין פרת.

הרצה:  python3 tools/build_workbook.py
הסקריפט בונה את הקובץ מאפס מתוך data/*.csv. השימוש השוטף לא דורש אותו —
פותחים את האקסל וממלאים. מריצים מחדש רק כשמשנים את מבנה החוברת.
"""
import csv
from datetime import datetime, time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.properties import PageSetupProperties

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "shabbat-planner.xlsx"

# --- שמות גיליונות ---------------------------------------------------------
SH_HELP, SH_SET, SH_SCHED = "הוראות", "הגדרות", "לוז"
SH_CARDS, SH_PLAIN, SH_CHECK = "כרטיסיות", "טופס נקי", "צ'קליסט"
SH_SHOP, SH_PANTRY = "קניות", "לבדוק במטבח"
SH_ASSIGN, SH_MENU = "שיבוץ", "תפריט השבת"
SH_STUDENTS, SH_GROUPS = "חניכים", "קבוצות"
SH_TASKS, SH_RECIPES, SH_ITEMS, SH_ZMAN = "מאגר משימות", "מתכונים", "מצרכים", "זמנים"

# --- גדלים ------------------------------------------------------------------
MAX_GROUPS = 6            # קבוצות נתמכות (כרטיסייה לכל אחת)
CARD_TASK_ROWS = 18       # שורות משימה בכל כרטיסייה
ASSIGN_ROWS = 150         # שורות בגיליון השיבוץ
STUDENT_ROWS = 90         # שורות בגיליון החניכים
TASK_ROWS = 250           # שורות במאגר המשימות (כולל רזרבה)
RECIPE_ROWS = 250         # שורות בגיליון המתכונים
MENU_ROWS = 40            # שורות בתפריט השבת
ITEM_ROWS = 100           # שורות בקטלוג המצרכים
EXTRA_SHOP_ROWS = 12      # שורות חופשיות בסוף רשימת הקניות

# --- צבעים ------------------------------------------------------------------
INK, MUTED, LINE, BAND = "1F2430", "6B7280", "C9CFD8", "EDF1F6"
ACCENT, INPUT_BG, CALC_BG = "2E5C8A", "FFF9E3", "EEF3F8"
WARN_BG, WARN_INK = "FCE3C6", "8A4B00"

TAB_INPUT, TAB_OUTPUT, TAB_REF = "E8A33D", "2E5C8A", "9AA5B1"

THEMES = {
    "ורוד": ("F6BFD5", "FDEEF4"),
    "ים": ("B3D4EF", "EAF3FB"),
    "ספארי": ("F3D3A0", "FDF1DF"),
    "שדה": ("C6E2B7", "EDF6E7"),
    "סגול": ("D3C6EE", "F1EBFB"),
    "ירוק": ("B7E4D6", "E7F7F2"),
}
THEME_ORDER = list(THEMES)
FONT = "Arial"

WINDOWS = "שישי,שבת,מוצאי שבת,חמישי"
MEALS = "קידוש,ארוחת ערב שבת,ארוחת צהריים שבת,סעודה שלישית,טיש,ארוחת צהריים שישי"


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
    """הפניה מצוטטת לגיליון, בטוחה גם לשמות עם רווח."""
    return "'{}'!".format(sheet)


def date_text(ref):
    """תאריך כטקסט בלי להסתמך על קודי פורמט מתורגמים (אקסל בעברית)."""
    return 'TEXT(DAY({r}),"00")&"/"&TEXT(MONTH({r}),"00")&"/"&TEXT(YEAR({r}),"0000")'.format(r=ref)


def time_text(ref):
    return 'TEXT(HOUR({r}),"00")&":"&TEXT(MINUTE({r}),"00")'.format(r=ref)


CANDLE = q(SH_SET) + "$B$10"      # כניסת שבת בפועל
HAVDALAH = q(SH_SET) + "$B$11"    # צאת שבת בפועל


def page(ws, landscape=False, fit=True, rtl=True, tab=None):
    ws.sheet_view.rightToLeft = rtl
    ws.sheet_view.showGridLines = False
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    if fit:
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
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


def subtitle(ws, row, text, span="A:F", size=10):
    last = span.split(":")[1]
    ws.merge_cells("A{r}:{c}{r}".format(r=row, c=last))
    c = ws["A{}".format(row)]
    c.value = text
    c.font = f(size, color=MUTED, italic=True)
    c.alignment = align(wrap=True)
    ws.row_dimensions[row].height = 20
    return c


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


def as_time(text):
    h, m = text.split(":")
    return time(int(h), int(m))


def data_cell(ws, row, col, value=None, editable=True, wrap=False, center=False,
              bold=False, size=11, fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    c.border = box()
    c.alignment = align(h="center" if center else "right", wrap=wrap, v="top" if wrap else "center")
    c.font = f(size, bold=bold)
    if editable:
        c.fill = fill(INPUT_BG)
    if fmt:
        c.number_format = fmt
    return c


# ---------------------------------------------------------------------------
# גיליון: הוראות
# ---------------------------------------------------------------------------
HELP_LINES = [
    ("מה עושים כל שבוע", None),
    ("1", "«הגדרות» — בוחרים תאריך שבת מהרשימה. כניסת השבת וצאתה נטענות לבד. ממלאים מרחבים ואנשי צוות."),
    ("2", "«חניכים» — משבצים כל חניך לקבוצה. אפשר לתת ל-tools/assign_groups.py להציע חלוקה מתחלפת."),
    ("3", "«שיבוץ» — מי עושה מה: קבוצה, חלון זמן, שעה (אם יש), משימה מהרשימה ופרטים. הקטגוריה נטענת לבד."),
    ("4", "«תפריט השבת» — מה מכינים והכמויות. מכאן נבנית רשימת הקניות."),
    ("5", "מדפיסים: «לוז», «כרטיסיות» (דף צבעוני לקבוצה), «טופס נקי», «צ'קליסט» ו«קניות»."),
    ("", None),
    ("סוגי משימות", None),
    ("•", "אפייה ובישול — משתנות בכל שבת לפי התפריט והמתכונים."),
    ("•", "ניקיון וסידור — משימה נפרדת לכל מרחב, כדי שתבחרו בכל שבת אילו מרחבים מנקים ומתי."),
    ("•", "תורנות ארוחה — תורנים לקידוש, לארוחות ולסעודה שלישית."),
    ("•", "אחריות טכנית — פלטות, מיחמים, תנור חימום, ציוד הבדלה, אורות ומזגנים, עיתון."),
    ("", None),
    ("איך הקניות מחושבות", None),
    ("•", "«מצרכים» הוא קטלוג קבוע: יחידה, קטגוריית קנייה, ומה נמצא תמיד במטבח."),
    ("•", "«מתכונים» — לכל מנה שורה לכל מרכיב, עם הכמות ליחידה אחת. ממלאים פעם אחת."),
    ("•", "«תפריט השבת» — בוחרים מנות וכמה מכל אחת. «קניות» ו«לבדוק במטבח» מתמלאים לבד."),
    ("", None),
    ("טיפים", None),
    ("•", "שכחת להזין תאריך? כל הגיליונות יישארו ריקים עד שתבחר אחד."),
    ("•", "הזמנים ב«זמנים» מחושבים לירושלים ומדויקים לדקה-שתיים. הלוח שלך קובע — תקן שורה או הזן עקיפה ב«הגדרות»."),
    ("•", "ב«לוז» יש התראה אוטומטית כשנשארת פחות משעה בין החבורה של 15:00 לסעודה שלישית."),
    ("•", "המשימות בכרטיסייה מופיעות בסדר שבו הזנת אותן ב«שיבוץ» — כדאי להזין לפי סדר הזמן."),
    ("•", "שינית שם קבוצה? עדכן גם ב«שיבוץ». עמודת «בדיקה» שם תדליק אזהרה על שם שאינו קיים."),
    ("•", "צבע הטאב: כתום = ממלאים, כחול = פלט להדפסה, אפור = מאגרים שמתעדכנים לעיתים רחוקות."),
    ("•", "לשמור עותק לכל שבת: קובץ ← שמירה בשם, או python3 tools/new_shabbat.py <תאריך>."),
]


def build_help(wb):
    ws = wb.create_sheet(SH_HELP)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 4, "B": 108})
    title_row(ws, 1, "תכנון שבת — מדרשת עין פרת", span="A:B", size=20)

    row = 3
    for key, text in HELP_LINES:
        if text is None:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            c = ws.cell(row=row, column=1, value=key)
            c.font = f(13, bold=True, color=ACCENT)
            c.alignment = align()
            ws.row_dimensions[row].height = 26
        else:
            k = ws.cell(row=row, column=1, value=key)
            k.font = f(11, bold=True, color=ACCENT)
            k.alignment = align(h="center", v="top")
            t = ws.cell(row=row, column=2, value=text)
            t.font = f(11)
            t.alignment = align(v="top", wrap=True)
            ws.row_dimensions[row].height = 30
        row += 1
    return ws


# ---------------------------------------------------------------------------
# גיליון: הגדרות
# ---------------------------------------------------------------------------
SETTINGS_LAYOUT = [
    (1, "title", "הגדרות השבת — הגיליון היחיד שממלאים כל שבוע", None),
    (3, "section", "1. איזו שבת", None),
    (4, "input", "תאריך השבת", None),
    (5, "calc", "פרשה", "=IFERROR(VLOOKUP($B$4,'{z}'!$A$3:$D$400,2,FALSE),\"\")"),
    (6, "calc", "כניסת שבת (מהלוח)", "=IFERROR(VLOOKUP($B$4,'{z}'!$A$3:$D$400,3,FALSE),\"\")"),
    (7, "calc", "צאת שבת (מהלוח)", "=IFERROR(VLOOKUP($B$4,'{z}'!$A$3:$D$400,4,FALSE),\"\")"),
    (8, "input", "עקיפה ידנית — כניסת שבת", None),
    (9, "input", "עקיפה ידנית — צאת שבת", None),
    (10, "result", "כניסת שבת בפועל", '=IF($B$8="",$B$6,$B$8)'),
    (11, "result", "צאת שבת בפועל", '=IF($B$9="",$B$7,$B$9)'),
    (13, "section", "2. מרחבים והחלטות", None),
    (14, "input", "מקום קבלת שבת ישראלית", None),
    (15, "input", "מקום הקידוש", None),
    (16, "input", "מרחבי חבורות חניכים", None),
    (17, "input", "מקום הטיש", None),
    (18, "input", "מקום החבורה עם איש צוות", None),
    (19, "input", "מקום סעודה שלישית", None),
    (21, "section", "3. אנשי צוות", None),
    (22, "input", "טיש (ליל שבת)", None),
    (23, "input", "חבורה (שבת 15:00)", None),
    (24, "input", "כריכה לכריכה (מוצ\"ש)", None),
    (26, "section", "4. כללי", None),
    (27, "input", "מספר משתתפים", None),
    (28, "input", "מספר חבורות חניכים", None),
    (29, "input", "הערות לשבת", None),
]

SETTINGS_HINTS = {
    4: "בחירה מהרשימה",
    8: "רק אם הלוח שלך אומר אחרת (למשל 18:20)",
    9: "רק אם הלוח שלך אומר אחרת",
    14: "כשעה לפני כניסת השבת",
    15: "שבת 11:00",
    16: "לפי מספר החבורות",
    17: "כשעה וחצי אחרי תחילת הסעודה",
    18: "ברירת מחדל: בית מיכאל",
    19: "חדר אוכל או בית שקד",
    27: "משמש לחישוב כמויות",
}

SETTINGS_DEFAULTS = {18: "בית מיכאל", 19: "חדר אוכל"}


def build_settings(wb):
    ws = wb.create_sheet(SH_SET)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 30, "B": 30, "C": 44})

    for row, kind, label, formula in SETTINGS_LAYOUT:
        if kind == "title":
            title_row(ws, row, label, span="A:C", size=18)
            continue
        if kind == "section":
            ws.merge_cells("A{r}:C{r}".format(r=row))
            c = ws["A{}".format(row)]
            c.value = label
            c.font = f(13, bold=True, color="FFFFFF")
            c.fill = fill(ACCENT)
            c.alignment = align()
            ws.row_dimensions[row].height = 24
            continue

        lab = ws.cell(row=row, column=1, value=label)
        lab.font = f(11, bold=True)
        lab.alignment = align()
        lab.fill = fill(BAND)
        lab.border = box()

        val = ws.cell(row=row, column=2)
        val.border = box()
        val.alignment = align(h="center")
        if kind == "input":
            val.fill = fill(INPUT_BG)
            val.font = f(12)
            if row in SETTINGS_DEFAULTS:
                val.value = SETTINGS_DEFAULTS[row]
        elif kind == "calc":
            val.value = formula.format(z=SH_ZMAN)
            val.font = f(12, color=MUTED)
        else:
            val.value = formula
            val.font = f(13, bold=True, color=ACCENT)
            val.fill = fill(CALC_BG)

        if row in (6, 7, 8, 9, 10, 11):
            val.number_format = "hh:mm"
        if row == 4:
            val.number_format = "dd/mm/yyyy"

        hint = ws.cell(row=row, column=3, value=SETTINGS_HINTS.get(row, ""))
        hint.font = f(10, color=MUTED, italic=True)
        hint.alignment = align()
        ws.row_dimensions[row].height = 22

    dv_list(ws, "'{}'!$A$3:$A$400".format(SH_ZMAN), "B4", strict=True)
    dv_list(ws, '"חדר אוכל,בית שקד"', "B19")
    ws.freeze_panes = "A2"
    return ws


# ---------------------------------------------------------------------------
# גיליון: לוז
# ---------------------------------------------------------------------------
def build_schedule(wb):
    ws = wb.create_sheet(SH_SCHED)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 13, "B": 10, "C": 34, "D": 22, "E": 16, "F": 40})

    title_row(ws, 1, "לוח זמנים לשבת", span="A:F", size=20)
    sub = ws.cell(
        row=2, column=1,
        value='=IF({s}$B$4="","בחר תאריך בגיליון «הגדרות»","שבת "&{d}&'
        'IF({s}$B$5=""," "," · פרשת "&{s}$B$5)&"  |  כניסה "&{ct}&"  ·  צאה "&{ht})'.format(
            s=q(SH_SET), d=date_text(q(SH_SET) + "$B$4"),
            ct=time_text(CANDLE), ht=time_text(HAVDALAH)),
    )
    ws.merge_cells("A2:F2")
    sub.font = f(12, bold=True, color=MUTED)
    sub.alignment = align()
    ws.row_dimensions[2].height = 22

    header_row(ws, 3, ["יום", "שעה", "פעילות", "מקום", "איש צוות", "הערות"])

    def guard(expr, base=CANDLE):
        return '=IF({b}="","",{e})'.format(b=base, e=expr)

    S = q(SH_SET)
    rows = [
        ("יום שישי", guard("{}-TIME(1,0,0)".format(CANDLE)), "קבלת שבת ישראלית",
         '={}$B$14&""'.format(S), "", "כשעה לפני כניסת השבת"),
        ("", guard(CANDLE), "כניסת שבת", "", "", "הדלקת נרות"),
        ("", guard("$B$5+TIME(0,15,0)"), "קבלת שבת וערבית", "בית מיכאל", "",
         "כ-15 דקות אחרי כניסת השבת"),
        ("", guard("MAX($B$6+TIME(1,30,0),TIME(18,30,0))"), "סעודת שבת", "חדר אוכל", "",
         "כשעה וחצי אחרי תחילת קבלת שבת, ולא לפני 18:30"),
        ("", guard("$B$7+TIME(1,30,0)"), "טיש עם איש צוות", '={}$B$17&""'.format(S),
         '={}$B$22&""'.format(S), "כשעה וחצי אחרי תחילת הסעודה"),
        ("יום שבת", time(11, 0), "קידוש", '={}$B$15&""'.format(S), "", ""),
        ("", time(11, 45), "חבורות חניכים", '={}$B$16&""'.format(S), "",
         "מחולקים לפי מספר החבורות"),
        ("", time(12, 30), "ארוחת צהריים", "חדר אוכל", "", ""),
        ("", time(15, 0), "חבורה עם איש צוות", '={}$B$18&""'.format(S),
         '={}$B$23&""'.format(S),
         '=IF({h}="","",IF(($B$13-TIME(15,0,0))<TIME(1,0,0),'
         '"⚠ פחות משעה עד סעודה שלישית — לשקול שינוי",""))'.format(h=HAVDALAH)),
        ("", guard("{}-TIME(1,30,0)".format(HAVDALAH), HAVDALAH), "סעודה שלישית",
         '={}$B$19&""'.format(S), "", "כשעה וחצי לפני צאת השבת"),
        ("", guard(HAVDALAH, HAVDALAH), "הבדלה", "", "", ""),
        ("מוצאי שבת", guard("{}+TIME(0,10,0)".format(HAVDALAH), HAVDALAH),
         "ניקיונות וארגון הקמפוס", "הקמפוס", "", "10 דקות אחרי צאת השבת"),
        ("", guard("CEILING({}+TIME(2,0,0),TIME(0,30,0))".format(HAVDALAH), HAVDALAH),
         "כריכה לכריכה — תנ\"ך עם איש צוות", "", '={}$B$24&""'.format(S),
         "כשעתיים אחרי צאת השבת, מעוגל לחצי שעה"),
    ]

    day_fills = {"יום שישי": "E8F0F8", "יום שבת": "F3EDE3", "מוצאי שבת": "EDEAF5"}
    current_fill = BAND
    for i, (day, tm, act, place, staff, note) in enumerate(rows):
        r = 4 + i
        if day:
            current_fill = day_fills[day]
        for col, val in enumerate([day, tm, act, place, staff, note], start=1):
            c = ws.cell(row=r, column=col, value=val if val != "" else None)
            c.border = box()
            c.alignment = align(h="center" if col in (1, 2) else "right", wrap=(col == 6))
            c.font = f(11, bold=(col == 3))
            if col == 1:
                c.fill = fill(current_fill)
                c.font = f(11, bold=True, color=ACCENT)
            if col == 2:
                c.number_format = "hh:mm"
                c.font = f(13, bold=True)
        ws.row_dimensions[r].height = 26

    last = 4 + len(rows) - 1
    ws.conditional_formatting.add(
        "F4:F{}".format(last),
        FormulaRule(formula=['LEFT($F4,1)="⚠"'], fill=fill(WARN_BG),
                    font=f(11, bold=True, color=WARN_INK)),
    )
    ws.freeze_panes = "A4"
    note_row(ws, last + 2,
             "השעות נגזרות אוטומטית מכניסת/צאת השבת שבגיליון «הגדרות». כדי לשנות — עדכנו שם, לא כאן.",
             last_col=6)
    return ws


# ---------------------------------------------------------------------------
# גיליון: זמנים
# ---------------------------------------------------------------------------
def build_zmanim(wb):
    ws = wb.create_sheet(SH_ZMAN)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 16, "B": 26, "C": 14, "D": 14, "E": 46})
    title_row(ws, 1, "לוח שבתות — זמני ירושלים", span="A:E", size=16)
    header_row(ws, 2, ["תאריך", "פרשה", "כניסת שבת", "צאת שבת", "ניתן לעריכה"])

    for i, row in enumerate(read_csv("zmanim.csv")):
        r = 3 + i
        d = datetime.strptime(row["תאריך"], "%d/%m/%Y").date()
        for col, val, fmt in ((1, d, "dd/mm/yyyy"), (2, row["פרשה"], None),
                              (3, as_time(row["כניסת שבת"]), "hh:mm"),
                              (4, as_time(row["צאת שבת"]), "hh:mm")):
            data_cell(ws, r, col, val, editable=(col in (3, 4)),
                      center=(col != 2), fmt=fmt)
    ws.freeze_panes = "A3"

    hint = ws.cell(row=3, column=5,
                   value="הזמנים מחושבים לירושלים (כניסה 40 דק' לפני השקיעה, צאה 40 דק' אחריה) "
                         "ומדויקים לדקה-שתיים. אם הלוח שלך אומר אחרת — תקנו את השורה. "
                         "הצבע הצהוב מסמן שדה שמותר לשנות.")
    ws.merge_cells("E3:E8")
    hint.font = f(10, color=MUTED, italic=True)
    hint.alignment = align(v="top", wrap=True)
    return ws


# ---------------------------------------------------------------------------
# גיליון: חניכים
# ---------------------------------------------------------------------------
def build_students(wb):
    """רשימת החניכים והשיוך לקבוצות.

    עמודות העזר F..K מחברות בהדרגה את שמות כל קבוצה למחרוזת אחת. השורה האחרונה
    שלהן היא מה שמופיע בכרטיסייה — כך ששינוי שיוך של חניך מתעדכן מיד, בלי TEXTJOIN
    (שאינו קיים בכל גרסת אקסל).
    """
    ws = wb.create_sheet(SH_STUDENTS)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 30, "B": 22, "C": 18, "D": 34})
    title_row(ws, 1, "חניכים ושיוך לקבוצות", span="A:D", size=18)
    header_row(ws, 2, ["שם", "קבוצה", "קבוצה קבועה", "הערה"])

    students = read_csv("students.csv")
    last = 2 + STUDENT_ROWS
    for i in range(STUDENT_ROWS):
        r = 3 + i
        row = students[i] if i < len(students) else {}
        data_cell(ws, r, 1, row.get("שם") or None, editable=False, bold=True)
        data_cell(ws, r, 2, row.get("קבוצה קבועה") or None, center=True)
        data_cell(ws, r, 3, row.get("קבוצה קבועה") or None, center=True)
        data_cell(ws, r, 4, row.get("הערה") or None)
        ws.row_dimensions[r].height = 20

        for slot in range(MAX_GROUPS):
            col = 6 + slot                      # F..K
            gref = "{g}$A${gr}".format(g=q(SH_GROUPS), gr=3 + slot)
            if i == 0:
                formula = '=IF(AND($B{r}<>"",$B{r}={g}),$A{r},"")'.format(r=r, g=gref)
            else:
                prev = ws.cell(row=r - 1, column=col).coordinate
                formula = ('=IF(AND($B{r}<>"",$B{r}={g}),IF({p}="","",{p}&", ")&$A{r},{p})'
                           .format(r=r, g=gref, p=prev))
            c = ws.cell(row=r, column=col, value=formula)
            c.font = f(9, color=MUTED)

    for slot in range(MAX_GROUPS):
        ws.column_dimensions[chr(ord("F") + slot)].hidden = True

    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_GROUPS, 2 + MAX_GROUPS),
            "B3:B{}".format(last))
    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_GROUPS, 2 + MAX_GROUPS),
            "C3:C{}".format(last))
    ws.freeze_panes = "A3"
    note_row(ws, last + 2,
             "עמודת «קבוצה» היא השיוך לשבת הזו. «קבוצה קבועה» נועדה לחניך שצריך להישאר "
             "תמיד באותה קבוצה — סקריפט החלוקה מכבד אותה ומסובב רק את השאר.")
    return ws


# ---------------------------------------------------------------------------
# גיליון: קבוצות
# ---------------------------------------------------------------------------
def build_groups(wb):
    ws = wb.create_sheet(SH_GROUPS)
    page(ws, landscape=True, tab=TAB_INPUT)
    widths(ws, {"A": 24, "B": 20, "C": 96, "D": 14, "E": 12})
    title_row(ws, 1, "קבוצות האחריות", span="A:E", size=18)
    header_row(ws, 2, ["קבוצה", "מוביל/ה", "חניכים (מחושב מגיליון «חניכים»)",
                       "ערכת צבע", "מס' חניכים"])

    student_last = 2 + STUDENT_ROWS
    for i in range(MAX_GROUPS):
        r = 3 + i
        name = "קבוצה {}".format(i + 1) if i < 4 else None
        data_cell(ws, r, 1, name, bold=True)
        data_cell(ws, r, 2, None)
        members = data_cell(
            ws, r, 3,
            '=IF($A{r}="","",{s}${col}${last}&"")'.format(
                r=r, s=q(SH_STUDENTS), col=chr(ord("F") + i), last=student_last),
            editable=False, wrap=True)
        members.fill = fill(CALC_BG)
        data_cell(ws, r, 4, THEME_ORDER[i], center=True)
        count = data_cell(
            ws, r, 5,
            '=IF($A{r}="","",COUNTIF({s}$B$3:$B${last},$A{r}))'.format(
                r=r, s=q(SH_STUDENTS), last=student_last),
            editable=False, center=True, bold=True)
        count.fill = fill(CALC_BG)
        ws.row_dimensions[r].height = 46

    dv_list(ws, '"{}"'.format(",".join(THEME_ORDER)), "D3:D{}".format(2 + MAX_GROUPS))
    ws.freeze_panes = "A3"
    note_row(ws, 4 + MAX_GROUPS,
             "שמות הקבוצות והמובילים נקבעים כאן. רשימת החניכים מחושבת מגיליון «חניכים» — "
             "אין מה להקליד בה. ערכת הצבע קובעת את צבע הכרטיסייה.", last_col=5)
    return ws


# ---------------------------------------------------------------------------
# גיליון: מאגר משימות
# ---------------------------------------------------------------------------
CATEGORY_COLORS = {
    "אפייה ובישול": "FDF1DF",
    "ניקיון וסידור": "EAF3FB",
    "תורנות ארוחה": "EDF6E7",
    "אחריות טכנית": "F1EBFB",
}


def build_tasks(wb):
    ws = wb.create_sheet(SH_TASKS)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 20, "B": 22, "C": 14, "D": 76})
    title_row(ws, 1, "מאגר משימות קבוע", span="A:D", size=18)
    header_row(ws, 2, ["קטגוריה", "תחום אחריות", "חלון זמן", "משימה"])

    rows = read_csv("task_library.csv")
    for i in range(TASK_ROWS):
        r = 3 + i
        row = rows[i] if i < len(rows) else {}
        cat = row.get("קטגוריה", "")
        for col, key in enumerate(["קטגוריה", "תחום אחריות", "חלון זמן", "משימה"], start=1):
            c = data_cell(ws, r, col, row.get(key) or None, editable=False,
                          wrap=(col == 4), center=(col == 3), bold=(col == 1))
            if col == 1 and cat:
                c.fill = fill(CATEGORY_COLORS.get(cat, BAND))
        ws.row_dimensions[r].height = 20

    dv_list(ws, '"{}"'.format(",".join(CATEGORY_COLORS)), "A3:A{}".format(2 + TASK_ROWS))
    dv_list(ws, '"{}"'.format(WINDOWS + ",משתנה"), "C3:C{}".format(2 + TASK_ROWS))
    ws.freeze_panes = "A3"
    note_row(ws, 4 + TASK_ROWS,
             "זו רשימת ההיצע לגיליון «שיבוץ». מותר ורצוי להוסיף, למחוק ולתקן — הרשימה הנגללת "
             "והקטגוריה האוטומטית מתעדכנות לבד. משימות ניקיון מופיעות בנפרד לכל מרחב, "
             "כדי לבחור בכל שבת אילו מרחבים מנקים ומתי.")
    return ws


# ---------------------------------------------------------------------------
# גיליון: שיבוץ
# ---------------------------------------------------------------------------
def build_assign(wb):
    ws = wb.create_sheet(SH_ASSIGN)
    page(ws, landscape=True, tab=TAB_INPUT)
    widths(ws, {"A": 20, "B": 13, "C": 9, "D": 44, "E": 17, "F": 52,
                "G": 9, "H": 22, "I": 22})
    title_row(ws, 1, "שיבוץ תורנויות לשבת", span="A:G", size=18)
    header_row(ws, 2, ["קבוצה", "חלון זמן", "שעה", "משימה", "קטגוריה",
                       "פרטים וכמויות", "בוצע", "מפתח (אל תיגעו)", "בדיקה"])

    last = 2 + ASSIGN_ROWS
    task_last = 2 + TASK_ROWS
    for i in range(ASSIGN_ROWS):
        r = 3 + i
        data_cell(ws, r, 1, None, bold=True)
        data_cell(ws, r, 2, None, center=True)
        data_cell(ws, r, 3, None, center=True, fmt="hh:mm")
        data_cell(ws, r, 4, None, wrap=True)
        cat = data_cell(
            ws, r, 5,
            '=IF($D{r}="","",IFERROR(INDEX({t}$A$3:$A${tl},'
            'MATCH($D{r},{t}$D$3:$D${tl},0)),""))'.format(r=r, t=q(SH_TASKS), tl=task_last),
            editable=False, center=True)
        cat.fill = fill(CALC_BG)
        cat.font = f(10, color=MUTED)
        data_cell(ws, r, 6, None, wrap=True)
        data_cell(ws, r, 7, None, editable=False, center=True)

        key = ws.cell(row=r, column=8,
                      value='=IF($A{r}="","",$A{r}&"|"&COUNTIF($A$3:$A{r},$A{r}))'.format(r=r))
        key.font = f(9, color=MUTED)

        check = ws.cell(
            row=r, column=9,
            value='=IF($A{r}="","",IF(COUNTIF({g}$A$3:$A${gl},$A{r})=0,'
                  '"⚠ שם קבוצה לא מוכר",""))'.format(r=r, g=q(SH_GROUPS), gl=2 + MAX_GROUPS))
        check.font = f(10, bold=True, color=WARN_INK)
        check.alignment = align(h="center")
        ws.row_dimensions[r].height = 28

    ws.column_dimensions["H"].hidden = True

    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_GROUPS, 2 + MAX_GROUPS), "A3:A{}".format(last))
    dv_list(ws, '"{}"'.format(WINDOWS), "B3:B{}".format(last))
    dv_list(ws, "'{}'!$D$3:$D${}".format(SH_TASKS, task_last), "D3:D{}".format(last))
    dv_list(ws, '"✔"', "G3:G{}".format(last))

    ws.conditional_formatting.add(
        "I3:I{}".format(last), FormulaRule(formula=["LEN($I3)>0"], fill=fill(WARN_BG)))
    ws.freeze_panes = "A3"
    return ws


# ---------------------------------------------------------------------------
# גיליון: כרטיסיות
# ---------------------------------------------------------------------------
def build_cards(wb):
    ws = wb.create_sheet(SH_CARDS)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 12, "B": 8, "C": 15, "D": 17, "E": 17, "F": 22,
                "H": 12, "I": 12, "J": 12, "K": 12, "L": 12})
    for col in "HIJKL":
        ws.column_dimensions[col].hidden = True

    block_height = CARD_TASK_ROWS + 7
    G, A, S = q(SH_GROUPS), q(SH_SET), q(SH_ASSIGN)
    assign_last = 2 + ASSIGN_ROWS

    for idx in range(MAX_GROUPS):
        top = 1 + idx * block_height
        grow = 3 + idx
        gref = "{g}$A${r}".format(g=G, r=grow)
        theme_cell = "{g}$D${r}".format(g=G, r=grow)
        strong, light = THEMES[THEME_ORDER[idx]]

        ws.merge_cells(start_row=top, start_column=1, end_row=top, end_column=6)
        c = ws.cell(row=top, column=1, value='=IF({r}="","",{r})'.format(r=gref))
        c.font = f(24, bold=True)
        c.alignment = align(h="center")
        c.fill = fill(strong)
        ws.row_dimensions[top].height = 42

        ws.merge_cells(start_row=top + 1, start_column=1, end_row=top + 1, end_column=6)
        c = ws.cell(row=top + 1, column=1,
                    value='=IF({g}$C${r}="","",{g}$C${r})'.format(g=G, r=grow))
        c.font = f(11, bold=True)
        c.alignment = align(h="center", wrap=True)
        c.fill = fill(light)
        ws.row_dimensions[top + 1].height = 60

        ws.merge_cells(start_row=top + 2, start_column=1, end_row=top + 2, end_column=6)
        c = ws.cell(
            row=top + 2, column=1,
            value='=IF({a}$B$4="","","שבת "&{d}&IF({a}$B$5=""," "," · פרשת "&{a}$B$5))'.format(
                a=A, d=date_text(A + "$B$4")))
        c.font = f(11, italic=True, color=MUTED)
        c.alignment = align(h="center")
        c.fill = fill(light)
        ws.row_dimensions[top + 2].height = 20

        hdr = top + 3
        ws.merge_cells(start_row=hdr, start_column=4, end_row=hdr, end_column=5)
        for col, text in ((1, "מתי"), (2, "שעה"), (3, "קטגוריה"), (4, "משימה"), (6, "פרטים")):
            h = ws.cell(row=hdr, column=col, value=text)
            h.font = f(11, bold=True, color="FFFFFF")
            h.fill = fill(ACCENT)
            h.alignment = align(h="center")
            h.border = box()
        ws.row_dimensions[hdr].height = 22

        for n in range(1, CARD_TASK_ROWS + 1):
            r = hdr + n
            text_lookup = ('=IFERROR(INDEX({s}${col}$3:${col}${last},'
                           'MATCH({g}&"|"&{n},{s}$H$3:$H${last},0))&"","")')
            num_lookup = ('=IFERROR(INDEX({s}${col}$3:${col}${last},'
                          'MATCH({g}&"|"&{n},{s}$H$3:$H${last},0)),"")')
            for col_idx, src in ((8, "B"), (9, "D"), (10, "F"), (12, "E")):
                ws.cell(row=r, column=col_idx,
                        value=text_lookup.format(s=S, col=src, g=gref, n=n, last=assign_last))
            ws.cell(row=r, column=11,
                    value=num_lookup.format(s=S, col="C", g=gref, n=n, last=assign_last))

            when = ws.cell(row=r, column=1,
                           value='=IF($H{r}="","",IF($H{r}=$H{p},"",$H{r}))'.format(r=r, p=r - 1))
            when.font = f(11, bold=True, color=ACCENT)
            when.alignment = align(h="center", v="top")
            when.fill = fill(light)
            when.border = box()

            hour = ws.cell(row=r, column=2,
                           value='=IF(N($K{r})=0,"",{t})'.format(r=r, t=time_text("$K{}".format(r))))
            hour.font = f(11, bold=True)
            hour.alignment = align(h="center", v="top")
            hour.border = box()

            cat = ws.cell(row=r, column=3, value="=$L{}".format(r))
            cat.font = f(9, color=MUTED)
            cat.alignment = align(h="center", v="top", wrap=True)
            cat.border = box()

            ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=5)
            task = ws.cell(row=r, column=4, value="=$I{}".format(r))
            task.font = f(11, bold=True)
            task.alignment = align(v="top", wrap=True)
            task.border = box()

            det = ws.cell(row=r, column=6, value="=$J{}".format(r))
            det.font = f(10, color=MUTED)
            det.alignment = align(v="top", wrap=True)
            det.border = box()

            ws.cell(row=r, column=5).border = box()
            ws.row_dimensions[r].height = 28

        warn = hdr + CARD_TASK_ROWS + 1
        ws.merge_cells(start_row=warn, start_column=1, end_row=warn, end_column=6)
        w = ws.cell(
            row=warn, column=1,
            value='=IF(COUNTIF({s}$A$3:$A${last},{g})>{n},'
                  '"⚠ לקבוצה יש עוד משימות שלא נכנסו לכרטיסייה — ראו «טופס נקי»","")'.format(
                      s=S, last=assign_last, g=gref, n=CARD_TASK_ROWS))
        w.font = f(10, bold=True, color=WARN_INK)
        w.alignment = align(h="center")
        ws.row_dimensions[warn].height = 18

        head_range = "A{}:F{}".format(top + 1, top + 2)
        body_range = "A{}:A{}".format(hdr + 1, hdr + CARD_TASK_ROWS)
        for name, (s_rgb, l_rgb) in THEMES.items():
            rule = ['{}="{}"'.format(theme_cell, name)]
            ws.conditional_formatting.add(head_range, FormulaRule(formula=rule, fill=fill(l_rgb)))
            ws.conditional_formatting.add(body_range, FormulaRule(formula=rule, fill=fill(l_rgb)))
            ws.conditional_formatting.add(
                "A{r}:F{r}".format(r=top), FormulaRule(formula=rule, fill=fill(s_rgb)))

    for idx in range(1, MAX_GROUPS):
        ws.row_breaks.append(Break(id=idx * block_height))
    return ws


# ---------------------------------------------------------------------------
# גיליון: טופס נקי
# ---------------------------------------------------------------------------
def build_plain(wb):
    ws = wb.create_sheet(SH_PLAIN)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 20, "B": 12, "C": 8, "D": 15, "E": 38, "F": 44})
    title_row(ws, 1, "תורנויות שבת — טופס להדפסה", span="A:F", size=18)
    ws.merge_cells("A2:F2")
    sub = ws.cell(
        row=2, column=1,
        value='=IF({a}$B$4="","בחר תאריך בגיליון «הגדרות»","שבת "&{d}&'
        'IF({a}$B$5=""," "," · פרשת "&{a}$B$5)&"  |  כניסה "&{ct}&"  ·  צאה "&{ht})'.format(
            a=q(SH_SET), d=date_text(q(SH_SET) + "$B$4"),
            ct=time_text(CANDLE), ht=time_text(HAVDALAH)))
    sub.font = f(11, bold=True)
    sub.alignment = align()

    header_row(ws, 3, ["קבוצה", "מתי", "שעה", "קטגוריה", "משימה", "פרטים וכמויות"],
               fill_rgb="333B47")

    S = q(SH_ASSIGN)
    for i in range(ASSIGN_ROWS):
        r, src = 4 + i, 3 + i
        group = ws.cell(
            row=r, column=1,
            value='=IF({s}$A{n}="","",IF({s}$A{n}={s}$A{p},"",{s}$A{n}))'.format(
                s=S, n=src, p=src - 1))
        group.font = f(11, bold=True)
        ws.cell(row=r, column=3,
                value='=IF(N({s}$C{n})=0,"",{t})'.format(s=S, n=src, t=time_text("{}$C{}".format(S, src))))
        for col, letter in ((2, "B"), (4, "E"), (5, "D"), (6, "F")):
            ws.cell(row=r, column=col,
                    value='=IF({s}$A{n}="","",{s}${c}{n}&"")'.format(s=S, c=letter, n=src))
        for col in range(1, 7):
            c = ws.cell(row=r, column=col)
            c.border = box()
            if col != 1:
                c.font = f(10)
            c.alignment = align(v="top", wrap=(col >= 5), h="center" if col in (2, 3, 4) else "right")
        ws.row_dimensions[r].height = 24

    ws.freeze_panes = "A4"
    ws.print_title_rows = "3:3"
    return ws


# ---------------------------------------------------------------------------
# גיליון: צ'קליסט
# ---------------------------------------------------------------------------
def build_checklist(wb):
    ws = wb.create_sheet(SH_CHECK)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 18, "B": 62, "C": 20, "D": 10, "E": 34})
    title_row(ws, 1, "צ'קליסט לוגיסטי", span="A:E", size=18)
    subtitle(ws, 2, "האחריות הטכנית שלא נכנסת לתורנויות: חימום, הבדלה, חשמל, עיתון. "
                    "מסמנים ✔ ככל שמתקדמים.", span="A:E")
    header_row(ws, 3, ["מתי", "משימה", "אחראי", "בוצע", "הערות"])

    rows = read_csv("checklist.csv")
    total = len(rows) + 15
    when_fills = {"תחילת השבוע": "EDF1F6", "חמישי": "F1EBFB", "שישי בבוקר": "E8F0F8",
                  "שישי": "E8F0F8", "שבת": "F3EDE3", "מוצאי שבת": "EDEAF5"}
    for i in range(total):
        r = 4 + i
        row = rows[i] if i < len(rows) else {}
        when = data_cell(ws, r, 1, row.get("מתי") or None, editable=False,
                         center=True, bold=True)
        if row.get("מתי"):
            when.fill = fill(when_fills.get(row["מתי"], BAND))
        data_cell(ws, r, 2, row.get("משימה") or None, editable=False, wrap=True)
        data_cell(ws, r, 3, None, center=True)
        data_cell(ws, r, 4, None, center=True)
        data_cell(ws, r, 5, row.get("הערה") or None, wrap=True)
        ws.row_dimensions[r].height = 24

    last = 3 + total
    dv_list(ws, '"{}"'.format(WINDOWS + ",תחילת השבוע,שישי בבוקר"), "A4:A{}".format(last))
    dv_list(ws, '"✔"', "D4:D{}".format(last))
    ws.conditional_formatting.add(
        "A4:E{}".format(last),
        FormulaRule(formula=['$D4="✔"'], fill=fill("E7F7F2"), font=f(10, color=MUTED)))
    ws.freeze_panes = "A4"
    ws.print_title_rows = "3:3"
    return ws


# ---------------------------------------------------------------------------
# גיליון: תפריט השבת
# ---------------------------------------------------------------------------
def build_menu(wb):
    ws = wb.create_sheet(SH_MENU)
    page(ws, tab=TAB_INPUT)
    widths(ws, {"A": 34, "B": 14, "C": 24, "D": 22, "E": 38})
    title_row(ws, 1, "תפריט השבת", span="A:E", size=18)
    subtitle(ws, 2, "מה מכינים השבת וכמה מכל דבר. הכמות היא מכפיל של המתכון: "
                    "«3» ליד עוגת שמרים = שלוש עוגות. מכאן נבנות רשימת הקניות ובדיקת המלאי.",
             span="A:E")
    header_row(ws, 3, ["מנה", "כמות", "לאיזו ארוחה", "קבוצה אחראית", "הערה"])

    last = 3 + MENU_ROWS
    for i in range(MENU_ROWS):
        r = 4 + i
        data_cell(ws, r, 1, None, bold=True)
        data_cell(ws, r, 2, None, center=True)
        data_cell(ws, r, 3, None, center=True)
        data_cell(ws, r, 4, None, center=True)
        data_cell(ws, r, 5, None, wrap=True)
        ws.row_dimensions[r].height = 22

    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_RECIPES, 2 + RECIPE_ROWS), "A4:A{}".format(last))
    dv_list(ws, '"{}"'.format(MEALS), "C4:C{}".format(last))
    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_GROUPS, 2 + MAX_GROUPS), "D4:D{}".format(last))
    ws.freeze_panes = "A4"
    note_row(ws, last + 2,
             "מנה שאינה מופיעה כאן — הכמויות שלה לא ייכנסו לרשימת הקניות. "
             "מנה שאין לה מתכון ב«מתכונים» אפשר לרשום כאן בכל זאת, ולהוסיף את המצרכים "
             "ידנית בעמודת «תוספת ידנית» שבגיליון «קניות».", last_col=5)
    return ws


# ---------------------------------------------------------------------------
# גיליון: מתכונים
# ---------------------------------------------------------------------------
def build_recipes(wb):
    ws = wb.create_sheet(SH_RECIPES)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 32, "B": 28, "C": 16, "D": 12, "E": 40, "F": 14})
    title_row(ws, 1, "מתכונים", span="A:E", size=18)
    header_row(ws, 2, ["מנה", "מרכיב", "כמות ליחידה אחת", "יחידה", "הערה", "כמות בפועל"])

    last = 2 + RECIPE_ROWS
    menu_last = 3 + MENU_ROWS
    for i in range(RECIPE_ROWS):
        r = 3 + i
        data_cell(ws, r, 1, None, bold=True)
        data_cell(ws, r, 2, None)
        data_cell(ws, r, 3, None, center=True)
        unit = data_cell(
            ws, r, 4,
            '=IF($B{r}="","",IFERROR(VLOOKUP($B{r},{it}$A$3:$B${il},2,FALSE),""))'.format(
                r=r, it=q(SH_ITEMS), il=2 + ITEM_ROWS),
            editable=False, center=True)
        unit.fill = fill(CALC_BG)
        unit.font = f(10, color=MUTED)
        data_cell(ws, r, 5, None, wrap=True)
        actual = ws.cell(
            row=r, column=6,
            value='=IF($A{r}="","",IFERROR($C{r}*VLOOKUP($A{r},{m}$A$4:$B${ml},2,FALSE),0))'.format(
                r=r, m=q(SH_MENU), ml=menu_last))
        actual.font = f(9, color=MUTED)
        ws.row_dimensions[r].height = 20

    ws.column_dimensions["F"].hidden = True
    dv_list(ws, "'{}'!$A$3:$A${}".format(SH_ITEMS, 2 + ITEM_ROWS), "B3:B{}".format(last))
    ws.freeze_panes = "A3"
    note_row(ws, last + 2,
             "ממלאים פעם אחת: לכל מנה — שורה לכל מרכיב, והכמות הדרושה ליחידה אחת "
             "(עוגה אחת, סיר אחד). «כמות בפועל» מוכפלת אוטומטית לפי «תפריט השבת». "
             "מרכיב שאינו ברשימה — מוסיפים אותו קודם בגיליון «מצרכים».", last_col=5)
    return ws


# ---------------------------------------------------------------------------
# גיליון: מצרכים
# ---------------------------------------------------------------------------
def build_items(wb):
    ws = wb.create_sheet(SH_ITEMS)
    page(ws, tab=TAB_REF)
    widths(ws, {"A": 30, "B": 12, "C": 24, "D": 14, "E": 18})
    title_row(ws, 1, "קטלוג מצרכים", span="A:E", size=18)
    header_row(ws, 2, ["מצרך", "יחידה", "קטגוריית קנייה", "מלאי קבוע", "מינימום במלאי"])

    rows = read_csv("ingredients.csv")
    categories = sorted({r["קטגוריית קנייה"] for r in rows})
    for i in range(ITEM_ROWS):
        r = 3 + i
        row = rows[i] if i < len(rows) else {}
        data_cell(ws, r, 1, row.get("מצרך") or None, editable=False, bold=True)
        data_cell(ws, r, 2, row.get("יחידה") or None, editable=False, center=True)
        data_cell(ws, r, 3, row.get("קטגוריית קנייה") or None, editable=False)
        data_cell(ws, r, 4, row.get("מלאי קבוע") or None, editable=False, center=True)
        minimum = row.get("מינימום במלאי") or None
        data_cell(ws, r, 5, float(minimum) if minimum else None, center=True)
        ws.row_dimensions[r].height = 20

    last = 2 + ITEM_ROWS
    dv_list(ws, '"{}"'.format(",".join(categories)), "C3:C{}".format(last))
    dv_list(ws, '"כן,לא"', "D3:D{}".format(last))
    ws.freeze_panes = "A3"
    note_row(ws, last + 2,
             "«מלאי קבוע = כן» אומר שהמצרך נמצא תמיד במטבח: הוא לא ייכנס לרשימת הקניות "
             "אלא לגיליון «לבדוק במטבח». כל שינוי כאן משנה את שתי הרשימות.", last_col=5)
    return ws


# ---------------------------------------------------------------------------
# גיליונות: קניות · לבדוק במטבח
# ---------------------------------------------------------------------------
NUM_FMT = '0.##;-0.##;'          # אפס מוצג כתא ריק


def _needed(item_ref):
    return '=SUMIF({rc}$B$3:$B${rl},{ref},{rc}$F$3:$F${rl})'.format(
        rc=q(SH_RECIPES), rl=2 + RECIPE_ROWS, ref=item_ref)


def build_shopping(wb):
    ws = wb.create_sheet(SH_SHOP)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 22, "B": 30, "C": 14, "D": 14, "E": 12, "F": 12, "G": 9})
    title_row(ws, 1, "רשימת קניות", span="A:G", size=18)
    subtitle(ws, 2, "מחושב מ«תפריט השבת» × «מתכונים». עמודת «תוספת ידנית» היא לכל מה שלא "
                    "עובר דרך מתכון — פירות לקידוש, חלב, פיצוחים לטיש. "
                    "מצרכי מלאי קבוע אינם כאן אלא בגיליון «לבדוק במטבח».", span="A:G")
    header_row(ws, 3, ["קטגוריה", "מצרך", "ממתכונים", "תוספת ידנית", "סה\"כ",
                       "יחידה", "נקנה"])

    rows = [r for r in read_csv("ingredients.csv") if r["מלאי קבוע"] != "כן"]
    rows.sort(key=lambda r: (r["קטגוריית קנייה"], r["מצרך"]))

    r = 4
    for row in rows:
        data_cell(ws, r, 1, row["קטגוריית קנייה"], editable=False, center=True)
        data_cell(ws, r, 2, row["מצרך"], editable=False, bold=True)
        calc = data_cell(ws, r, 3, _needed("$B{}".format(r)), editable=False,
                         center=True, fmt=NUM_FMT)
        calc.fill = fill(CALC_BG)
        data_cell(ws, r, 4, None, center=True, fmt=NUM_FMT)
        total = data_cell(ws, r, 5, "=N($C{r})+N($D{r})".format(r=r), editable=False,
                          center=True, bold=True, fmt=NUM_FMT)
        total.fill = fill(CALC_BG)
        data_cell(ws, r, 6, row["יחידה"], editable=False, center=True)
        data_cell(ws, r, 7, None, center=True)
        ws.row_dimensions[r].height = 20
        r += 1

    extra_start = r
    for _ in range(EXTRA_SHOP_ROWS):
        data_cell(ws, r, 1, None, center=True)
        data_cell(ws, r, 2, None, bold=True)
        data_cell(ws, r, 3, None, editable=False, center=True)
        data_cell(ws, r, 4, None, center=True, fmt=NUM_FMT)
        total = data_cell(ws, r, 5, "=N($C{r})+N($D{r})".format(r=r), editable=False,
                          center=True, bold=True, fmt=NUM_FMT)
        total.fill = fill(CALC_BG)
        data_cell(ws, r, 6, None, center=True)
        data_cell(ws, r, 7, None, center=True)
        ws.row_dimensions[r].height = 20
        r += 1

    last = r - 1
    ws.conditional_formatting.add(
        "A4:G{}".format(last),
        FormulaRule(formula=["$E4>0"], fill=fill("E7F7F2"), font=f(11, bold=True)))
    ws.conditional_formatting.add(
        "A4:G{}".format(last),
        FormulaRule(formula=['$G4="✔"'], fill=fill(BAND), font=f(10, color=MUTED)))
    dv_list(ws, '"✔"', "G4:G{}".format(last))
    ws.auto_filter.ref = "A3:G{}".format(last)
    ws.freeze_panes = "A4"
    ws.print_title_rows = "3:3"
    note_row(ws, last + 2,
             "השורות המודגשות הן מה שצריך לקנות בפועל. אפשר לסנן לפי עמודת «סה\"כ» או "
             "לפי קטגוריה, ולהדפיס. {} השורות האחרונות פנויות למצרכים שאינם בקטלוג.".format(
                 EXTRA_SHOP_ROWS), last_col=7)
    return ws


def build_pantry(wb):
    ws = wb.create_sheet(SH_PANTRY)
    page(ws, tab=TAB_OUTPUT)
    widths(ws, {"A": 30, "B": 16, "C": 18, "D": 12, "E": 14, "F": 34})
    title_row(ws, 1, "לבדוק במטבח", span="A:F", size=18)
    subtitle(ws, 2, "מצרכים שנמצאים תמיד במטבח — לא קונים אותם אוטומטית, רק מוודאים "
                    "שיש מספיק. «דרוש השבת» מחושב מהמתכונים; «מינימום» הוא הרף שהגדרתם "
                    "בקטלוג המצרכים.", span="A:F")
    header_row(ws, 3, ["מצרך", "דרוש השבת", "מינימום במלאי", "יחידה", "יש מספיק?", "הערה"])

    rows = [r for r in read_csv("ingredients.csv") if r["מלאי קבוע"] == "כן"]
    rows.sort(key=lambda r: (r["קטגוריית קנייה"], r["מצרך"]))

    for i, row in enumerate(rows):
        r = 4 + i
        data_cell(ws, r, 1, row["מצרך"], editable=False, bold=True)
        need = data_cell(ws, r, 2, _needed("$A{}".format(r)), editable=False,
                         center=True, fmt=NUM_FMT)
        need.fill = fill(CALC_BG)
        minimum = row.get("מינימום במלאי") or None
        data_cell(ws, r, 3, float(minimum) if minimum else None, editable=False,
                  center=True, fmt=NUM_FMT)
        data_cell(ws, r, 4, row["יחידה"], editable=False, center=True)
        data_cell(ws, r, 5, None, center=True)
        data_cell(ws, r, 6, None, wrap=True)
        ws.row_dimensions[r].height = 20

    last = 3 + len(rows)
    ws.conditional_formatting.add(
        "A4:F{}".format(last),
        FormulaRule(formula=["$B4>0"], fill=fill("FDF1DF"), font=f(11, bold=True)))
    ws.conditional_formatting.add(
        "A4:F{}".format(last),
        FormulaRule(formula=['$E4="חסר"'], fill=fill(WARN_BG),
                    font=f(11, bold=True, color=WARN_INK)))
    dv_list(ws, '"יש,חסר"', "E4:E{}".format(last))
    ws.freeze_panes = "A4"
    ws.print_title_rows = "3:3"
    note_row(ws, last + 2,
             "מסומן בכתום = המתכונים של השבת צורכים ממנו. סימון «חסר» מדליק את השורה "
             "באדום — זה מה שצריך להוסיף להזמנה.", last_col=6)
    return ws


# ---------------------------------------------------------------------------
def main():
    wb = Workbook()
    wb.remove(wb.active)
    build_help(wb)
    build_settings(wb)
    build_schedule(wb)
    build_cards(wb)
    build_plain(wb)
    build_checklist(wb)
    build_shopping(wb)
    build_pantry(wb)
    build_assign(wb)
    build_menu(wb)
    build_students(wb)
    build_groups(wb)
    build_tasks(wb)
    build_recipes(wb)
    build_items(wb)
    build_zmanim(wb)
    wb.active = 0
    wb.save(OUT)
    print("נוצר: {} ({} גיליונות)".format(OUT, len(wb.sheetnames)))


if __name__ == "__main__":
    main()
