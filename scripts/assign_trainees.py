#!/usr/bin/env python3
"""Assign the season's trainees to the 19 Mishmarim they build, and write the
result everywhere it is recorded. Deterministic (seeded), so re-running gives
the same answer and produces no diff.

Writes:
  migrations/2026-09-assign-trainees.sql   — run in the Supabase SQL Editor
  Mishmer-section/2026-27/schedule.md      — the owners column
  Mishmer-section/2026-27/students.md      — the per-trainee table
  students_tasks.md                        — the «אחראים» lines (the first-run seed)

Rules, asserted below, not assumed:
  1. #01–#02 stay צוות — the staff build them.
  2. 19 Mishmarim × 2 = 38 slots over 8 trainees → six get 5, two get 4.
  3. Two different trainees per Mishmar, and all 19 pairs distinct.
  4. **MIN_BUILD_DAYS between a trainee's own evenings**, measured on the real
     calendar read from schedule.md — not "no two consecutive Mishmarim". The
     evenings are not evenly spaced (#03→#04 and #15→#16 are a fortnight
     apart, the rest a week), and the number that matters is the app's own
     build window: a topic is due 21 days before the evening. At a 14-day
     spacing the topic deadline of a pair's next Mishmar falls a week before
     their current one happens — they build the next evening out of the last
     week of this one. 21 days is what makes that stop.
  5. AWAY and TOGETHER — the season's two human facts, declared here so the
     draw honours them and the assertions prove it.
"""
import random, re, sys
from pathlib import Path
from datetime import date

# The eight trainees of תשפ״ז. איתי בן יהודה left the programme in September;
# his four evenings were redistributed and his row is deleted from the database.
NAMES = ["איתי בן מנחם", "אלה מאיר", "זואה כהן", "יותם ספיר",
         "יעל שם טוב", "כליל בלאוקופף", "רוני פרנקל", "רותם דרור"]

# name → students.id. FROZEN, never re-derived: these ids are already the live
# database's truth (and `students.id` is referenced by assignments, outreach,
# feedback and tasks). Re-shuffling them would rename all eight rows for
# nothing. **id 4 belonged to איתי בן יהודה and is retired** — a future
# trainee gets a new id, never his.
STUDENT_IDS = {
    "זואה כהן": 1, "אלה מאיר": 2, "רוני פרנקל": 3, "איתי בן מנחם": 5,
    "יותם ספיר": 6, "רותם דרור": 7, "יעל שם טוב": 8, "כליל בלאוקופף": 9,
}
# Rows to remove, each guarded by the NAME we expect to find on it. The guard
# matters: `apply_trainee_roster` in the app hands a brand-new trainee the
# first FREE id, which may well be one of these — an unguarded DELETE would
# then quietly remove a person who had just joined.
RETIRED_ROWS = {4: "איתי בן יהודה", 10: "חניך 10"}

STAFF = (1, 2)
MISHMARIM = list(range(3, 22))          # #03–#21
SEED = 5787
RESTARTS = 150_000
MIN_BUILD_DAYS = 21                     # = the app's topic deadline
LOADS = [4, 4, 5, 5, 5, 5, 5, 5]
ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_MD = ROOT / "Mishmer-section/2026-27/schedule.md"

# Mishmarim a trainee cannot take, whatever the draw says.
AWAY = {"אלה מאיר": {3, 4}}             # abroad until the day before 8.10
# Trainees who must share exactly one evening.
TOGETHER = ("אלה מאיר", "זואה כהן")

