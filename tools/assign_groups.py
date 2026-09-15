# -*- coding: utf-8 -*-
"""שיבוץ חניכים למשימות — שלב אחרי שלב, ברמת המשימה.

    python3 tools/assign_groups.py 2026-09-18
    python3 tools/assign_groups.py 2026-09-18 --dry-run
    python3 tools/assign_groups.py 2026-09-18 --max-stages 1

המשימות נקראות מגיליון «משימות» שבקובץ השבת (שלב, יום, שעה, קבוצה, אנשים, ניקוד).
גודל כל קבוצה נגזר מהן: המספר הגדול ביותר של אנשים שנדרשים בו-זמנית (שיא). אותו
אדם עושה כמה משימות בשעות שונות, ואף אחד לא מופיע בשתי משימות באותה שעה. משימה
בלי שעה = כל הקבוצה.

השיבוץ רץ שלב אחרי שלב (הכנות שישי ← תורנות שישי ← תורנות שבת): בכל שלב חניך
יכול להיות בקבוצה אחת, אבל הוא יכול להופיע בכמה שלבים (עד --max-stages) כל עוד
השעות לא מתנגשות. מי שצבר פחות ניקוד — בהיסטוריה ובשבת הזו — נבחר קודם; חניכי
אלול מתפזרים יחסית.

הצמדות ידניות ב-data/attendance/<תאריך>.csv («שיבוץ ידני», כמה קבוצות מופרדות
ב-;) נשמרות גם אם הקבוצה גדולה מהשיא. המבנה הקבוע ב-data/group_plan.csv.
"""
import argparse
import csv
import random
import sys
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attendance as attendance_mod
import build_workbook as bw
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PLAN = DATA / "group_plan.csv"
DUTY = DATA / "duty_history.csv"
DAY_ORDER = {"שישי": 0, "שבת": 1, "מוצאי שבת": 2}


# ---------------------------------------------------------------------------
def read_plan():
    with PLAN.open(encoding="utf-8-sig", newline="") as fh:
        plan = []
        for row in csv.DictReader(fh):
            if not (row.get("קבוצה") or "").strip():
                continue
            plan.append({
                "name": row["קבוצה"].strip(),
                "stage": (row.get("שלב") or "").strip() or bw.STAGES[-1],
                "leader": (row.get("מוביל/ה") or "").strip(),
                "fixed": [x.strip() for x in (row.get("חברים קבועים") or "").split(";") if x.strip()],
                "size": 0,
            })
    return plan


def history_points():
    """ניקוד מצטבר לכל חניך מכל השבתות הקודמות."""
    points = Counter()
    for r in bw.read_history():
        points[r["שם"]] += int(r.get("ניקוד") or 1)
    return points


def record_duty(date, records):
    rows = [r for r in bw.read_history() if r["תאריך"] != date] + records
    rows.sort(key=lambda r: (r["תאריך"], r.get("שלב") or "", r.get("קבוצה") or "", r["שם"]))
    with DUTY.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=bw.HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


# ---------------------------------------------------------------------------
def _clean(value):
    return value.strip() if isinstance(value, str) else value


def read_tasks(path):
    """שורות גיליון «משימות» שיש בהן משימה."""
    ws = load_workbook(path)[bw.SH_TASKS]
    tasks = []
    for r in range(bw.TASK_FIRST_ROW, ws.max_row + 1):
        task = _clean(ws.cell(row=r, column=bw.T_TASK).value)
        if not task:
            continue
        hour = ws.cell(row=r, column=bw.T_HOUR).value
        if isinstance(hour, datetime):
            hour = hour.time()
        people = ws.cell(row=r, column=bw.T_PEOPLE).value
        points = ws.cell(row=r, column=bw.T_POINTS).value
        tasks.append({
            "row": r, "stage": _clean(ws.cell(row=r, column=bw.T_STAGE).value) or "",
            "day": _clean(ws.cell(row=r, column=bw.T_DAY).value) or "",
            "hour": hour or None, "group": _clean(ws.cell(row=r, column=bw.T_GROUP).value) or "",
            "task": task, "people": int(people) if people not in (None, "") else None,
            "points": int(points) if points not in (None, "") else 1,
        })
    return tasks


def timed_slots(tasks, group):
    """המשבצות (יום, שעה) שהקבוצה תופסת בפועל — משימה בלי שעה אינה תופסת זמן."""
    return {key for key, _ in slots_of(tasks, group) if key[0] != "*"}


