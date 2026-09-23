# -*- coding: utf-8 -*-
"""שבת שלמה בפקודה אחת: תבנית ← קובץ השבת ← שיבוץ ← פליירים ולו"ז צל ← zip ← בדיקות.

    python3 tools/shabbat.py 2026-09-25
    python3 tools/shabbat.py 2026-09-25 --check      # רק בדיקות ו-zip, על מה שכבר קיים

לפני ההרצה צריך שלושה קבצים לשבת הזו — tools/import_form.py כותב אותם מההודעה שהטופס הרכיב:
  data/attendance/<תאריך>.csv — נוכחים, מי לא בשישי / במוצ"ש, הצמדות
  data/preps/<תאריך>.csv      — מה מכינים, כמה, כמה אנשים ומי אחראי
  data/menu/<תאריך>.csv       — הקייטרינג, חלוקת העוגות ומה מוגש מההכנות
ושורה ב-data/weeks.csv אם השבת משותפת עם שנה א'. הצוות, הלו"ז והתורנויות הקבועות
כבר במערכת.
"""
import argparse
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import assign_groups
import attendance
import build_workbook as bw
import export_pdf as ep


def run(script, *args):
    print("\n▶ {} {}".format(script, " ".join(args)))
    if subprocess.run([sys.executable, str(TOOLS / script), *args], cwd=ROOT).returncode:
        raise SystemExit("✗ {} נכשל — עוצרים כאן".format(script))


