# -*- coding: utf-8 -*-
"""הפקת קובץ עבודה לשבת מסוימת.

    python3 tools/new_shabbat.py 2026-09-18
    python3 tools/new_shabbat.py 2026-09-18 --from shabbatot/2026-09-04.xlsx

ברירת המחדל: עותק של shabbat-planner.xlsx. עם --from מתחילים מקובץ של שבת קודמת —
כך עריכות שנעשו במשימות, במתכונים ובקייטרינג עוברות הלאה; רק השמות והקבוצות
מתאפסים. בשני המקרים «לוז» נכתב מחדש לגמרי מ-bw.schedule_rows (גם אירועים שהוספו
ידנית בקובץ הקודם יורדים — מוסיפים אותם ב-data/schedule/<תאריך>.csv), עם שעות
סטטיות (ההצעה בגיליון היא נוסחה, והייצוא לא יכול לקרוא נוסחאות).
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_workbook as bw

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "shabbat-planner.xlsx"
OUTDIR = ROOT / "shabbatot"


def clear(ws, row, col):
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


def reset_schedule(wb, date):
    """הלו"ז של השבת — כל השורות נכתבות מחדש מ-bw.schedule_rows (תבנית לפי סוג השבת + קובץ
    הלו"ז של השבוע), עם שעות סטטיות. הזמנים נלקחים מ-bw.zmanim_for (אתר ישיבה לשבתות שלנו)
    ונכתבים לשורת השבת ב«זמנים», כך שהייצוא והנוסחאות קוראים אותם זמנים."""
    zm, ws = wb[bw.SH_ZMAN], wb[bw.SH_SCHED]
    z, row = bw.zmanim_for(date), find_row(zm, date)
    if z is None or row is None:
        raise SystemExit("התאריך {} אינו מופיע בלוח הזמנים. הריצו קודם tools/zmanim.py ו-build_workbook.py"
                         .format(date.strftime("%d/%m/%Y")))
    candle, havdalah = bw.as_time(z["כניסת שבת"]), bw.as_time(z["צאת שבת"])
    zm.cell(row=row, column=3).value, zm.cell(row=row, column=4).value = candle, havdalah
    if zm.cell(row=2, column=5).value == "מקור":          # בקבצים ישנים E היא עמודת הערה ממוזגת
        zm.cell(row=row, column=5).value = z["מקור"]
    ws[bw.SCHED_DATE] = zm.cell(row=row, column=1).value
    ws[bw.SCHED_TITLE] = bw.read_shabbat(date).get("שם") or None

    rows = bw.schedule_rows(date, candle, havdalah)
    bw.write_schedule(ws, rows)
    times = {(r["יום"], r["אירוע"]): r["שעה"] for r in rows}
    return z["פרשה"], candle, havdalah, times


def reset_people(wb):
    ws = wb[bw.SH_TASKS]
    for r in range(bw.TASK_FIRST_ROW, ws.max_row + 1):
        clear(ws, r, bw.T_NAMES)
    ws = wb[bw.SH_GROUPS]
    for r in range(bw.GROUP_FIRST_ROW, ws.max_row + 1):
        clear(ws, r, bw.G_MEMBERS)
    ws = wb[bw.SH_STUDENTS]
    for r in range(bw.STUDENT_FIRST_ROW, ws.max_row + 1):
        for col in (bw.S_AVAILABLE, bw.S_GROUPS, bw.S_NOTE):
            clear(ws, r, col)
    # «היסטוריה» לא מתאפסת — זה הזיכרון של המערכת


def write_week(wb, date, times=None):
    """המשימות, הקבוצות, התפריט והמתכונים של השבת הזו: הקבועים + מה שהאחראים בחרו לשבוע
    (data/preps, data/menu, data/recipes, data/weeks.csv). מצייני המקום מתמלאים כאן."""
    rows, plan, menu = bw.task_rows(date, times), bw.plan_rows(date), bw.read_week(date)["menu"]
    if len(rows) > bw.TASK_ROWS or len(plan) > bw.GROUP_ROWS or len(menu) > bw.CATERING_ROWS:
        raise SystemExit("יותר מדי שורות לגיליון: {} משימות, {} קבוצות, {} מנות".format(
            len(rows), len(plan), len(menu)))
    ws = wb[bw.SH_TASKS]
    for i in range(bw.TASK_ROWS):
        bw.write_task_row(ws, bw.TASK_FIRST_ROW + i, rows[i] if i < len(rows) else None)
    ws = wb[bw.SH_GROUPS]
    for i in range(bw.GROUP_ROWS):
        bw.write_group_row(ws, bw.GROUP_FIRST_ROW + i, plan[i] if i < len(plan) else None)
    ws = wb[bw.SH_CATERING]
    for i in range(bw.CATERING_ROWS):
        bw.write_menu_row(ws, 3 + i, menu[i] if i < len(menu) else None)
    bw.write_recipes(wb[bw.SH_RECIPES], bw.recipe_rows(date))
    return rows, plan


def main():
    ap = argparse.ArgumentParser(description="הפקת קובץ שבת")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-11")
    ap.add_argument("--from", dest="source", help="להתחיל מקובץ של שבת קודמת במקום מהתבנית")
    ap.add_argument("--out", help="נתיב פלט חלופי")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    if date.weekday() != 4:
        print("שים לב: {} אינו יום שישי — ממשיך בכל זאת.".format(args.date))

    OUTDIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else OUTDIR / "{}.xlsx".format(date.isoformat())
    source = Path(args.source) if args.source else TEMPLATE
    if source.resolve() != out.resolve():
        shutil.copy(source, out)

    wb = load_workbook(out)
    parasha, candle, havdalah, times = reset_schedule(wb, date)
    reset_people(wb)
    if not args.source:                  # --from שומר את המשימות של השבת הקודמת כמו שהן
        rows, plan = write_week(wb, date, times)
        print("  {} משימות · {} קבוצות".format(len(rows), len(plan)))
    wb.save(out)
    shown = out.relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    print("נוצר: {}  ({}, {})".format(shown, date.strftime("%d/%m/%Y"), parasha or "—"))
    print("  כניסת שבת {}  ·  צאת שבת {}".format(
        candle.strftime("%H:%M"), havdalah.strftime("%H:%M")))


if __name__ == "__main__":
    main()
