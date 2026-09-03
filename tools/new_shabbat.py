# -*- coding: utf-8 -*-
"""הפקת קובץ עבודה לשבת מסוימת מתוך shabbat-planner.xlsx.

    python3 tools/new_shabbat.py 2026-09-04
    python3 tools/new_shabbat.py 2026-09-04 --clear-groups --clear-assignments

התאריך נבחר מראש בגיליון «הגדרות», כך שהלו"ז, הכרטיסיות והטופס הנקי מוכנים מיד.
הקובץ נשמר תחת shabbatot/<תאריך>.xlsx — תיקייה אחת עם היסטוריית כל השבתות.
"""
import argparse
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "shabbat-planner.xlsx"
OUTDIR = ROOT / "shabbatot"

SETTINGS_INPUTS = ["B8", "B9", "B14", "B15", "B16", "B17",
                   "B22", "B23", "B24", "B27", "B28", "B29"]


def clear(ws, row, col):
    """ניקוי תא, בדילוג על תאים ממוזגים (שורות ההערה בתחתית הגיליונות)."""
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, MergedCell):
        cell.value = None


def find_row(ws, date):
    """שורת השבת בגיליון «זמנים», או None אם התאריך אינו בלוח."""
    for row in ws.iter_rows(min_row=3, max_col=1):
        cell = row[0]
        if cell.value and getattr(cell.value, "date", lambda: cell.value)() == date:
            return cell.row
    return None


def main():
    ap = argparse.ArgumentParser(description="הפקת קובץ שבת")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-04")
    ap.add_argument("--clear-settings", action="store_true", help="ניקוי מרחבים ואנשי צוות")
    ap.add_argument("--clear-groups", action="store_true", help="ניקוי הרכבי הקבוצות")
    ap.add_argument("--clear-assignments", action="store_true",
                    help="ניקוי עמודת הקבוצה בשיבוץ (המשימות והכמויות נשמרות)")
    ap.add_argument("--out", help="נתיב פלט חלופי")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    if date.weekday() != 4:
        print("שים לב: {} אינו יום שישי — ממשיך בכל זאת.".format(args.date))

    OUTDIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else OUTDIR / "{}.xlsx".format(date.isoformat())
    shutil.copy(TEMPLATE, out)

    wb = load_workbook(out)
    zm, st = wb["זמנים"], wb["הגדרות"]

    row = find_row(zm, date)
    if row is None:
        raise SystemExit("התאריך {} אינו מופיע בגיליון «זמנים». הריצו קודם tools/zmanim.py"
                         .format(date.strftime("%d/%m/%Y")))
    st["B4"] = zm.cell(row=row, column=1).value

    if args.clear_settings:
        for ref in SETTINGS_INPUTS:
            st[ref] = None

    if args.clear_groups:
        gr = wb["קבוצות"]
        for r in range(3, gr.max_row + 1):
            for col in (1, 2):            # עמודת החניכים מחושבת — לא נוגעים בה
                clear(gr, r, col)
        st = wb["חניכים"]
        for r in range(3, st.max_row + 1):
            clear(st, r, 2)

    if args.clear_assignments:
        asg = wb["שיבוץ"]
        for r in range(3, asg.max_row + 1):
            for col in (1, 2, 3, 4, 6, 7):   # עמודת הקטגוריה מחושבת
                clear(asg, r, col)

    wb.save(out)
    print("נוצר: {}  ({}, {})".format(
        out, date.strftime("%d/%m/%Y"), zm.cell(row=row, column=2).value or "—"))
    print("  כניסת שבת {}  ·  צאת שבת {}".format(
        zm.cell(row=row, column=3).value, zm.cell(row=row, column=4).value))


if __name__ == "__main__":
    main()