def pack(out_dir, date):
    """כל ה-PNG בקובץ zip אחד — לשליחה לחניכים."""
    path = out_dir / "פליירים {}.zip".format(date.strftime("%d.%m"))
    pngs = sorted(out_dir.glob("*.png"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for png in pngs:
            zf.write(png, png.name)
    return path, len(pngs)


def checks(date, workbook, out_dir):
    """הבדיקות שכל שבת צריכה לעבור. מחזיר (נתונים, בעיות, אזהרות) — בעיות מכשילות, אזהרות לא."""
    data = ep.read_workbook(workbook)
    stage_of = {g["name"]: g["stage"] for g in data["groups"]}
    problems, warnings = [], []

    seen = {}                                            # אף אחד לא בשני מקומות באותה שעה
    for t in data["tasks"]:
        if t["hour"] is None:
            continue
        for n in t["names"]:
            key = (t["day"], t["hour"], n)
            if key in seen and seen[key] != t["row"]:
                problems.append("{} משובץ/ת פעמיים ב{} {}".format(n, t["day"], ep.hhmm(t["hour"])))
            seen[key] = t["row"]

    blocked = attendance.load_blocked(date)             # חסומים לא בשלב (או בקבוצה) שממנו נחסמו
    blocked_groups = attendance.load_group_blocks(date)
    chosen = {n: {x.strip() for x in v.split(";") if x.strip()} for n, v in attendance.load_pins(date).items()}
    for group, n in dict(bw.week_leaders(date), **attendance.load_leaders(date)).items():
        chosen.setdefault(n, set()).add(group)          # הצמדה ידנית או «אחראי על» גוברות על החסימה
    for g in data["groups"]:
        for n in g["members"]:
            if g["stage"] in blocked.get(n, ()):
                problems.append("{} ב«{}» למרות שאינו/ה זמין/ה ב{}".format(n, g["name"], g["stage"]))
            if g["name"] in blocked_groups.get(n, ()) and g["name"] not in chosen.get(n, ()):
                problems.append("{} ב«{}» למרות שהקבוצה חסומה לו/ה (לא בקבוצה)".format(n, g["name"]))

    for g in data["groups"]:                             # לכל חבר קבוצה יש משימה
        mine = [t for t in data["tasks"] if t["group"] == g["name"]]
        for n in g["members"]:
            if not any(n in t["names"] for t in mine):
                problems.append("{} ב«{}» בלי משימה".format(n, g["name"]))
        if not mine:
            problems.append("לקבוצה «{}» אין משימות".format(g["name"]))
        for t in mine:
            if not t["names"]:
                problems.append("משימה בלי שמות: «{}» [{}]".format(t["task"][:40], g["name"]))
    names = {g["name"] for g in data["groups"]}
    for t in data["tasks"]:                              # משימה בלי קבוצה מותרת (הוספה ידנית)
        if t["group"] and t["group"] not in names:
            problems.append("משימה «{}» בקבוצה שלא בתכנית: {}".format(t["task"][:40], t["group"]))

    needs = {g["name"] for g in assign_groups.read_plan(date) if g["needs_staff"]}
    for g in data["groups"]:                             # לכל קבוצה שדורשת אחראי — יש
        if g["name"] in needs and not g["leader"]:
            problems.append("ל«{}» אין אחראי/ת".format(g["name"]))

    for t in data["tasks"]:                              # כל משימה מעוגנת, אין {…} שנשאר
        if not ep.find_event(data["events"], t):
            problems.append("משימה לא מעוגנת ללו\"ז: «{}» (עוגן: {})".format(t["task"][:40], t["anchor"] or "—"))
        if "{" in t["task"] or "{" in (t["recipe"] or ""):
            problems.append("מציין מקום שלא הוחלף: «{}»".format(t["task"][:50]))
        for dish in ep.split_dishes(t["recipe"]):
            if dish not in data["recipes"]:
                problems.append("אין בגיליון «מתכונים» את «{}» (משימה: {})".format(dish, t["task"][:30]))

    last = None                                          # הלו"ז: לכל אירוע שעה, ולפי הסדר
    for e in data["events"]:
        if e["hour"] is None:
            warnings.append("לאירוע «{}» אין שעה בלו\"ז".format(e["name"]))
            continue
        key = bw.event_sort_key(e["day"], e["hour"])
        if last and key < last[0]:
            warnings.append("«{}» ({}) מופיע אחרי «{}» בלו\"ז".format(e["name"], ep.hhmm(e["hour"]), last[1]))
        last = (key, e["name"])
    if bw.read_shabbat(date).get("אנשי צוות"):         # שבת שסגרנו — הדברים שהאחראים סוגרים
        notes = {e["name"]: e["note"] or "" for e in data["events"]}
        if "מעביר" not in notes.get("טיש", ""):
            warnings.append("לא רשום מי מעביר את הטיש")
        if "מעבירים" not in notes.get("חבורות", "") or "טרם" in notes.get("חבורות", ""):
            warnings.append("לא רשומים מעבירי החבורות")

    for g in data["groups"]:                             # כל פלייר בעמוד אחד
        pdf = out_dir / "{}.pdf".format(g["name"])
        if pdf.exists() and ep.pdf_pages(pdf) != 1:
            problems.append("הפלייר «{}» יצא ב-{} עמודים".format(g["name"], ep.pdf_pages(pdf)))
    return data, problems, warnings


def main():
    ap = argparse.ArgumentParser(description="שבת שלמה בפקודה אחת")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-25")
    ap.add_argument("--check", action="store_true", help="בלי להריץ מחדש — רק בדיקות ו-zip")
    args = ap.parse_args()
    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    workbook = ROOT / "shabbatot" / "{}.xlsx".format(date.isoformat())
    out_dir = ROOT / "shabbatot" / date.isoformat()

    needed = [(attendance.path_for(date), "רשימת הנוכחים"),
              (ROOT / "data" / "preps" / "{}.csv".format(date.isoformat()), "ההכנות של שישי"),
              (ROOT / "data" / "menu" / "{}.csv".format(date.isoformat()), "התפריט")]
    missing = [(p, what) for p, what in needed if not p.exists()]
    if missing:
        raise SystemExit("✗ חסר לשבת הזו:\n" + "\n".join(
            "   · {} — {}".format(what, p.relative_to(ROOT)) for p, what in missing) +
            "\n  קולטים את ההודעה מהטופס: python3 tools/import_form.py < הודעה.txt")

    if not args.check:
        run("build_workbook.py")
        run("new_shabbat.py", date.isoformat())
        run("assign_groups.py", date.isoformat())
        run("export_pdf.py", date.isoformat())

    data, problems, warnings = checks(date, workbook, out_dir)
    zip_path, count = pack(out_dir, date)
    on_duty = {n for g in data["groups"] for n in g["members"]}

    print("\n" + "═" * 60)
    print("שבת {} · {} · {} תורנים ב-{} קבוצות".format(
        ep.hebrew_date_range(date), data["parasha"] or "", len(on_duty), len(data["groups"])))
    print("zip: {} ({} תמונות)".format(zip_path.relative_to(ROOT), count))
    for w in warnings:
        print("  ⚠ " + w)
    if problems:
        print("\n⚠ {} בעיות:".format(len(problems)))
        for p in problems:
            print("   · " + p)
        sys.exit(1)
    print("✓ כל הבדיקות עברו")


if __name__ == "__main__":
    main()
