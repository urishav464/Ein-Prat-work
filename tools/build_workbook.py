# -*- coding: utf-8 -*-
"""מחולל חוברת "תכנון שבת" (shabbat-planner.xlsx) — עין פרת.

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
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.properties import PageSetupProperties

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "shabbat-planner.xlsx"

# --- שמות גיליונות ---------------------------------------------------------
SH_HELP, SH_SET, SH_SCHED = "הוראות", "הגדרות", "לוז"
SH_ZMAN, SH_GROUPS, SH_TASKS = "זמנים", "קבוצות", "מאגר משימות"
SH_ASSIGN, SH_CARDS, SH_PLAIN = "שיבוץ", "כרטיסיות", "טופס נקי"

MAX_GROUPS = 6            # מספר הקבוצות הנתמך בכרטיסיות
CARD_TASK_ROWS = 16       # שורות משימה בכל כרטיסייה
ASSIGN_ROWS = 150         # שורות בגיליון השיבוץ

# --- צבעים ------------------------------------------------------------------
INK = "1F2430"
MUTED = "6B7280"
LINE = "C9CFD8"
BAND = "EDF1F6"
ACCENT = "2E5C8A"
INPUT_BG = "FFF9E3"

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


CANDLE = q(SH_SET) + "$B$10"      # כניסת שבת בפועל
HAVDALAH = q(SH_SET) + "$B$11"    # צאת שבת בפועל



def date_text(ref):
    """תאריך כטקסט בלי להסתמך על קודי פורמט מתורגמים (אקסל בעברית)."""
    return 'TEXT(DAY({r}),"00")&"/"&TEXT(MONTH({r}),"00")&"/"&TEXT(YEAR({r}),"0000")'.format(r=ref)


def time_text(ref):
    return 'TEXT(HOUR({r}),"00")&":"&TEXT(MINUTE({r}),"00")'.format(r=ref)


def page(ws, landscape=False, fit=True, rtl=True):
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


def read_csv(name):
    with (DATA / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def as_time(text):
    h, m = text.split(":")
    return time(int(h), int(m))


# ---------------------------------------------------------------------------
# גיליון: הוראות
# ---------------------------------------------------------------------------
def build_help(wb):
    ws = wb.create_sheet(SH_HELP)
    page(ws)
    widths(ws, {"A": 4, "B": 92})
    title_row(ws, 1, "תכנון שבת — מדרשת עין פרת", span="A:B", size=20)

    steps = [
        ("מה עושים כל שבוע (5 דקות)", None),
        ("1", "גיליון «הגדרות» — בוחרים תאריך שבת מהרשימה. כניסת השבת וצאתה נטענות לבד."),
        ("2", "באותו גיליון — ממלאים את המרחבים (קבלת שבת ישראלית, קידוש, חבורות, טיש, סעודה שלישית) ואת אנשי הצוות."),
        ("3", "גיליון «לוז» מוכן ומודפס. אין מה למלא בו — כל השעות נגזרות מזמני השבת."),
        ("4", "גיליון «קבוצות» — מעדכנים מי בכל קבוצה (רק כשההרכב משתנה)."),
        ("5", "גיליון «שיבוץ» — קובעים מי עושה מה. בוחרים קבוצה, חלון זמן ומשימה מהרשימות, ומוסיפים כמויות בעמודת הפרטים."),
        ("6", "מדפיסים: «כרטיסיות» לתצוגה הצבעונית (דף לקבוצה, טוב גם לצילום מסך לוואטסאפ) או «טופס נקי» להדפסה מהירה של הכל בדף אחד."),
        ("", None),
        ("טיפים", None),
        ("•", "שכחת להזין תאריך? כל הגיליונות יישארו ריקים עד שתבחר אחד."),
        ("•", "הזמנים בגיליון «זמנים» מחושבים לירושלים ומדויקים לדקה-שתיים. אם הלוח שלך אומר אחרת — פשוט תקן את השורה, או הזן עקיפה ידנית ב«הגדרות»."),
        ("•", "בגיליון «לוז» יש התראה אוטומטית כשנשארת פחות משעה בין החבורה עם איש הצוות לסעודה שלישית — בדיוק המקרה שדורש החלטה."),
        ("•", "המשימות בכרטיסייה מופיעות בסדר שבו הזנת אותן ב«שיבוץ». כדאי להזין לפי הסדר: שישי, שבת, מוצאי שבת."),
        ("•", "לשמור עותק לכל שבת: קובץ ← שמירה בשם ← «שבת פרשת ___»."),
    ]
    row = 3
    for key, text in steps:
        if text is None:
            c = ws.cell(row=row, column=1, value=key)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
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
            ws.row_dimensions[row].height = 32
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
}

SETTINGS_DEFAULTS = {
    18: "בית מיכאל",
    19: "חדר אוכל",
}


def build_settings(wb):
    ws = wb.create_sheet(SH_SET)
    page(ws)
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
        else:  # result
            val.value = formula
            val.font = f(13, bold=True, color=ACCENT)
            val.fill = fill("E8F0F8")

        if row in (6, 7, 8, 9, 10, 11):
            val.number_format = "hh:mm"
        if row == 4:
            val.number_format = "dd/mm/yyyy"

        hint = ws.cell(row=row, column=3, value=SETTINGS_HINTS.get(row, ""))
        hint.font = f(10, color=MUTED, italic=True)
        hint.alignment = align()
        ws.row_dimensions[row].height = 22

    dv_date = DataValidation(
        type="list", formula1="'{}'!$A$3:$A$400".format(SH_ZMAN), allow_blank=True
    )
    dv_date.error = "בחר תאריך מרשימת השבתות בגיליון «זמנים»"
    ws.add_data_validation(dv_date)
    dv_date.add(ws["B4"])

    dv_seuda = DataValidation(type="list", formula1='"חדר אוכל,בית שקד"', allow_blank=True)
    dv_seuda.showErrorMessage = False
    ws.add_data_validation(dv_seuda)
    dv_seuda.add(ws["B19"])

    ws.freeze_panes = "A2"
    return ws


# ---------------------------------------------------------------------------
# גיליון: לוז
# ---------------------------------------------------------------------------
def build_schedule(wb):
    ws = wb.create_sheet(SH_SCHED)
    page(ws)
    widths(ws, {"A": 12, "B": 10, "C": 34, "D": 22, "E": 16, "F": 40})

    title_row(ws, 1, "לוח זמנים לשבת", span="A:F", size=20)
    sub = ws.cell(
        row=2,
        column=1,
        value='=IF({s}$B$4="","בחר תאריך בגיליון «הגדרות»","שבת "&{d}&'
        'IF({s}$B$5=""," "," · פרשת "&{s}$B$5)&"  |  כניסה "&{ct}&"  ·  צאה "&{ht})'.format(
            s=q(SH_SET), d=date_text(q(SH_SET) + "$B$4"), ct=time_text(CANDLE), ht=time_text(HAVDALAH)
        ),
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
         "={}$B$14".format(S), "", "כשעה לפני כניסת השבת"),
        ("", guard(CANDLE), "כניסת שבת", "", "", "הדלקת נרות"),
        ("", guard("$B$5+TIME(0,15,0)"), "קבלת שבת וערבית", "בית מיכאל", "", "כ-15 דקות אחרי כניסת השבת"),
        ("", guard("MAX($B$6+TIME(1,30,0),TIME(18,30,0))"), "סעודת שבת", "חדר אוכל", "",
         "כשעה וחצי אחרי תחילת קבלת שבת, ולא לפני 18:30"),
        ("", guard("$B$7+TIME(1,30,0)"), "טיש עם איש צוות", "={}$B$17".format(S),
         "={}$B$22".format(S), "כשעה וחצי אחרי תחילת הסעודה"),
        ("יום שבת", time(11, 0), "קידוש", "={}$B$15".format(S), "", ""),
        ("", time(11, 45), "חבורות חניכים", "={}$B$16".format(S), "", "מחולקים לפי מספר החבורות"),
        ("", time(12, 30), "ארוחת צהריים", "חדר אוכל", "", ""),
        ("", time(15, 0), "חבורה עם איש צוות", "={}$B$18".format(S), "={}$B$23".format(S),
         '=IF({h}="","",IF(($B$13-TIME(15,0,0))<TIME(1,0,0),'
         '"⚠ פחות משעה עד סעודה שלישית — לשקול שינוי",""))'.format(h=HAVDALAH)),
        ("", guard("{}-TIME(1,30,0)".format(HAVDALAH), HAVDALAH), "סעודה שלישית",
         "={}$B$19".format(S), "", "כשעה וחצי לפני צאת השבת"),
        ("", guard(HAVDALAH, HAVDALAH), "הבדלה", "", "", ""),
        ("מוצאי שבת", guard("{}+TIME(0,10,0)".format(HAVDALAH), HAVDALAH),
         "ניקיונות וארגון הקמפוס", "הקמפוס", "", "10 דקות אחרי צאת השבת"),
        ("", guard("CEILING({}+TIME(2,0,0),TIME(0,30,0))".format(HAVDALAH), HAVDALAH),
         "כריכה לכריכה — תנ\"ך עם איש צוות", "", "={}$B$24".format(S),
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
        FormulaRule(formula=['LEFT($F4,1)="⚠"'], fill=fill("FCE3C6"), font=f(11, bold=True, color="8A4B00")),
    )
    ws.freeze_panes = "A4"

    note = ws.cell(row=last + 2, column=1,
                   value="השעות נגזרות אוטומטית מכניסת/צאת השבת שבגיליון «הגדרות». כדי לשנות — עדכנו שם, לא כאן.")
    ws.merge_cells(start_row=last + 2, start_column=1, end_row=last + 2, end_column=6)
    note.font = f(10, color=MUTED, italic=True)
    note.alignment = align()
    return ws


# ---------------------------------------------------------------------------
# גיליון: זמנים
# ---------------------------------------------------------------------------
def build_zmanim(wb):
    ws = wb.create_sheet(SH_ZMAN)
    page(ws)
    widths(ws, {"A": 16, "B": 26, "C": 14, "D": 14, "E": 46})
    title_row(ws, 1, "לוח שבתות — זמני ירושלים", span="A:E", size=16)
    header_row(ws, 2, ["תאריך", "פרשה", "כניסת שבת", "צאת שבת", ""])
    ws["E2"] = "ניתן לעריכה"
    ws["E2"].font = f(11, bold=True, color="FFFFFF")
    ws["E2"].fill = fill(ACCENT)
    ws["E2"].alignment = align(h="center")

    for i, row in enumerate(read_csv("zmanim.csv")):
        r = 3 + i
        d = datetime.strptime(row["תאריך"], "%d/%m/%Y").date()
        cells = [
            (1, d, "dd/mm/yyyy"),
            (2, row["פרשה"], None),
            (3, as_time(row["כניסת שבת"]), "hh:mm"),
            (4, as_time(row["צאת שבת"]), "hh:mm"),
        ]
        for col, val, fmt in cells:
            c = ws.cell(row=r, column=col, value=val)
            c.border = box()
            c.alignment = align(h="center" if col != 2 else "right")
            c.font = f(11)
            if fmt:
                c.number_format = fmt
            if col in (3, 4):
                c.fill = fill(INPUT_BG)
    ws.freeze_panes = "A3"

    hint = ws.cell(row=3, column=5,
                   value="הזמנים מחושבים לירושלים (כניסה 40 דק' לפני השקיעה, צאה 40 דק' אחריה) ומדויקים לדקה-שתיים. "
                         "אם הלוח שלך אומר אחרת — פשוט תקנו את השורה, הצבע הצהוב מסמן שדה שמותר לשנות.")
    ws.merge_cells("E3:E8")
    hint.font = f(10, color=MUTED, italic=True)
    hint.alignment = align(v="top", wrap=True)
    return ws


# ---------------------------------------------------------------------------
# גיליון: קבוצות
# ---------------------------------------------------------------------------
def build_groups(wb):
    ws = wb.create_sheet(SH_GROUPS)
    page(ws, landscape=True)
    widths(ws, {"A": 26, "B": 18, "C": 96, "D": 14})
    title_row(ws, 1, "קבוצות האחריות", span="A:D", size=18)
    header_row(ws, 2, ["קבוצה", "מוביל/ה", "חניכים (מופרדים בפסיק)", "ערכת צבע"])

    sample = read_csv("groups_sample.csv")
    for i in range(MAX_GROUPS):
        r = 3 + i
        row = sample[i] if i < len(sample) else {}
        values = [
            row.get("קבוצה", ""),
            row.get("מוביל/ה", ""),
            row.get("חניכים", ""),
            row.get("ערכת צבע", THEME_ORDER[i]),
        ]
        for col, val in enumerate(values, start=1):
            c = ws.cell(row=r, column=col, value=val or None)
            c.border = box()
            c.alignment = align(wrap=(col == 3), h="center" if col == 4 else "right")
            c.font = f(11, bold=(col == 1))
            c.fill = fill(INPUT_BG)
        ws.row_dimensions[r].height = 46

    dv = DataValidation(type="list", formula1='"{}"'.format(",".join(THEME_ORDER)), allow_blank=True)
    dv.showErrorMessage = False
    ws.add_data_validation(dv)
    dv.add("D3:D{}".format(2 + MAX_GROUPS))

    note = ws.cell(row=4 + MAX_GROUPS, column=1,
                   value="עדכנו כאן רק כשהרכב הקבוצות משתנה. ערכת הצבע קובעת את צבע הכרטיסייה בגיליון «כרטיסיות».")
    ws.merge_cells(start_row=4 + MAX_GROUPS, start_column=1, end_row=4 + MAX_GROUPS, end_column=4)
    note.font = f(10, color=MUTED, italic=True)
    note.alignment = align()
    ws.freeze_panes = "A3"
    return ws


# ---------------------------------------------------------------------------
# גיליון: מאגר משימות
# ---------------------------------------------------------------------------
def build_tasks(wb):
    ws = wb.create_sheet(SH_TASKS)
    page(ws)
    widths(ws, {"A": 24, "B": 16, "C": 86})
    title_row(ws, 1, "מאגר משימות קבוע", span="A:C", size=18)
    header_row(ws, 2, ["תחום אחריות", "חלון זמן", "משימה"])

    rows = read_csv("task_library.csv")
    area_colors = {}
    for i, row in enumerate(rows):
        r = 3 + i
        area = row["תחום אחריות"]
        area_colors.setdefault(area, BAND if len(area_colors) % 2 == 0 else "F7F9FC")
        for col, key in enumerate(["תחום אחריות", "חלון זמן", "משימה"], start=1):
            c = ws.cell(row=r, column=col, value=row[key])
            c.border = box()
            c.alignment = align(wrap=(col == 3), h="center" if col == 2 else "right")
            c.font = f(11, bold=(col == 1))
            if col == 1:
                c.fill = fill(area_colors[area])
        ws.row_dimensions[r].height = 20
    ws.freeze_panes = "A3"

    end = 3 + len(rows) + 1
    note = ws.cell(row=end, column=1,
                   value="זו רשימת ההיצע לגיליון «שיבוץ». מותר ורצוי להוסיף, למחוק ולתקן שורות — הרשימה הנגללת מתעדכנת לבד.")
    ws.merge_cells(start_row=end, start_column=1, end_row=end, end_column=3)
    note.font = f(10, color=MUTED, italic=True)
    note.alignment = align()
    return ws


# ---------------------------------------------------------------------------
# גיליון: שיבוץ
# ---------------------------------------------------------------------------
SAMPLE_ASSIGNMENTS = [
    ("קבוצה של יעל + ארבל", "שישי", "אפיית חלות", ""),
    ("קבוצה של יעל + ארבל", "שישי", "בייגל בייטס", "כפול 1 ק\"ג קמח תופח"),
    ("קבוצה של יעל + ארבל", "שישי", "פנקייקים", "כ-30 יחידות"),
    ("קבוצה של יעל + ארבל", "שישי", "שטיפת חדר אוכל ועריכתו", ""),
    ("קבוצה של יעל + ארבל", "שבת", "הכנסת מאפים לחימום (10:00)", "בייגל בייטס, עוגיות, עוגות שמרים, חלות לצהריים, חלה נתלשת, פנקייקים, בית לזית, ג'חנון, עוגות בננה. ללא אלומיניום מעל העוגות"),
    ("קבוצה של יעל + ארבל", "שבת", "סידור פינת קפה", "ניקוי, הוצאת חלב, מילוי קפה וסוכר"),
    ("קבוצה של יעל + ארבל", "שבת", "טאטוא הרצפה וסידור כיסאות", "שיהיה נעים במרחב"),
    ("קבוצה של יעל + ארבל", "שבת", "הוצאת פירות וחיתוך", "8 פומלות, ק\"ג קיווי, 3 קופסאות פסיפלורה"),
    ("קבוצה של יעל + ארבל", "שבת", "הוצאת עוגות וכלים וסידור שולחנות", "עוגות חלביות, בייגל בייטס ולבנה, עוגיות שוקולד צ'יפס, בית לזית, פנקייקים, כנאפה, קורנפלקס. קערות, צלחות, כפות, כפיות. כיסאות במעגל"),
    ("קבוצה של יעל + ארבל", "שבת", "קיפול והכנסה למקרר בסיום", "לא להשאיר אוכל פתוח"),
    ("קבוצה של יעל + ארבל", "מוצאי שבת", "בית מדרש", ""),

    ("קבוצה של מיקה", "שישי", "שטיפת בית המדרש וסידור בית הכנסת", ""),
    ("קבוצה של מיקה", "שישי", "הבאת ספות משנה א' וסידורן", "לסדר בדק, שני שולחנות באמצע"),
    ("קבוצה של מיקה", "שישי", "ניקוי השירותים", "אקונומיקה, נייר טואלט וניירות ניגוב"),
    ("קבוצה של מיקה", "שבת", "הנחת אוכל בתנור החימום (11:00)", ""),
    ("קבוצה של מיקה", "שבת", "עריכת שולחנות (13:00)", "כפות הגשה, חלוקת סלטים לשולחנות, פינוי בסיום"),
    ("קבוצה של מיקה", "מוצאי שבת", "החזרת הספות למקומן", ""),
    ("קבוצה של מיקה", "מוצאי שבת", "שטיפת בית המדרש", ""),

    ("קבוצה של הילה", "שישי", "אפייה", "עוגת ביסקוויטים גבינה, 3 עוגות בננה עם שוקו צ'יפס, 3 ק\"ג שמרים, עוגיות שוקולד צ'יפס, 2 עוגות גזר, כדורי שוקולד פרווה"),
    ("קבוצה של הילה", "שישי", "שטיפת מטבח", "כולל הכל"),
    ("קבוצה של הילה", "שישי", "טיש — טאטוא הרצפה אחרי ארוחת ערב", ""),
    ("קבוצה של הילה", "שישי", "טיש — סידור וניקוי שולחנות בקוביה וכיסאות מסביב", ""),
    ("קבוצה של הילה", "שישי", "טיש — שתייה, כוסות, כדורי שוקולד וחימום עוגות פרווה", ""),
    ("קבוצה של הילה", "שישי", "טיש — ניקיון מלא בסיום", ""),
    ("קבוצה של הילה", "שבת", "סעודה שלישית — הכנסת מה שנותר לחימום והבאה אל שקד", ""),
    ("קבוצה של הילה", "מוצאי שבת", "ניקיון מטבח", ""),

    ("הקבוצה של שטה", "שישי", "סלטים", "מטבוחה, סלט ביצים 50 ביצים"),
    ("הקבוצה של שטה", "שישי", "ארוחת צהריים של שישי", "70 ביצים קשות, 10 בצלים קצוצים דק, סלט ירקות, פטרוזיליה, חצילים מטוגנים, טחינה, סחוג, צ'יפס, לחמם פיתות"),
    ("הקבוצה של שטה", "שישי", "פריקת האוכל בצהריים (14:00)", ""),
    ("הקבוצה של שטה", "שישי", "הנחת האוכל על הפלטות (17:00)", ""),
    ("הקבוצה של שטה", "שישי", "עריכת שולחנות (18:00)", "כפות הגשה, חלוקת סלטים, פינוי בסיום הארוחה"),
    ("הקבוצה של שטה", "מוצאי שבת", "ניקיון מטבח", "כיריים, כיורים, מזווה, פינוי כלים בייבוש"),
]


def build_assign(wb):
    ws = wb.create_sheet(SH_ASSIGN)
    page(ws, landscape=True)
    widths(ws, {"A": 24, "B": 14, "C": 44, "D": 60, "E": 10, "F": 22})
    title_row(ws, 1, "שיבוץ תורנויות לשבת", span="A:E", size=18)
    header_row(ws, 2, ["קבוצה", "חלון זמן", "משימה", "פרטים וכמויות", "בוצע", "מפתח (אל תיגעו)"])

    for i in range(ASSIGN_ROWS):
        r = 3 + i
        sample = SAMPLE_ASSIGNMENTS[i] if i < len(SAMPLE_ASSIGNMENTS) else ("", "", "", "")
        for col, val in enumerate(sample, start=1):
            c = ws.cell(row=r, column=col, value=val or None)
            c.border = box()
            c.alignment = align(wrap=(col == 4), h="center" if col == 2 else "right")
            c.font = f(11, bold=(col == 1))
            c.fill = fill(INPUT_BG if col != 1 else "FFFDF0")
        done = ws.cell(row=r, column=5)
        done.border = box()
        done.alignment = align(h="center")
        key = ws.cell(
            row=r,
            column=6,
            value='=IF($A{r}="","",$A{r}&"|"&COUNTIF($A$3:$A{r},$A{r}))'.format(r=r),
        )
        key.font = f(9, color=MUTED)
        ws.row_dimensions[r].height = 30

    ws.column_dimensions["F"].hidden = True
    last = 2 + ASSIGN_ROWS

    dv_group = DataValidation(
        type="list", formula1="'{}'!$A$3:$A${}".format(SH_GROUPS, 2 + MAX_GROUPS), allow_blank=True
    )
    dv_group.showErrorMessage = False
    ws.add_data_validation(dv_group)
    dv_group.add("A3:A{}".format(last))

    dv_win = DataValidation(type="list", formula1='"שישי,שבת,מוצאי שבת"', allow_blank=True)
    dv_win.showErrorMessage = False
    ws.add_data_validation(dv_win)
    dv_win.add("B3:B{}".format(last))

    dv_task = DataValidation(type="list", formula1="'{}'!$C$3:$C$200".format(SH_TASKS), allow_blank=True)
    dv_task.showErrorMessage = False   # מותר גם טקסט חופשי
    ws.add_data_validation(dv_task)
    dv_task.add("C3:C{}".format(last))

    dv_done = DataValidation(type="list", formula1='"✔"', allow_blank=True)
    dv_done.showErrorMessage = False
    ws.add_data_validation(dv_done)
    dv_done.add("E3:E{}".format(last))

    ws.freeze_panes = "A3"
    return ws


# ---------------------------------------------------------------------------
# גיליון: כרטיסיות
# ---------------------------------------------------------------------------
def build_cards(wb):
    ws = wb.create_sheet(SH_CARDS)
    page(ws)
    widths(ws, {"A": 13, "B": 16, "C": 16, "D": 16, "E": 15, "F": 15, "H": 12, "I": 12, "J": 12})
    for col in ("H", "I", "J"):
        ws.column_dimensions[col].hidden = True

    block_height = CARD_TASK_ROWS + 6
    G, A, S = q(SH_GROUPS), q(SH_SET), q(SH_ASSIGN)

    for idx in range(MAX_GROUPS):
        top = 1 + idx * block_height
        grow = 3 + idx                      # שורת הקבוצה בגיליון «קבוצות»
        gref = "{g}$A${r}".format(g=G, r=grow)
        theme_cell = "{g}$D${r}".format(g=G, r=grow)
        strong, light = THEMES[THEME_ORDER[idx]]

        # כותרת
        ws.merge_cells(start_row=top, start_column=1, end_row=top, end_column=6)
        c = ws.cell(row=top, column=1, value='=IF({r}="","",{r})'.format(r=gref))
        c.font = f(24, bold=True)
        c.alignment = align(h="center")
        c.fill = fill(strong)
        ws.row_dimensions[top].height = 42

        # חניכים
        ws.merge_cells(start_row=top + 1, start_column=1, end_row=top + 1, end_column=6)
        c = ws.cell(row=top + 1, column=1,
                    value='=IF({g}$C${r}="","",{g}$C${r})'.format(g=G, r=grow))
        c.font = f(12, bold=True)
        c.alignment = align(h="center", wrap=True)
        c.fill = fill(light)
        ws.row_dimensions[top + 1].height = 54

        # שורת שבת
        ws.merge_cells(start_row=top + 2, start_column=1, end_row=top + 2, end_column=6)
        c = ws.cell(
            row=top + 2, column=1,
            value='=IF({a}$B$4="","","שבת "&{d}&IF({a}$B$5=""," "," · פרשת "&{a}$B$5))'.format(
                a=A, d=date_text(A + "$B$4")),
        )
        c.font = f(11, italic=True, color=MUTED)
        c.alignment = align(h="center")
        c.fill = fill(light)
        ws.row_dimensions[top + 2].height = 20

        # כותרות טבלה
        hdr = top + 3
        ws.merge_cells(start_row=hdr, start_column=2, end_row=hdr, end_column=4)
        ws.merge_cells(start_row=hdr, start_column=5, end_row=hdr, end_column=6)
        for col, text in ((1, "מתי"), (2, "משימה"), (5, "פרטים וכמויות")):
            h = ws.cell(row=hdr, column=col, value=text)
            h.font = f(11, bold=True, color="FFFFFF")
            h.fill = fill(ACCENT)
            h.alignment = align(h="center")
            h.border = box()
        ws.row_dimensions[hdr].height = 22

        # שורות משימה
        for n in range(1, CARD_TASK_ROWS + 1):
            r = hdr + n
            lookup = ('=IFERROR(INDEX({s}${col}$3:${col}${last},'
                      'MATCH({g}&"|"&{n},{s}$F$3:$F${last},0))&"","")')
            last = 2 + ASSIGN_ROWS
            ws.cell(row=r, column=8, value=lookup.format(s=S, col="B", g=gref, n=n, last=last))
            ws.cell(row=r, column=9, value=lookup.format(s=S, col="C", g=gref, n=n, last=last))
            ws.cell(row=r, column=10, value=lookup.format(s=S, col="D", g=gref, n=n, last=last))

            when = ws.cell(
                row=r, column=1,
                value='=IF($H{r}="","",IF($H{r}=$H{p},"",$H{r}))'.format(r=r, p=r - 1),
            )
            when.font = f(11, bold=True, color=ACCENT)
            when.alignment = align(h="center", v="top")
            when.fill = fill(light)
            when.border = box()

            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
            task = ws.cell(row=r, column=2, value="=$I{}".format(r))
            task.font = f(11, bold=True)
            task.alignment = align(v="top", wrap=True)
            task.border = box()

            ws.merge_cells(start_row=r, start_column=5, end_row=r, end_column=6)
            det = ws.cell(row=r, column=5, value="=$J{}".format(r))
            det.font = f(10, color=MUTED)
            det.alignment = align(v="top", wrap=True)
            det.border = box()

            for col in (3, 4, 6):
                ws.cell(row=r, column=col).border = box()
            ws.row_dimensions[r].height = 30

        # התראה כשיש לקבוצה יותר משימות ממה שנכנס לכרטיסייה
        warn = hdr + CARD_TASK_ROWS + 1
        ws.merge_cells(start_row=warn, start_column=1, end_row=warn, end_column=6)
        w = ws.cell(
            row=warn, column=1,
            value='=IF(COUNTIF({s}$A$3:$A${last},{g})>{n},'
                  '"⚠ לקבוצה יש עוד משימות שלא נכנסו לכרטיסייה — ראו «טופס נקי»","")'.format(
                      s=S, last=2 + ASSIGN_ROWS, g=gref, n=CARD_TASK_ROWS),
        )
        w.font = f(10, bold=True, color="8A4B00")
        w.alignment = align(h="center")
        ws.row_dimensions[warn].height = 18

        # צביעה דינמית לפי ערכת הצבע שנבחרה בגיליון «קבוצות»
        head_range = "A{}:F{}".format(top + 1, top + 2)
        body_range = "A{}:A{}".format(hdr + 1, hdr + CARD_TASK_ROWS)
        for name, (s_rgb, l_rgb) in THEMES.items():
            rule_head = FormulaRule(formula=['{}="{}"'.format(theme_cell, name)], fill=fill(l_rgb), stopIfTrue=False)
            ws.conditional_formatting.add(head_range, rule_head)
            ws.conditional_formatting.add(
                body_range, FormulaRule(formula=['{}="{}"'.format(theme_cell, name)], fill=fill(l_rgb))
            )
        # הכותרת עצמה בגוון החזק
        for name, (s_rgb, _l) in THEMES.items():
            ws.conditional_formatting.add(
                "A{r}:F{r}".format(r=top),
                FormulaRule(formula=['{}="{}"'.format(theme_cell, name)], fill=fill(s_rgb)),
            )

    # מעברי עמוד — כרטיסייה לדף
    for idx in range(1, MAX_GROUPS):
        ws.row_breaks.append(Break(id=idx * block_height))
    return ws


# ---------------------------------------------------------------------------
# גיליון: טופס נקי
# ---------------------------------------------------------------------------
def build_plain(wb):
    ws = wb.create_sheet(SH_PLAIN)
    page(ws)
    widths(ws, {"A": 24, "B": 13, "C": 40, "D": 52})
    title_row(ws, 1, "תורנויות שבת — טופס להדפסה", span="A:D", size=18)
    sub = ws.cell(
        row=2, column=1,
        value='=IF({a}$B$4="","בחר תאריך בגיליון «הגדרות»","שבת "&{d}&'
        'IF({a}$B$5=""," "," · פרשת "&{a}$B$5)&"  |  כניסה "&{ct}&"  ·  צאה "&{ht})'.format(
            a=q(SH_SET), d=date_text(q(SH_SET) + "$B$4"), ct=time_text(CANDLE), ht=time_text(HAVDALAH)),
    )
    ws.merge_cells("A2:D2")
    sub.font = f(11, bold=True)
    sub.alignment = align()

    header_row(ws, 3, ["קבוצה", "מתי", "משימה", "פרטים וכמויות"], fill_rgb="333B47")

    S = q(SH_ASSIGN)
    for i in range(ASSIGN_ROWS):
        r = 4 + i
        src = 3 + i
        group = ws.cell(
            row=r, column=1,
            value='=IF({s}$A{n}="","",IF({s}$A{n}={s}$A{p},"",{s}$A{n}))'.format(s=S, n=src, p=src - 1),
        )
        group.font = f(11, bold=True)
        for col, letter in ((2, "B"), (3, "C"), (4, "D")):
            ws.cell(row=r, column=col,
                    value='=IF({s}$A{n}="","",{s}${c}{n}&"")'.format(s=S, c=letter, n=src))
        for col in range(1, 5):
            c = ws.cell(row=r, column=col)
            c.border = box()
            if col != 1:
                c.font = f(10)
            c.alignment = align(v="top", wrap=(col >= 3), h="center" if col == 2 else "right")
        ws.row_dimensions[r].height = 26

    ws.freeze_panes = "A4"
    ws.print_title_rows = "3:3"
    return ws


def main():
    wb = Workbook()
    wb.remove(wb.active)
    build_help(wb)
    build_settings(wb)
    build_schedule(wb)
    build_cards(wb)
    build_plain(wb)
    build_assign(wb)
    build_groups(wb)
    build_tasks(wb)
    build_zmanim(wb)
    wb.active = 0
    wb.save(OUT)
    print("נוצר: {}".format(OUT))


if __name__ == "__main__":
    main()