def slots_of(tasks, group):
    """קבוצות של משימות שרצות בו-זמנית: (מפתח, [משימות]) לפי סדר הזמן."""
    slots = OrderedDict()
    mine = sorted((t for t in tasks if t["group"] == group),
                  key=lambda t: (DAY_ORDER.get(t["day"], 9), t["hour"] is None,
                                 t["hour"] or datetime.min.time(), t["row"]))
    for t in mine:
        key = (t["day"], t["hour"]) if t["hour"] else ("*", t["row"])
        slots.setdefault(key, []).append(t)
    return list(slots.items())


def peak(tasks, group):
    """כמה אנשים הקבוצה צריכה: השיא של אנשים בו-זמנית."""
    return max((sum(t["people"] or 0 for t in ts) for _, ts in slots_of(tasks, group)), default=0)


def shrink_to_fit(plan, tasks, budget, fixed_sizes):
    """כשאין מספיק זמינים — מורידים אחד מהמשימות הגדולות ביותר עד שזה נכנס."""
    changed = []
    while True:
        need = sum(max(peak(tasks, g["name"]), fixed_sizes.get(g["name"], 0)) for g in plan)
        if need <= budget:
            return changed
        candidates = []
        for g in plan:
            if fixed_sizes.get(g["name"], 0) >= peak(tasks, g["name"]):
                continue
            for _, ts in slots_of(tasks, g["name"]):
                if sum(t["people"] or 0 for t in ts) == peak(tasks, g["name"]):
                    candidates += [t for t in ts if (t["people"] or 0) > 1]
        if not candidates:
            return changed
        t = max(candidates, key=lambda t: (t["people"], -t["row"]))
        t.setdefault("orig", t["people"])
        t["people"] -= 1
        if t not in changed:
            changed.append(t)


# ---------------------------------------------------------------------------
def assign(plan, available, programs, score, seed, pins=None):
    """משבץ חניכים לקבוצות של שלב אחד לפי גודל (g["size"]).

    סדר הקדימויות: הצמדות ידניות ← מובילים וחברים קבועים ← כל השאר לפי ניקוד
    (מי שצבר פחות נבחר קודם), כשחניכי אלול מתפזרים בין הקבוצות.
    """
    rng = random.Random(seed)
    groups = {g["name"]: [] for g in plan}
    taken = set()

    for name, targets in (pins or {}).items():
        for group in targets:
            if group in groups and name in available and name not in taken:
                groups[group].append(name)
                taken.add(name)

    for g in plan:
        for name in ([g["leader"]] if g["leader"] else []) + g["fixed"]:
            match, _ = roster.match_name(name, available)
            if match and match not in taken:
                groups[g["name"]].append(match)
                taken.add(match)

    open_slots = lambda g: g["size"] - len(groups[g["name"]])

    # כולם מדורגים לפי ניקוד (מי שצבר פחות — קודם); חניך אלול נכנס לקבוצה עם היחס
    # הנמוך ביותר של אלול-לגודל, כדי שאלול יתפזרו בין הקבוצות ולא יצטברו באחת.
    ranked = [n for n in available if n not in taken]
    rng.shuffle(ranked)
    ranked.sort(key=lambda n: score.get(n, 0))
    elul_in = {g["name"]: sum(programs.get(m) == "אלול" for m in groups[g["name"]]) for g in plan}
    for name in ranked:
        candidates = [g for g in plan if open_slots(g) > 0]
        if not candidates:
            break
        if programs.get(name) == "אלול":
            target = min(candidates, key=lambda g: ((elul_in[g["name"]] + 1) / g["size"], -g["size"]))
            elul_in[target["name"]] += 1
        else:
            target = candidates[0]
        groups[target["name"]].append(name)
        taken.add(name)

    for g in plan:                                     # המוביל/ה ראשון/ה ברשימה
        match, _ = roster.match_name(g["leader"], groups[g["name"]]) if g["leader"] else (None, None)
        if match:
            groups[g["name"]].remove(match)
            groups[g["name"]].insert(0, match)
    return groups


def fill_tasks(members, tasks, group):
    """מצמיד שמות לכל משימה של הקבוצה: סבב לפי סדר השעות, בלי כפילות באותה שעה."""
    names = {}
    if not members:
        return names
    pointer = 0
    for key, ts in slots_of(tasks, group):
        for t in ts:
            if t["people"] is None:
                names[t["row"]] = list(members)
                continue
            chosen = []
            for _ in range(min(t["people"], len(members))):
                chosen.append(members[pointer % len(members)])
                pointer += 1
            names[t["row"]] = chosen
    return names


