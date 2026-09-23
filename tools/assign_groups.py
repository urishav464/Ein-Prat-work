# -*- coding: utf-8 -*-
"""שיבוץ חניכים למשימות — שלב אחרי שלב, ברמת המשימה.

    python3 tools/assign_groups.py 2026-09-18
    python3 tools/assign_groups.py 2026-09-18 --dry-run
    python3 tools/assign_groups.py 2026-09-18 --max-stages 1

המשימות נקראות מגיליון «משימות» שבקובץ השבת (שלב, יום, שעה, קבוצה, אנשים, ניקוד).
גודל כל קבוצה נגזר מהן: המספר הגדול ביותר של אנשים שנדרשים בו-זמנית (שיא). אותו
אדם עושה כמה משימות בשעות שונות, ואף אחד לא מופיע בשתי משימות באותה שעה. משימה
בלי שעה = כל הקבוצה.

השיבוץ רץ שלב אחרי שלב (הכנות שישי ← תורנות שישי ← תורנות שבת ← תורנות מוצ"ש): בכל שלב חניך
יכול להיות בקבוצה אחת, אבל הוא יכול להופיע בכמה שלבים (עד --max-stages) כל עוד
השעות לא מתנגשות. מי שצבר פחות ניקוד — בהיסטוריה ובשבת הזו — נבחר קודם; חניכי
אלול מתפזרים יחסית.

הצמדות ידניות ב-data/attendance/<תאריך>.csv («שיבוץ ידני», כמה קבוצות מופרדות
ב-;) נשמרות גם אם הקבוצה גדולה מהשיא. המבנה הקבוע ב-data/group_plan.csv, וההכנות של השבוע ב-data/preps/<תאריך>.csv.
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
DUTY = DATA / "duty_history.csv"
DAY_ORDER = bw.DAY_ORDER


# ---------------------------------------------------------------------------
def read_plan(date=None):
    """הקבוצות לשבת: ההכנות שהאחראים בחרו לשבוע הזה + הקבוצות הקבועות (bw.plan_rows)."""
    plan = []
    for row in bw.plan_rows(date):
        if not (row.get("קבוצה") or "").strip():
            continue
        plan.append({
            "name": row["קבוצה"].strip(),
            "stage": (row.get("שלב") or "").strip() or bw.STAGES[-1],
            "points": int(row.get("ניקוד") or 1),
            "needs_staff": (row.get("אחראי מצוות") or "").strip() == "כן",
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
        tasks.append({
            "row": r, "stage": _clean(ws.cell(row=r, column=bw.T_STAGE).value) or "",
            "day": _clean(ws.cell(row=r, column=bw.T_DAY).value) or "",
            "hour": hour or None, "group": _clean(ws.cell(row=r, column=bw.T_GROUP).value) or "",
            "task": task, "people": int(people) if people not in (None, "") else None,
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
def assign(plan, available, programs, score, seed, pins=None, group_blocks=None):
    """משבץ חניכים לקבוצות של שלב אחד לפי גודל (g["size"]).

    סדר הקדימויות: הצמדות ידניות ← מובילים וחברים קבועים ← כל השאר לפי ניקוד
    (מי שצבר פחות נבחר קודם), כשחניכי אלול מתפזרים בין הקבוצות. group_blocks = {שם: {קבוצה}}
    — קבוצות שחניך לא נכנס אליהן בדירוג (הצמדה ידנית גוברת).
    """
    group_blocks = group_blocks or {}
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
        if not any(open_slots(g) > 0 for g in plan):
            break
        candidates = [g for g in plan if open_slots(g) > 0 and g["name"] not in group_blocks.get(name, ())]
        if not candidates:
            continue
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


def pick_staff(slots, staff, used, score, busy, pool):
    """איש צוות השבת שיהיה אחראי על הקבוצה — הפנוי עם הניקוד הנמוך ביותר."""
    free = [n for n in staff
            if n not in used and n in pool and not (busy.get(n, set()) & slots)]
    return min(free, key=lambda n: (score.get(n, 0), n)) if free else None


def assign_all(plan, tasks, available, programs, past, pins, seed, max_stages,
               staff=(), blocked=None, leaders=None, group_blocks=None):
    """מריץ את השיבוץ שלב אחרי שלב ומחזיר (קבוצות, שמות למשימה, הקטנות)."""
    blocked = blocked or {}
    leaders = leaders or {}
    group_blocks = group_blocks or {}
    groups, task_names, shrunk = {}, {}, []
    week_points, stages_of, busy = Counter(), Counter(), {}
    stages = [s for s in bw.STAGES if any(g["stage"] == s for g in plan)]
    stages += [g["stage"] for g in plan if g["stage"] not in stages]      # שלב לא מוכר — בסוף
    points_of = {g["name"]: g["points"] for g in plan}
    promised = {n: list(gs) for n, gs in pins.items()}          # הצמדות + אחראים = התחייבויות
    for group, name in leaders.items():
        promised.setdefault(name, []).append(group)
    done = set()
    for i, stage in enumerate(OrderedDict.fromkeys(stages)):
        stage_plan = [g for g in plan if g["stage"] == stage]
        stage_names = {g["name"] for g in stage_plan}
        stage_pins = {n: [g for g in gs if g in stage_names] for n, gs in pins.items()}
        stage_pins = {n: gs for n, gs in stage_pins.items() if gs}
        # התחייבות לשלב מאוחר יותר: השעות שלה שמורות כבר עכשיו, והניקוד שלה נספר
        # בדירוג — כך מי שהוצמד לבית מדרש לא נלקח קודם להכנה ב-8:00, ומי שמחכה
        # לו תורנות שבת לא נבחר לשישי לפני מי שאין לו כלום.
        reserved, committed = {}, Counter()
        for n, gs in promised.items():
            for g in gs:
                if g in points_of and g not in stage_names and g not in done:
                    reserved.setdefault(n, set()).update(timed_slots(tasks, g))
                    committed[n] += points_of[g]
        # חניך פנוי לשלב רק אם אף משימה שכבר שובץ אליה אינה מתנגשת בזמן עם
        # משימות השלב — כך בית מדרש ב-8:00 והכנות ב-8:00 לא נופלים על אותו אדם.
        stage_slots = set().union(*(timed_slots(tasks, g["name"]) for g in stage_plan)) \
            if stage_plan else set()
        pool = [n for n in available
                if (stages_of[n] < max_stages or n in stage_pins)
                and stage not in blocked.get(n, ())
                and not (busy.get(n, set()) & stage_slots)
                and (n in stage_pins or not (reserved.get(n, set()) & stage_slots))]

        # אחראי מצוות השבת לכל קבוצה שדורשת אחד — נספר בתוך גודל הקבוצה.
        # הצוות מתאפס בכל שלב: אותו אדם יכול להיות אחראי בשישי וגם בשבת, אבל
        # לא על שתי קבוצות באותו שלב.
        score_now = {n: past.get(n, 0) + week_points[n] + committed[n] for n in staff}
        used_here = set()
        for g in stage_plan:                      # אחראי/ת שנקבע/ה לשבת הזו — קודם לכל
            match, _ = roster.match_name(leaders.get(g["name"], ""), pool) \
                if g["name"] in leaders else (None, None)
            if match:
                g["leader"] = match
                if match in staff:
                    used_here.add(match)
            elif g["name"] in leaders:
                print("⚠ האחראי/ת «{}» ל«{}» לא זמין/ה בשלב".format(leaders[g["name"]], g["name"]))
        eligible = lambda g: [n for n in staff if g["name"] not in group_blocks.get(n, ())]
        # הקבוצה עם הכי מעט אנשי צוות אפשריים בוחרת ראשונה — כך מעביר/ת חבורה מהצוות לא «תופס/ת»
        # את הארוחה ומשאיר/ה את ארוחת הצהריים בלי אחראי (בלי חסימות — הסדר נשאר כמו שהיה)
        for g in sorted(stage_plan, key=lambda g: len(eligible(g))):
            if not g["needs_staff"] or g["leader"]:
                continue
            chosen = pick_staff(timed_slots(tasks, g["name"]), eligible(g),  # לא מי שהקבוצה חסומה לו/ה
                                used_here, score_now, busy, pool)
            if chosen:
                g["leader"] = chosen
                used_here.add(chosen)
            else:
                print("⚠ אין איש צוות פנוי ל«{}»".format(g["name"]))
        # אנשי הצוות משמשים כאחראים או כחברים שהוצמדו ידנית — לא ממלאים מקומות רגילים
        pool = [n for n in pool if n not in staff or n in used_here or n in stage_pins]

        fixed = Counter(g for gs in stage_pins.values() for g in gs)
        for g in stage_plan:
            for name in ([g["leader"]] if g["leader"] else []) + g["fixed"]:
                match, _ = roster.match_name(name, pool)
                if match and match not in stage_pins:
                    fixed[g["name"]] += 1
        shrunk += shrink_to_fit(stage_plan, tasks, len(pool), fixed)
        for g in stage_plan:
            g["size"] = max(peak(tasks, g["name"]), fixed.get(g["name"], 0))

        score = {n: past.get(n, 0) + week_points[n] + committed[n] for n in pool}
        result = assign(stage_plan, pool, programs, score, seed + i, pins=stage_pins, group_blocks=group_blocks)
        groups.update(result)
        done.update(stage_names)
        for g in stage_plan:
            task_names.update(fill_tasks(result[g["name"]], tasks, g["name"]))
            occupied = timed_slots(tasks, g["name"])
            for n in result[g["name"]]:
                stages_of[n] += 1
                week_points[n] += g["points"]          # הניקוד הוא של התורנות, פעם אחת
                busy.setdefault(n, set()).update(occupied)
    return groups, task_names, shrunk


# ---------------------------------------------------------------------------
def set_cell(ws, row, col, value):
    cell = ws.cell(row=row, column=col)
    if not isinstance(cell, MergedCell):
        cell.value = value


def write_workbook(path, plan, groups, task_names, present, available, history,
                   havurot=None, week_points=None):
    wb = load_workbook(path)

    ws = wb[bw.SH_TASKS]
    for r in range(bw.TASK_FIRST_ROW, ws.max_row + 1):
        set_cell(ws, r, bw.T_NAMES, ", ".join(task_names[r]) if r in task_names else None)

    ws = wb[bw.SH_GROUPS]
    for i, g in enumerate(plan):
        r = bw.GROUP_FIRST_ROW + i
        set_cell(ws, r, bw.G_NAME, g["name"])
        set_cell(ws, r, bw.G_STAGE, g["stage"] or None)
        set_cell(ws, r, bw.G_POINTS, g["points"])
        set_cell(ws, r, bw.G_LEADER, g["leader"] or None)
        set_cell(ws, r, bw.G_MEMBERS, ", ".join(groups[g["name"]]) or None)
    for r in range(bw.GROUP_FIRST_ROW + len(plan), ws.max_row + 1):
        for col in (bw.G_NAME, bw.G_STAGE, bw.G_POINTS, bw.G_LEADER, bw.G_MEMBERS):
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
        set_cell(ws, r, bw.S_HAVURA, (havurot or {}).get(name))
        if name not in present:
            set_cell(ws, r, bw.S_AVAILABLE, None)
            set_cell(ws, r, bw.S_NOTE, "לא נוכח/ת")
        else:
            set_cell(ws, r, bw.S_AVAILABLE, "כן" if name in available else "לא")
            set_cell(ws, r, bw.S_NOTE, None)
        set_cell(ws, r, bw.S_GROUPS, "; ".join(lookup[name]) if name in lookup else None)
        set_cell(ws, r, bw.S_POINTS, (week_points or {}).get(name))

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
    staff = attendance_mod.load_staff(date)
    blocked = attendance_mod.load_blocked(date)
    group_blocks = attendance_mod.load_group_blocks(date)
    leaders = dict(bw.week_leaders(date), **attendance_mod.load_leaders(date))
    havurot = attendance_mod.load_havurot(date)

    plan = read_plan(date)
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
        args.seed if args.seed is not None else date.toordinal(), args.max_stages,
        staff=staff, blocked=blocked, leaders=leaders, group_blocks=group_blocks)

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
    records = [{"תאריך": date.isoformat(), "שם": n, "שלב": g["stage"],
                "קבוצה": g["name"], "ניקוד": g["points"]}
               for g in plan for n in groups[g["name"]]]
    history = record_duty(date.isoformat(), records)
    week_points = {n: sum(g["points"] for g in plan if n in groups[g["name"]]) for n in on_duty}
    write_workbook(path, plan, groups, task_names, set(present), set(available),
                   history, havurot, week_points)
    print("\nנכתב אל {}".format(path.relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path))


if __name__ == "__main__":
    main()