# The pairing we were aiming at before איתי בן יהודה left: the committed
# schedule with the approved #04↔#13 exchange applied, minus him. It is not a
# constraint — it is the draw's preference, so that the evenings the pairs
# have already been told about survive wherever the rules allow. Frozen here
# rather than read back out of schedule.md, so this script stays a pure
# function of its constants and a second run cannot drift.
PREFERRED = {
    3:  ("יותם ספיר", "רותם דרור"),      4:  ("כליל בלאוקופף",),
    5:  ("זואה כהן", "יעל שם טוב"),      6:  ("איתי בן מנחם", "רותם דרור"),
    7:  ("רוני פרנקל", "יותם ספיר"),     8:  ("אלה מאיר", "כליל בלאוקופף"),
    9:  ("זואה כהן", "יותם ספיר"),       10: ("רותם דרור", "כליל בלאוקופף"),
    11: ("יעל שם טוב",),                 12: ("רוני פרנקל", "איתי בן מנחם"),
    13: ("זואה כהן", "אלה מאיר"),        14: ("רוני פרנקל",),
    15: ("איתי בן מנחם", "יעל שם טוב"),  16: ("אלה מאיר", "יותם ספיר"),
    17: ("זואה כהן", "רותם דרור"),       18: ("אלה מאיר", "איתי בן מנחם"),
    19: ("יעל שם טוב", "כליל בלאוקופף"), 20: ("רוני פרנקל", "רותם דרור"),
    21: ("יותם ספיר",),
}


# The generated Markdown is read by people, so counts are spelled out.
HEB_NUM = {1: "אחד", 2: "שניים", 3: "שלושה", 4: "ארבעה", 5: "חמישה", 6: "שישה",
           7: "שבעה", 8: "שמונה", 9: "תשעה", 10: "עשרה"}


def read_dates() -> dict[int, date]:
    """The real calendar, read from schedule.md — the season's source of truth.
    Copying the dates into this file would create a second one."""
    out = {}
    for mid, d, m, y in re.findall(r"^\| (\d\d) \| (\d+)\.(\d+)\.(\d{4}) \|",
                                   SCHEDULE_MD.read_text(encoding="utf-8"), flags=re.M):
        out[int(mid)] = date(int(y), int(m), int(d))
    missing = [m for m in MISHMARIM if m not in out]
    assert not missing, f"schedule.md has no date for {missing}"
    return out


def draw(rng: random.Random, dates: dict[int, date]):
    """One attempt: fill the evenings in order, each from the trainees who are
    free, not away, and far enough from their own previous evening. Among
    those, whoever already holds this evening comes first — that is what keeps
    the diff small — then whoever has the most left to do."""
    quota = {n: 5 for n in NAMES}
    for n in rng.sample(NAMES, 2):
        quota[n] = 4
    last: dict[str, date | None] = {n: None for n in NAMES}
    pairs, used = {}, set()
    for mid in MISHMARIM:
        pool = [n for n in NAMES
                if quota[n] > 0 and mid not in AWAY.get(n, ())
                and (last[n] is None
                     or (dates[mid] - last[n]).days >= MIN_BUILD_DAYS)]
        rng.shuffle(pool)
        pool.sort(key=lambda n: (-(n in PREFERRED[mid]) * 3, -quota[n]))
        chosen = None
        for a in range(len(pool)):
            for b in range(a + 1, len(pool)):
                pr = tuple(sorted((pool[a], pool[b])))
                if pr not in used:
                    chosen = pr
                    break
            if chosen:
                break
        if not chosen:
            return None
        used.add(chosen)
        pairs[mid] = chosen
        for n in chosen:
            quota[n] -= 1
            last[n] = dates[mid]
    if any(q != 0 for q in quota.values()):
        return None
    if not any(set(p) == set(TOGETHER) for p in pairs.values()):
        return None
    return pairs


def kept(pairs) -> int:
    """How many of the 38 slots a candidate leaves where the pairs expect them."""
    return sum(len(set(pairs[m]) & set(PREFERRED[m])) for m in MISHMARIM)