def assign_all(plan, tasks, available, programs, past, pins, seed, max_stages):
    """מריץ את השיבוץ שלב אחרי שלב ומחזיר (קבוצות, שמות למשימה, הקטנות)."""
    groups, task_names, shrunk = {}, {}, []
    week_points, stages_of, busy = Counter(), Counter(), {}
    stages = [s for s in bw.STAGES if any(g["stage"] == s for g in plan)]
    stages += [g["stage"] for g in plan if g["stage"] not in stages]      # שלב לא מוכר — בסוף
    for i, stage in enumerate(OrderedDict.fromkeys(stages)):
        stage_plan = [g for g in plan if g["stage"] == stage]
        stage_names = {g["name"] for g in stage_plan}
        stage_pins = {n: [g for g in gs if g in stage_names] for n, gs in pins.items()}
        stage_pins = {n: gs for n, gs in stage_pins.items() if gs}
        # חניך פנוי לשלב רק אם אף משימה שכבר שובץ אליה אינה מתנגשת בזמן עם
        # משימות השלב — כך בית מדרש ב-8:00 והכנות ב-8:00 לא נופלים על אותו אדם.
        stage_slots = set().union(*(timed_slots(tasks, g["name"]) for g in stage_plan)) \
            if stage_plan else set()
        pool = [n for n in available
                if (stages_of[n] < max_stages or n in stage_pins)
                and not (busy.get(n, set()) & stage_slots)]

        fixed = Counter(g for gs in stage_pins.values() for g in gs)
        for g in stage_plan:
            for name in ([g["leader"]] if g["leader"] else []) + g["fixed"]:
                match, _ = roster.match_name(name, pool)
                if match and match not in stage_pins:
                    fixed[g["name"]] += 1
        shrunk += shrink_to_fit(stage_plan, tasks, len(pool), fixed)
        for g in stage_plan:
            g["size"] = max(peak(tasks, g["name"]), fixed.get(g["name"], 0))

        score = {n: past.get(n, 0) + week_points[n] for n in pool}
        result = assign(stage_plan, pool, programs, score, seed + i, pins=stage_pins)
        groups.update(result)
        for g in stage_plan:
            names = fill_tasks(result[g["name"]], tasks, g["name"])
            task_names.update(names)
            for t in tasks:
                for n in names.get(t["row"], []):
                    week_points[n] += t["points"]
            occupied = timed_slots(tasks, g["name"])
            for n in result[g["name"]]:
                stages_of[n] += 1
                busy.setdefault(n, set()).update(occupied)
    return groups, task_names, shrunk


# ---------------------------------------------------------------------------
def set_cell(ws, row, col, value):
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, MergedCell):
        cell.value = value


