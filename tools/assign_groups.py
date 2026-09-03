# -*- coding: utf-8 -*-
"""הצעת חלוקה ל-4 קבוצות ושיבוץ תחומי אחריות מתחלפים.

    python3 tools/assign_groups.py 2026-09-04
    python3 tools/assign_groups.py 2026-09-04 --groups 4 --clean שישי=בית מיכאל \\
            --clean "מוצאי שבת=חדר אוכל,שירותי חדר אוכל,מטבח,חדר מקררים"

מה הסקריפט עושה:
  1. מחלק את החניכים מ-data/students.csv לקבוצות שוות בגודלן. חניך עם ערך בעמודת
     «קבוצה קבועה» נשאר תמיד בקבוצה שלו; השאר מתחלקים סביבו.
  2. מסובב את חבילות האחריות בין הקבוצות לפי data/rotation_history.csv — מי שקיבל
     חבילה מסוימת בשבת האחרונה לא יקבל אותה שוב עכשיו.
  3. כותב את ההצעה לגיליונות «חניכים», «קבוצות» ו«שיבוץ» של קובץ השבת.

הכל הצעה בלבד — אפשר לערוך הכל ידנית באקסל אחר כך.
"""
import argparse
import csv
import random
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HISTORY = DATA / "rotation_history.csv"

SH_STUDENTS, SH_GROUPS, SH_ASSIGN, SH_TASKS = "חניכים", "קבוצות", "שיבוץ", "מאגר משימות"

# חבילות האחריות — כל קבוצה מקבלת חבילה אחת, והן מתחלפות משבת לשבת.
# כל חבילה היא רשימת (חלון זמן, תחום אחריות) מתוך «מאגר משימות».
BUNDLES = [
    ("קידוש ומאפים", [("שישי", "מאפים"), ("שבת", "קידוש")]),
    ("ארוחות שבת", [("שישי", "בישול"), ("שישי", "ארוחת ערב שבת"),
                    ("שבת", "ארוחת צהריים שבת")]),
    ("ארוחות שישי וסעודה שלישית", [("שישי", "ארוחת בוקר שישי"),
                                   ("שישי", "ארוחת צהריים שישי"),
                                   ("שבת", "סעודה שלישית")]),
    ("טיש ואחריות טכנית", [("שישי", "טיש"), ("שישי", "חימום"), ("שישי", "הבדלה"),
                           ("שישי", "חשמל"), ("שישי", "עיתון"), ("שישי", "מרחבים"),
                           ("שבת", "חימום"), ("מוצאי שבת", "חשמל")]),
]

WINDOW_ORDER = {"חמישי": 0, "שישי": 1, "שבת": 2, "מוצאי שבת": 3}


def read_students():
    path = DATA / "students.csv"
    if not path.exists():
        raise SystemExit("חסר data/students.csv — הריצו קודם: python3 tools/roster.py")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("שם") or "").strip()]


def read_tasks():
    with (DATA / "task_library.csv").open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def history():
    if not HISTORY.exists():
        return []
    with HISTORY.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def record(date, mapping):
    rows = [r for r in history() if r["תאריך"] != date]
    for group, bundle in mapping.items():
        rows.append({"תאריך": date, "קבוצה": group, "חבילת אחריות": bundle})
    rows.sort(key=lambda r: (r["תאריך"], r["קבוצה"]))
    with HISTORY.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["תאריך", "קבוצה", "חבילת אחריות"])
        writer.writeheader()
        writer.writerows(rows)


def split_groups(students, names, seed):
    """חלוקה שוות-גודל שמכבדת נעילות."""
    groups = {name: [] for name in names}
    free = []
    for s in students:
        locked = (s.get("קבוצה קבועה") or "").strip()
        if locked in groups:
            groups[locked].append(s["שם"])
        else:
            free.append(s["שם"])

    random.Random(seed).shuffle(free)
    for name in free:
        target = min(groups, key=lambda n: (len(groups[n]), names.index(n)))
        groups[target].append(name)
    return groups


def rotate_bundles(names, past):
    """כל קבוצה מקבלת חבילה שלא קיבלה בשבת האחרונה, בסבב קבוע."""
    offset = len({r["תאריך"] for r in past})
    return {name: BUNDLES[(i + offset) % len(BUNDLES)][0] for i, name in enumerate(names)}


