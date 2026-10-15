# -*- coding: utf-8 -*-
"""שבת שלמה בפקודה אחת: תבנית ← קובץ השבת ← שיבוץ ← הדפים (לו"ז שבת, מי בכל תורנות, דף לכל תורנות) ← בדיקות.
ה-PDF בתיקיית השבת, והתמונות לשליחה — בתיקייה «תמונות» שבתוכה, ממוספרות כמו דף התורנויות.

    python3 tools/shabbat.py 2026-09-25
    python3 tools/shabbat.py 2026-09-25 --check      # רק בדיקות, על מה שכבר קיים

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
from datetime import datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import assign_groups
import attendance
import build_workbook as bw
import export_pdf as ep


def brief(text, n):
    """טקסט משימה להודעה בשורה אחת — משימה של כמה שורות מתחברת ב-« / »."""
    return (text or "").replace("\n", " / ")[:n]


def run(script, *args):
    print("\n▶ {} {}".format(script, " ".join(args)))
    if subprocess.run([sys.executable, str(TOOLS / script), *args], cwd=ROOT).returncode:
        raise SystemExit("✗ {} נכשל — עוצרים כאן".format(script))


def images(out_dir):
    """תיקיית התמונות לשליחה ומספר התמונות בה."""
    folder = out_dir / ep.IMAGES
    return folder, len(list(folder.glob("*.png")))


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
            for other in data["groups"]:                 # bw.APART: מנקי חדר האוכל בשישי — לא מההכנות
                if (other["stage"] in bw.APART.get(g["name"], ()) and n in other["members"]
                        and g["name"] not in chosen.get(n, ())):
                    problems.append("{} גם ב«{}» וגם ב«{}»".format(n, other["name"], g["name"]))

    for g in data["groups"]:                             # לכל חבר קבוצה יש משימה
        mine = [t for t in data["tasks"] if t["group"] == g["name"]]
        for n in g["members"]:
            if not any(n in t["names"] for t in mine):
                problems.append("{} ב«{}» בלי משימה".format(n, g["name"]))
        if not mine:
            problems.append("לקבוצה «{}» אין משימות".format(g["name"]))
        for t in mine:
            if not t["names"] and t["people"] != 0:     # 0 = הכנת מצטרפים בלבד — השמות במשימת העזרה
                problems.append("משימה בלי שמות: «{}» [{}]".format(brief(t["task"], 40), g["name"]))
        helping = [n for h in bw.help_tasks(data["tasks"], g["name"]) for n in h["names"]]
        if mine and all(t["people"] == 0 for t in mine):   # הכנת מצטרפים בלבד (בראוניז 0+2)
            if not helping:
                problems.append("ל«{}» אין אף אחד — אין אנשים משלה ואף אחד לא מצטרף".format(g["name"]))
            elif g["leader"] and g["leader"] not in helping:
                problems.append("האחראי/ת של «{}» ({}) לא מבין המצטרפים".format(g["name"], g["leader"]))
    names = {g["name"] for g in data["groups"]}
    for t in data["tasks"]:                              # משימה בלי קבוצה מותרת (הוספה ידנית)
        if t["group"] and t["group"] not in names:
            problems.append("משימה «{}» בקבוצה שלא בתכנית: {}".format(brief(t["task"], 40), t["group"]))

    plan = assign_groups.read_plan(date)
    needs = {g["name"] for g in plan if g["needs_staff"]}
    for t in data["tasks"]:                              # משימה שלא התמלאה — הוקטנה (חסרים זמינים) או לא
        if t["people"] and len(t["names"]) < int(t["people"]):
            warnings.append("ב«{}» [{}] שובצו {} מתוך {}".format(brief(t["task"], 30), t["group"], len(t["names"]),
                                                              int(t["people"])))
    staff = set(attendance.load_staff(date))             # קבוצת צוות שהאחראי/ת שלה נבחר/ה אוטומטית ולא מהצוות
    explicit = dict(bw.week_leaders(date), **attendance.load_leaders(date))
    for g in data["groups"]:
        if g["name"] in needs and g["leader"] and g["leader"] not in staff and g["name"] not in explicit:
            warnings.append("«{}» צריכה אחראי/ת מצוות השבת — לא היה פנוי, נבחר/ה {}".format(g["name"], g["leader"]))
    warnings += assign_groups.stale_groups(date, {g["name"] for g in plan})
    for g in data["groups"]:                             # לכל קבוצה שדורשת אחראי — יש
        if g["name"] in needs and not g["leader"]:
            problems.append("ל«{}» אין אחראי/ת".format(g["name"]))

    for t in data["tasks"]:                              # כל משימה מעוגנת, אין {…} שנשאר
        if not ep.find_event(data["events"], t):
            problems.append("משימה לא מעוגנת ללו\"ז: «{}» (עוגן: {})".format(brief(t["task"], 40), t["anchor"] or "—"))
        if "{" in t["task"] or "{" in (t["recipe"] or ""):
            problems.append("מציין מקום שלא הוחלף: «{}»".format(brief(t["task"], 50)))
        for dish in ep.split_dishes(t["recipe"]):
            if dish not in data["recipes"]:
                problems.append("אין בגיליון «מתכונים» את «{}» (משימה: {})".format(dish, brief(t["task"], 30)))

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

    for g in data["groups"]:                             # כל פלייר בעמוד אחד (ועם מתכון ארוך — ועוד עמוד מתכון)
        pdf = out_dir / "{}.pdf".format(ep.safe_name(g["name"]))
        recipe = any(ep.split_dishes(t["recipe"]) for t in data["tasks"] if t["group"] == g["name"])
        if pdf.exists() and ep.pdf_pages(pdf) > (2 if recipe else 1):
            problems.append("הפלייר «{}» יצא ב-{} עמודים".format(g["name"], ep.pdf_pages(pdf)))

    for f in out_dir.rglob("*"):                         # שמות שעוברים בווינדוס (" בשם — הקובץ נעלם בחילוץ)
        if f.name != ep.safe_name(f.name):
            problems.append("שם קובץ שלא יעבור בווינדוס: {}".format(f.relative_to(out_dir)))
    folder = out_dir / ep.IMAGES                         # תמונה לכל תורנות, ללו"ז ולדף התורנויות
    if folder.is_dir():
        cards, _ = ep.duty_cards(data)
        need = [ep.image_name(0, ep.SCHEDULE_NAME)] + [ep.image_name(n, c["name"]) for n, c in enumerate(cards, 1)]
        need = [n for n in need if not (folder / n).exists()]
        if not list(folder.glob(ep.image_name(0, ep.DUTIES_NAME).replace(".png", "*.png"))):
            need.append(ep.image_name(0, ep.DUTIES_NAME))
        if need:
            problems.append("חסרות תמונות ב-{}/: {}".format(ep.IMAGES, ", ".join(need)))
    return data, problems, warnings


def main():
    ap = argparse.ArgumentParser(description="שבת שלמה בפקודה אחת")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-25")
    ap.add_argument("--check", action="store_true", help="בלי להריץ מחדש — רק בדיקות")
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
    folder, count = images(out_dir)
    on_duty = {n for g in data["groups"] for n in g["members"]}

    print("\n" + "═" * 60)
    print("שבת {} · {} · {} תורנים ב-{} קבוצות".format(
        ep.hebrew_date_range(date), data["parasha"] or "", len(on_duty), len(data["groups"])))
    print("תמונות: {}/ ({})".format(folder.relative_to(ROOT), count))
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