def write_workbook(path, plan, groups, task_names, present, available, history):
    wb = load_workbook(path)

    ws = wb[bw.SH_TASKS]
    for r in range(bw.TASK_FIRST_ROW, ws.max_row + 1):
        set_cell(ws, r, bw.T_NAMES, ", ".join(task_names[r]) if r in task_names else None)

    ws = wb[bw.SH_GROUPS]
    for i, g in enumerate(plan):
        r = bw.GROUP_FIRST_ROW + i
        set_cell(ws, r, bw.G_NAME, g["name"])
        set_cell(ws, r, bw.G_STAGE, g["stage"] or None)
        set_cell(ws, r, bw.G_LEADER, g["leader"] or None)
        set_cell(ws, r, bw.G_MEMBERS, ", ".join(groups[g["name"]]) or None)
    for r in range(bw.GROUP_FIRST_ROW + len(plan), ws.max_row + 1):
        for col in (bw.G_NAME, bw.G_STAGE, bw.G_LEADER, bw.G_MEMBERS):
            set_cell(ws, r, col, None)

    ws = wb[bw.SH_STUDENTS]
    lookup = {}
    for g in plan:                                   # לפי סדר השלבים
        for name in groups[g["name"]]:
            lookup.setdefault(name, []).append(g["name"])
    for r in range(bw.STUDENT_FIRST_ROW, ws.max_row + 1):
        name = ws.cell(row=r, column=bw.S_NAME).value
        if not name:
            continue
        if name not in present:
            set_cell(ws, r, bw.S_AVAILABLE, None)
            set_cell(ws, r, bw.S_NOTE, "לא נוכח/ת")
        else:
            set_cell(ws, r, bw.S_AVAILABLE, "כן" if name in available else "לא")
            set_cell(ws, r, bw.S_NOTE, None)
        set_cell(ws, r, bw.S_GROUPS, "; ".join(lookup[name]) if name in lookup else None)

    ws = wb[bw.SH_HISTORY]
    for r in range(bw.HISTORY_FIRST_ROW, ws.max_row + 1):
        for col in range(1, 7):
            set_cell(ws, r, col, None)
    for i, row in enumerate(history):
        bw.write_history_row(ws, bw.HISTORY_FIRST_ROW + i, row)
    wb.save(path)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="שיבוץ חניכים למשימות")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-18")
    ap.add_argument("--seed", type=int, help="זרע אקראיות (לשחזור אותה חלוקה)")
    ap.add_argument("--file", help="נתיב קובץ השבת")
    ap.add_argument("--max-stages", type=int, default=2, help="בכמה שלבים חניך יכול להיות (ברירת מחדל 2)")
    ap.add_argument("--dry-run", action="store_true", help="הדפסה בלבד")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    path = Path(args.file) if args.file else ROOT / "shabbatot" / "{}.xlsx".format(date.isoformat())
    if not path.exists():
        raise SystemExit("לא נמצא {} — הריצו קודם tools/new_shabbat.py".format(path))

    students = roster.read_students()
    programs = {s["שם"]: s.get("תוכנית", "") for s in students}
    present = attendance_mod.load(date)
    available = attendance_mod.load_available(date)
    if available is None:
        raise SystemExit("אין רשימת נוכחות ל-{} — הריצו קודם tools/attendance.py".format(args.date))
    pins = {n: [g.strip() for g in v.split(";") if g.strip()] for n, v in attendance_mod.load_pins(date).items()}

    plan = read_plan()
    tasks = read_tasks(path)
    known = {g["name"] for g in plan}
    for t in tasks:
        if t["group"] and t["group"] not in known:
            print("⚠ משימה «{}» משויכת לקבוצה לא מוכרת: {}".format(t["task"], t["group"]))

    past = {n: p for n, p in history_points().items()}
    for r in bw.read_history():                       # השבת הזו לא נספרת נגד עצמה
        if r["תאריך"] == date.isoformat():
            past[r["שם"]] -= int(r.get("ניקוד") or 1)

    groups, task_names, shrunk = assign_all(
        plan, tasks, available, programs, past, pins,
        args.seed if args.seed is not None else date.toordinal(), args.max_stages)

    on_duty = {m for v in groups.values() for m in v}
    print("שבת {} · {} נוכחים · {} זמינים · {} תורנים · {} קבוצות".format(
        date.strftime("%d/%m/%Y"), len(present), len(available), len(on_duty), len(plan)))
    if shrunk:
        print("⚠ לא מספיק זמינים — הוקטנו: " + "; ".join(
            "{} [{}] {}→{}".format(t["task"][:30], t["group"], t["orig"], t["people"]) for t in shrunk))

    for stage in OrderedDict.fromkeys(g["stage"] for g in plan):
        leaves = [g for g in plan if g["stage"] == stage]
        print("\n■ {} ({} חניכים)".format(stage, sum(len(groups[g["name"]]) for g in leaves)))
        for g in leaves:
            print("   {} ({}, שיא {}): {}".format(g["name"], len(groups[g["name"]]), peak(tasks, g["name"]),
                                                 ", ".join(groups[g["name"]])))
            for _, ts in slots_of(tasks, g["name"]):
                for t in ts:
                    hour = t["hour"].strftime("%H:%M") if t["hour"] else "  —  "
                    print("      {} {} — {}".format(hour, t["task"][:44], ", ".join(task_names.get(t["row"], []))))

    multi = [n for n in on_duty if sum(n in v for v in groups.values()) > 1]
    if multi:
        print("\nבשני שלבים ({}): {}".format(len(multi), ", ".join(multi)))
    loose = [t for t in tasks if not t["group"]]
    if loose:
        print("\nמשימות בלי קבוצה ({}): {}".format(len(loose), "; ".join(t["task"] for t in loose)))
    idle = [n for n in available if n not in on_duty]
    print("\nלא תורנים השבת ({}): {}".format(len(idle), ", ".join(idle)))

    if args.dry_run:
        print("\n(dry-run — לא נכתב דבר)")
        return
    by_row = {t["row"]: t for t in tasks}
    records = [{"תאריך": date.isoformat(), "שם": n, "שלב": by_row[r]["stage"], "קבוצה": by_row[r]["group"],
                "משימה": by_row[r]["task"], "ניקוד": by_row[r]["points"]}
               for r, names in task_names.items() for n in names]
    history = record_duty(date.isoformat(), records)
    write_workbook(path, plan, groups, task_names, set(present), set(available), history)
    print("\nנכתב אל {}".format(path.relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path))


if __name__ == "__main__":
    main()