def main():
    dates = read_dates()
    rng = random.Random(SEED)
    # Best of a fixed number of seeded restarts: every candidate already obeys
    # every rule, so «best» only means «moves the fewest pairs».
    best = None
    for _ in range(RESTARTS):
        cand = draw(rng, dates)
        if cand and (best is None or kept(cand) > kept(best)):
            best = cand
    assert best, "no assignment satisfied the rules"
    pairs = best
    # ---- assertions: the rules, checked, not assumed ----
    load = {n: 0 for n in NAMES}
    seen = set()
    when: dict[str, list[date]] = {n: [] for n in NAMES}
    for mid in MISHMARIM:
        a, b = pairs[mid]
        assert a != b, f"#{mid} has one trainee twice"
        assert (a, b) not in seen, f"pair repeats at #{mid}"
        seen.add((a, b))
        for n in (a, b):
            load[n] += 1
            when[n].append(dates[mid])
            assert mid not in AWAY.get(n, ()), f"{n} is away for #{mid}"
    assert sorted(load.values()) == LOADS, load
    for n, days in when.items():
        gaps = [(y - x).days for x, y in zip(days, days[1:])]
        assert all(g >= MIN_BUILD_DAYS for g in gaps), (n, gaps)
    assert any(set(p) == set(TOGETHER) for p in pairs.values()), TOGETHER
    assert set(STUDENT_IDS) == set(NAMES), "STUDENT_IDS and NAMES disagree"
    # ---- SQL ----
    sql = [f"-- The season's {len(NAMES)} trainees and the evenings they build.",
           "-- Generated by scripts/assign_trainees.py (seed %d). Idempotent: run as often as needed." % SEED,
           "BEGIN;"]
    for n in NAMES:
        sql.append(f"UPDATE students SET name = '{n}' WHERE id = {STUDENT_IDS[n]};")
    for dead, who in sorted(RETIRED_ROWS.items()):
        sql.append(f"DELETE FROM students WHERE id = {dead} AND name = '{who}';"
                   "   -- assignments cascade; other student_id refs go NULL")
    sql.append(f"DELETE FROM assignments WHERE mishmar_id BETWEEN {MISHMARIM[0]} AND {MISHMARIM[-1]};")
    for mid in MISHMARIM:
        for n in pairs[mid]:
            sql.append("INSERT INTO assignments (mishmar_id, student_id) VALUES "
                       f"({mid}, {STUDENT_IDS[n]}) ON CONFLICT DO NOTHING;")
    sql.append("COMMIT;")
    (ROOT / "migrations").mkdir(exist_ok=True)
    (ROOT / "migrations/2026-09-assign-trainees.sql").write_text("\n".join(sql) + "\n", encoding="utf-8")

    def owners(mid):
        return " + ".join(pairs[mid])
    # ---- schedule.md: the owners column of #03–#21 ----
    sched = SCHEDULE_MD
    txt = sched.read_text(encoding="utf-8")
    def fix_row(m):
        mid = int(m.group(1))
        return m.group(0) if mid in STAFF else m.group(0).replace(m.group(2), owners(mid), 1)
    txt = re.sub(r"^\| (\d\d) \|[^\n]*?\| ((?:חניך \d+ \+ חניך \d+)|(?:[^|]+ \+ [^|]+?)) \|", fix_row, txt, flags=re.M)
    txt = re.sub(r"^האחראים הם [^\n]*\n",
                 f"האחראים הם {HEB_NUM[len(NAMES)]} החניכים של השנה — השיבוץ נוצר על ידי "
                 "`scripts/assign_trainees.py` ומוחל במסד דרך "
                 "`migrations/2026-09-assign-trainees.sql`.\n", txt, count=1, flags=re.M)
    sched.write_text(txt, encoding="utf-8")
    # ---- students_tasks.md: the seed's owners lines AND its index table ----
    # The first-run seed builds the student list from the index table's first
    # column and the assignments from the «אחראים» lines; both must carry the
    # real names, or a fresh database gets placeholders and no pairs.
    seed = ROOT / "students_tasks.md"
    t = seed.read_text(encoding="utf-8")
    cur = None
    out = []
    in_index = False
    index_done = False
    for line in t.splitlines(keepends=True):
        m = re.match(r"### משמר #(\d\d) ", line)
        if m:
            cur = int(m.group(1))
        if cur is None and line.startswith("| חניך") and not index_done and not in_index:
            # header row of the index table: emit the header + one row per trainee
            in_index = True
            out.append("| חניך/ה | משמרים | סה״כ |\n|---|---|---|\n")
            for n in NAMES:
                mine = [mid for mid in MISHMARIM if n in pairs[mid]]
                cells = " · ".join(f"[#{mid:02d}](#משמר-{mid:02d})" for mid in mine)
                out.append(f"| {n} | {cells} | {len(mine)} |\n")
            continue
        if in_index:
            if line.startswith("|") and "**צוות**" not in line:
                continue              # the old header separator / placeholder rows
            if "**צוות**" in line:
                out.append(line)
                in_index = False
                index_done = True
                continue
        if cur is None and line.startswith("> **שמות:**"):
            line = (f"> **שמות:** {HEB_NUM[len(NAMES)]} החניכים של השנה — השיבוץ נוצר על ידי "
                    "`scripts/assign_trainees.py` ומוחל במסד דרך "
                    "`migrations/2026-09-assign-trainees.sql`; הזריעה הראשונה קוראת "
                    "את השמות מהטבלה שלמטה.\n")
        if cur and cur not in STAFF and "**אחראים:**" in line:
            line = re.sub(r"\*\*אחראים:\*\* (?:חניך \d+|[^+·]+?) \+ (?:חניך \d+|[^·\n]+?)(?= ·|\n)",
                          f"**אחראים:** {owners(cur)}", line)
        out.append(line)
    seed.write_text("".join(out), encoding="utf-8")
    # ---- students.md: rewritten table ----
    rows = []
    for n in NAMES:
        mine = [mid for mid in MISHMARIM if n in pairs[mid]]
        gaps = [(dates[b] - dates[a]).days for a, b in zip(mine, mine[1:])]
        rows.append(f"| {n} | {', '.join(f'{mid:02d}' for mid in mine)} | "
                    f"{len(mine)} | {min(gaps)} ימים |")
    total = sum(len(p) for p in pairs.values())
    five = sum(1 for n in NAMES if load[n] == 5)
    students = ROOT / "Mishmer-section/2026-27/students.md"
    students.write_text(
        "# חניכים — תשפ״ז / 2026-27\n\n"
        f"> {HEB_NUM[len(NAMES)]} חניכים. השיבוץ מכסה **משמרים #03–21 בלבד** — #01 (משמר בוגרים) ו-#02 נבנים על ידי הצוות.\n"
        "> נוצר על ידי `scripts/assign_trainees.py` (זרע קבוע, ולכן ניתן לשחזור), ומוחל במסד דרך\n"
        "> `migrations/2026-09-assign-trainees.sql`. המסד הוא האמת; הקבצים כאן מתעדים אותו.\n\n"
        f"## השיבוץ\n\nסך הכל {total} שיבוצים ({len(MISHMARIM)} משמרים × 2) על {len(NAMES)} חניכים: "
        f"{HEB_NUM[five]} עם 5 משמרים ו{HEB_NUM[len(NAMES) - five]} עם 4.\n\n"
        "| חניך/ה | משמרים | סה״כ | מרווח מינימלי |\n|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
        "## כללי השיבוץ\n\n1. **שני אחראים לכל משמר** — לא ל-#01–02.\n"
        f"2. **עומס מאוזן** — {total} שיבוצים על {len(NAMES)} = {total / len(NAMES):.2f} בממוצע; "
        f"{five}×5 + {len(NAMES) - five}×4.\n"
        f"3. **בלי זוגות חוזרים** — {len(MISHMARIM)} הזוגות שונים זה מזה "
        f"(מתוך {len(NAMES) * (len(NAMES) - 1) // 2} האפשריים).\n"
        f"4. **חלון בנייה מלא** — לפחות {MIN_BUILD_DAYS} ימים בין שני משמרים של אותו אדם, בלוח השנה\n"
        "   האמיתי ולא בספירת משבצות. זה בדיוק התאריך המומלץ לסגירת נושא שהאפליקציה מחשבת\n"
        "   (‎21 יום לפני הערב), ולכן אף זוג לא בונה משמר מתוך השבוע האחרון של המשמר הקודם שלו.\n"
        "5. **אילוצים אישיים** — נרשמים ב-`AWAY` וב-`TOGETHER` בראש הסקריפט, ונבדקים בהרצה.\n",
        encoding="utf-8")
    print("student ids:", {n: STUDENT_IDS[n] for n in NAMES})
    print(f"kept {kept(pairs)}/{total} slots from the previous pairing")
    for mid in MISHMARIM:
        moved = " *" if set(pairs[mid]) != set(PREFERRED[mid]) else "  "
        print(f" {moved}#{mid:02d} {dates[mid].strftime('%d.%m')}: {owners(mid)}")
    print("load:", load)
    print("wrote migrations/2026-09-assign-trainees.sql, schedule.md, students.md, students_tasks.md")


if __name__ == "__main__":
    main()
