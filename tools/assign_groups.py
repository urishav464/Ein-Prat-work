# -*- coding: utf-8 -*-
"""שיבוץ החניכים לקבוצות לפי מבנה הקבוצות הקבוע.

    python3 tools/assign_groups.py 2026-09-04
    python3 tools/assign_groups.py 2026-09-04 --dry-run

המבנה מוגדר ב-data/group_plan.csv (קבוצה, קבוצת אם, גודל, מוביל/ה, חברים קבועים,
ערכת צבע, תחומי אחריות) — לשנות מבנה בשבוע הבא זו עריכת שורה שם, בלי נגיעה בקוד.

מי זמין לתורנות נקבע ב-data/attendance/<תאריך>.csv. כשיש יותר זמינים ממקומות,
הסקריפט מעדיף את מי שהיה תורן הכי מעט לאחרונה (data/duty_history.csv), וחניכי
תוכנית אלול מתפזרים יחסית בין הקבוצות ולא מצטברים באחת.
"""
import argparse
import csv
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attendance as attendance_mod
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PLAN = DATA / "group_plan.csv"
DUTY = DATA / "duty_history.csv"

SH_STUDENTS, SH_GROUPS, SH_ASSIGN, SH_TASKS = "חניכים", "קבוצות", "שיבוץ", "מאגר משימות"
WINDOW_ORDER = {"חמישי": 0, "שישי": 1, "שבת": 2, "מוצאי שבת": 3}
WINDOW_ANCHOR = {"חמישי": "חמישי — הכנות", "שישי": "שישי — הכנות ועבודה",
                 "שבת": "קידוש", "מוצאי שבת": "ניקיונות וארגון הקמפוס"}


# ---------------------------------------------------------------------------
def read_plan():
    with PLAN.open(encoding="utf-8-sig", newline="") as fh:
        plan = []
        for row in csv.DictReader(fh):
            if not (row.get("קבוצה") or "").strip():
                continue
            plan.append({
                "name": row["קבוצה"].strip(),
                "parent": (row.get("קבוצת אם") or "").strip(),
                "size": int(row["גודל"]),
                "leader": (row.get("מוביל/ה") or "").strip(),
                "fixed": [x.strip() for x in (row.get("חברים קבועים") or "").split(";") if x.strip()],
                "theme": (row.get("ערכת צבע") or "ים").strip(),
                "areas": [x.strip() for x in (row.get("תחומי אחריות") or "").split(";") if x.strip()],
            })
    return plan


def read_tasks():
    with (DATA / "task_library.csv").open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def duty_counts():
    if not DUTY.exists():
        return Counter()
    with DUTY.open(encoding="utf-8-sig", newline="") as fh:
        return Counter(r["שם"] for r in csv.DictReader(fh))


def record_duty(date, assignment):
    rows = []
    if DUTY.exists():
        with DUTY.open(encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["תאריך"] != date]
    for group, members in assignment.items():
        rows += [{"תאריך": date, "שם": name, "קבוצה": group} for name in members]
    rows.sort(key=lambda r: (r["תאריך"], r["קבוצה"], r["שם"]))
    with DUTY.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["תאריך", "שם", "קבוצה"])
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
def assign(plan, available, programs, past, seed):
    """משבץ חניכים לקבוצות העלה לפי התוכנית.

    סדר הקדימויות: מובילים וחברים קבועים ← חניכי אלול (מפוזרים יחסית) ←
    השאר, כשמי שהיה תורן פחות פעמים נבחר קודם.
    """
    rng = random.Random(seed)
    groups = {g["name"]: [] for g in plan}
    taken = set()

    for g in plan:
        for name in ([g["leader"]] if g["leader"] else []) + g["fixed"]:
            match, _ = roster.match_name(name, available)
            if match and match not in taken:
                groups[g["name"]].append(match)
                taken.add(match)

    def pool(program):
        people = [n for n in available if n not in taken and programs.get(n) == program]
        rng.shuffle(people)
        return sorted(people, key=lambda n: past.get(n, 0))

    open_slots = lambda g: g["size"] - len(groups[g["name"]])

    # אלול: כל חניך נכנס לקבוצה עם היחס הנמוך ביותר של אלול-לגודל, כך שהם
    # מתפזרים על פני כל הקבוצות ולא מצטברים בגדולות (חלוקה יחסית פר-חניך).
    elul = pool("אלול")
    placed = {g["name"]: 0 for g in plan}
    while elul:
        candidates = [g for g in plan if open_slots(g) > 0]
        if not candidates:
            break
        target = min(candidates,
                     key=lambda g: ((placed[g["name"]] + 1) / g["size"], -g["size"]))
        name = elul.pop(0)
        groups[target["name"]].append(name)
        placed[target["name"]] += 1
        taken.add(name)

    rest = pool("מדרשה") + elul
    rest.sort(key=lambda n: past.get(n, 0))
    for g in plan:
        while open_slots(g) > 0 and rest:
            name = rest.pop(0)
            groups[g["name"]].append(name)
            taken.add(name)
    return groups