def build_assignments(mapping, tasks, cleaning):
    """שורות לגיליון «שיבוץ»: (קבוצה, חלון זמן, שעה, משימה, פרטים)."""
    by_bundle = {title: areas for title, areas in BUNDLES}
    rows = []
    for group, bundle in mapping.items():
        for window, area in by_bundle[bundle]:
            for task in tasks:
                if task["תחום אחריות"] == area and task["חלון זמן"] in (window, "משתנה"):
                    rows.append((group, window, "", task["משימה"], ""))

    names = list(mapping)
    for i, (window, space) in enumerate(cleaning):
        group = names[i % len(names)]
        for task in tasks:
            if task["תחום אחריות"] == space and task["קטגוריה"] == "ניקיון וסידור":
                rows.append((group, window, "", task["משימה"], ""))
                break
        else:
            rows.append((group, window, "", "ניקיון וסידור {}".format(space), ""))

    order = {name: i for i, name in enumerate(mapping)}
    rows.sort(key=lambda row: (order[row[0]], WINDOW_ORDER.get(row[1], 9)))
    return rows


def set_cell(ws, row, col, value):
    """כתיבה לתא, בדילוג על תאים ממוזגים (שורות ההערה בתחתית הגיליונות)."""
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, MergedCell):
        cell.value = value


def write_workbook(path, groups, mapping, rows):
    wb = load_workbook(path)
    ws_students, ws_groups, ws_assign = wb[SH_STUDENTS], wb[SH_GROUPS], wb[SH_ASSIGN]

    lookup = {}
    for group, members in groups.items():
        for name in members:
            lookup[name] = group
    for r in range(3, ws_students.max_row + 1):
        name = ws_students.cell(row=r, column=1).value
        if name:
            set_cell(ws_students, r, 2, lookup.get(name))

    for i, (group, bundle) in enumerate(mapping.items()):
        set_cell(ws_groups, 3 + i, 1, group)
        set_cell(ws_groups, 3 + i, 2, bundle)

    for r in range(3, ws_assign.max_row + 1):
        for col in (1, 2, 3, 4, 6):
            set_cell(ws_assign, r, col, None)
    for i, (group, window, hour, task, detail) in enumerate(rows):
        r = 3 + i
        set_cell(ws_assign, r, 1, group)
        set_cell(ws_assign, r, 2, window)
        if hour:
            set_cell(ws_assign, r, 3, hour)
        set_cell(ws_assign, r, 4, task)
        if detail:
            set_cell(ws_assign, r, 6, detail)

    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description="הצעת חלוקה לקבוצות ושיבוץ אחריות")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-04")
    ap.add_argument("--groups", type=int, default=4, help="מספר הקבוצות (ברירת מחדל 4)")
    ap.add_argument("--names", help="שמות הקבוצות מופרדים בפסיק")
    ap.add_argument("--clean", action="append", default=[],
                    help='מרחבי ניקיון: "מוצאי שבת=חדר אוכל,מטבח" — ניתן לחזור על הדגל')
    ap.add_argument("--seed", type=int, help="זרע אקראיות (לשחזור אותה חלוקה)")
    ap.add_argument("--file", help="נתיב קובץ השבת (ברירת מחדל shabbatot/<תאריך>.xlsx)")
    ap.add_argument("--dry-run", action="store_true", help="הדפסה בלבד, בלי לכתוב לקובץ")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    path = Path(args.file) if args.file else ROOT / "shabbatot" / "{}.xlsx".format(date.isoformat())
    if not args.dry_run and not path.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם: python3 tools/new_shabbat.py {}".format(
            path, args.date))

    names = ([n.strip() for n in args.names.split(",")] if args.names
             else ["קבוצה {}".format(i + 1) for i in range(args.groups)])

    cleaning = []
    for spec in args.clean:
        window, _, spaces = spec.partition("=")
        for space in spaces.split(","):
            if space.strip():
                cleaning.append((window.strip(), space.strip()))

    students = read_students()
    past = history()
    groups = split_groups(students, names, args.seed if args.seed is not None else date.toordinal())
    mapping = rotate_bundles(names, past)
    rows = build_assignments(mapping, read_tasks(), cleaning)

    print("שבת {} · {} חניכים · {} קבוצות".format(
        date.strftime("%d/%m/%Y"), len(students), len(names)))
    for name in names:
        print("\n  {} — {} ({} חניכים)".format(name, mapping[name], len(groups[name])))
        print("    " + ", ".join(groups[name]))
        for row in rows:
            if row[0] == name:
                print("      · [{}] {}".format(row[1], row[3]))

    if args.dry_run:
        print("\n(dry-run — לא נכתב דבר)")
        return

    write_workbook(path, groups, mapping, rows)
    record(date.isoformat(), mapping)
    print("\nנכתב אל {}".format(path))


if __name__ == "__main__":
    main()