def build_assignments(plan, tasks):
    """שורות לגיליון «שיבוץ» לפי תחומי האחריות של כל קבוצת עלה."""
    rows = []
    for g in plan:
        for spec in g["areas"]:
            window, _, area = spec.partition(":")
            window, area = window.strip(), area.strip()
            for task in tasks:
                if task["תחום אחריות"] != area:
                    continue
                if task["חלון זמן"] not in (window, "משתנה"):
                    continue
                anchor = (task.get("עוגן") or "").strip() or WINDOW_ANCHOR.get(window, "")
                rows.append((g["name"], window, "", task["משימה"], "", anchor))
    order = {g["name"]: i for i, g in enumerate(plan)}
    rows.sort(key=lambda r: (order[r[0]], WINDOW_ORDER.get(r[1], 9)))
    return rows


# ---------------------------------------------------------------------------
def set_cell(ws, row, col, value):
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, MergedCell):
        cell.value = value


def write_workbook(path, plan, groups, rows):
    wb = load_workbook(path)
    ws_students, ws_groups, ws_assign = wb[SH_STUDENTS], wb[SH_GROUPS], wb[SH_ASSIGN]

    lookup = {name: group for group, members in groups.items() for name in members}
    for r in range(3, ws_students.max_row + 1):
        name = ws_students.cell(row=r, column=1).value
        if name:
            set_cell(ws_students, r, 2, lookup.get(name))

    for i, g in enumerate(plan):
        r = 3 + i
        set_cell(ws_groups, r, 1, g["name"])
        set_cell(ws_groups, r, 2, g["leader"] or None)
        set_cell(ws_groups, r, 3, g["parent"] or None)
        set_cell(ws_groups, r, 5, g["theme"])
    for r in range(3 + len(plan), ws_groups.max_row + 1):
        for col in (1, 2, 3, 5):
            set_cell(ws_groups, r, col, None)

    for r in range(3, ws_assign.max_row + 1):
        for col in (1, 2, 3, 4, 6, 7):
            set_cell(ws_assign, r, col, None)
    for i, (group, window, hour, task, detail, anchor) in enumerate(rows):
        r = 3 + i
        set_cell(ws_assign, r, 1, group)
        set_cell(ws_assign, r, 2, window)
        if hour:
            set_cell(ws_assign, r, 3, hour)
        set_cell(ws_assign, r, 4, task)
        if detail:
            set_cell(ws_assign, r, 6, detail)
        if anchor:
            set_cell(ws_assign, r, 7, anchor)

    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description="שיבוץ לקבוצות לפי המבנה הקבוע")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-04")
    ap.add_argument("--seed", type=int, help="זרע אקראיות (לשחזור אותה חלוקה)")
    ap.add_argument("--file", help="נתיב קובץ השבת")
    ap.add_argument("--dry-run", action="store_true", help="הדפסה בלבד")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    path = Path(args.file) if args.file else ROOT / "shabbatot" / "{}.xlsx".format(date.isoformat())
    if not args.dry_run and not path.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם tools/new_shabbat.py".format(path))

    students = roster.read_students()
    programs = {s["שם"]: s.get("תוכנית", "") for s in students}
    available = attendance_mod.load_available(date)
    if available is None:
        raise SystemExit("אין רשימת נוכחות ל-{} — הריצו קודם tools/attendance.py".format(args.date))

    plan = read_plan()
    groups = assign(plan, available, programs, duty_counts(),
                    args.seed if args.seed is not None else date.toordinal())
    rows = build_assignments(plan, read_tasks())

    placed = sum(len(v) for v in groups.values())
    print("שבת {} · {} זמינים · {} תורנים · {} קבוצות".format(
        date.strftime("%d/%m/%Y"), len(available), placed, len(plan)))

    parents = {}
    for g in plan:
        parents.setdefault(g["parent"] or g["name"], []).append(g)
    for parent, leaves in parents.items():
        total = sum(len(groups[g["name"]]) for g in leaves)
        elul = sum(1 for g in leaves for n in groups[g["name"]] if programs.get(n) == "אלול")
        print("\n■ {} ({} חניכים, מהם {} אלול)".format(parent, total, elul))
        for g in leaves:
            label = g["name"].split(" · ")[-1] if " · " in g["name"] else g["name"]
            print("   {} ({}): {}".format(label, len(groups[g["name"]]),
                                          ", ".join(groups[g["name"]])))

    idle = [n for n in available if n not in {m for v in groups.values() for m in v}]
    print("\nלא תורנים השבת ({}): {}".format(len(idle), ", ".join(idle)))

    if args.dry_run:
        print("\n(dry-run — לא נכתב דבר)")
        return
    write_workbook(path, plan, groups, rows)
    record_duty(date.isoformat(), groups)
    print("\nנכתב אל {}".format(path))


if __name__ == "__main__":
    main()
