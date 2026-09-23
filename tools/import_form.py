# -*- coding: utf-8 -*-
"""קליטת ההודעה שהטופס («טופס שבת» ב-docs/) הרכיב — לקבצי השבת.

    python3 tools/import_form.py < הודעה.txt
    python3 tools/import_form.py --file הודעה.txt --dry-run

ההודעה נפתחת ב«📋 טופס שבת · <תאריך>», ובנויה מקטעים «— שם —». הכלי כותב:
  data/attendance/<תאריך>.csv — כל החניכים פחות «לא בשבת»; «לא בשישי» / «עוזבים»
                                 הופכים ל«לא זמין בשלב»
  data/preps/<תאריך>.csv      — ההכנות, ארוחת צהריים שישי ומוצ"ש
  data/menu/<תאריך>.csv       — קייטרינג, מה מההכנות, חלוקת העוגות
  data/weeks.csv               — שבת משותפת כן/לא
  data/recipes.csv             — מתכונים שצורפו (מצרכים ואופן הכנה)
ושינויי הלו"ז וההערות — טקסט חופשי — מודפסים לטיפול ידני. אחר כך: tools/shabbat.py <תאריך>.
"""
import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attendance
import build_workbook as bw
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SECTION = re.compile(r"^—\s*(.+?)\s*—$")
PREP_FIELDS = ["הכנה", "יום", "שעה", "משימה", "כמות", "אנשים", "אחראי", "עזרה מבית המדרש", "מתכון", "הערה"]
MENU_FIELDS = ["ארוחה", "מנה", "כמות", "הערה"]
FRIDAY = "הכנות שישי;תורנות שישי"
MOTZASH = bw.STAGES[-1]
CLEANING = {"ניקיון בית המדרש": "ניקיון בית המדרש", "ניקיון חדר האוכל": "ניקיון חדר האוכל"}
MOTZASH_DINNER = 'ארוחת ערב מוצ"ש'
DEFAULT_CLEANERS = "12"


def parse(text):
    """{"date", "shared", "filler", sections: {שם: [שורות]}} — בלי ניחושים: מבנה קבוע."""
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    head = next((l for l in lines if "טופס שבת" in l), "")
    m = re.search(r"\d{4}-\d{2}-\d{2}", head)
    if not m:
        raise SystemExit("✗ לא נמצאה שורת «📋 טופס שבת · <תאריך>» — זו לא הודעה מהטופס?")
    msg = {"date": datetime.strptime(m.group(0), "%Y-%m-%d").date(), "shared": False, "filler": "",
           "sections": {}}
    current = None
    for line in lines:
        s = SECTION.match(line)
        if s:
            current = s.group(1)
            msg["sections"].setdefault(current, [])
        elif current is None:
            if line.startswith("שנה א'"):
                msg["shared"] = line.split(":", 1)[-1].strip() == "כן"
            elif line.startswith("מילא/ה"):
                msg["filler"] = line.split(":", 1)[-1].strip()
        elif current != "סוף":
            msg["sections"][current].append(line)
    for k, v in msg["sections"].items():            # שורות ריקות רק בתוך מתכון
        if not k.startswith("מתכון"):
            msg["sections"][k] = [l for l in v if l]
    if "סוף" not in msg["sections"]:
        print("⚠ ההודעה לא מסתיימת ב«— סוף —» — ייתכן שנחתכה בהעתקה. בודקים שהכול נכנס.")
    return msg


def fields(line):
    """«חלות · כמה: 10 ק"ג · אנשים: 5» → ("חלות", {כמה: ..., אנשים: ...})."""
    parts = [p.strip() for p in line.split(" · ")]
    head, kv = parts[0], {}
    for p in parts[1:]:
        k, _, v = p.partition(":")
        kv[k.strip()] = v.strip()
    return head, kv


def keyed(lines):
    """«ארוחת ערב: שניצל, אורז» → {ארוחת ערב: "שניצל, אורז"}."""
    out = {}
    for l in lines:
        k, _, v = l.partition(":")
        out[k.strip()] = v.strip()
    return out


def recipes_of(sections):
    """{מנה: (מצרכים, הוראות)} מקטעי «— מתכון: X —»."""
    out = {}
    for name, lines in sections.items():
        if not name.startswith("מתכון:"):
            continue
        dish, part, ing, steps = name.split(":", 1)[1].strip(), None, [], []
        for l in lines:
            if l in ("מצרכים:", "הכנה:"):
                part = l
            elif l:
                (ing if part == "מצרכים:" else steps).append(l)
        out[dish] = ("\n".join(ing), "\n".join(steps))
    return out


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def last_havurot():
    """החבורה של כל חניך מקובץ הנוכחות האחרון שיש בו חבורות."""
    for path in sorted((DATA / "attendance").glob("*.csv"), reverse=True):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            h = {r["שם"]: (r.get("חבורה") or "").strip() for r in csv.DictReader(fh)}
        if any(h.values()):
            return h
    return {}


def build(msg, warn):
    sec = msg["sections"]
    students = roster.read_students()
    names = [s["שם"] for s in students]
    program = {s["שם"]: s.get("תוכנית", "") for s in students}

    def who(raw):
        name, how = roster.match_name(raw, names)
        if name is None:
            warn("לא זוהה ברשימה: «{}»".format(raw))
        return name

    # --- נוכחות --------------------------------------------------------------
    out = {who(n) for n in sec.get("לא בשבת", [])} - {None}
    nofri = {}
    for line in sec.get("לא בשישי", []):
        name, _ = fields(line)
        n = who(name)
        if n:
            nofri[n] = line.split(" · ", 1)[1].strip() if " · " in line else ""
    leave = {who(n) for n in sec.get('עוזבים לפני מוצ"ש', [])} - {None}
    extra = []
    for raw in sec.get("לא ברשימה", []):
        n, _ = roster.match_name(raw, names)
        if n:
            extra.append(n)
        else:
            warn("«{}» לא ברשימת החניכים — מוסיפים ל-data/students.csv ומריצים שוב".format(raw))
    havurot = last_havurot()
    present = [n for n in names if n not in out]
    att = []
    for n in present:
        blocked = FRIDAY if n in nofri else (MOTZASH if n in leave else "")
        note = ("לא בשישי" + (" — " + nofri[n] if nofri.get(n) else "")) if n in nofri else \
               ("עוזב/ת לפני מוצ\"ש" if n in leave else "")
        att.append({"שם": n, "תוכנית": program.get(n, ""), "חבורה": havurot.get(n, ""), "זמין לתורנות": "כן",
                    "לא זמין בשלב": blocked, "צוות שבת": "", "שיבוץ ידני": "", "אחראי על": "", "הערה": note})

    # --- הכנות ----------------------------------------------------------------
    recipes = recipes_of(sec)
    known = {r["מנה"] for r in bw.read_csv("recipes.csv")}
    friday_ok = set(present) - set(nofri)

    def lead(name, group):
        if not name:
            return ""
        n = who(name)
        if n and n not in friday_ok:
            warn("{} אחראי/ת על «{}» אבל לא בשישי בבוקר".format(n, group))
        return n or ""

    preps = []
    for line in sec.get("הכנות", []):
        name, kv = fields(line)
        if not kv.get("אנשים", "").isdigit() or int(kv["אנשים"]) < 1:
            warn("ל«{}» חסר כמה אנשים".format(name))
        dish = name if (name in recipes or name in known) else ""
        preps.append({"הכנה": name, "יום": "", "שעה": "07:00" if name.startswith("חלות") else "", "משימה": "",
                      "כמות": kv.get("כמה", ""), "אנשים": kv.get("אנשים", ""),
                      "אחראי": lead(kv.get("אחראי", ""), name), "עזרה מבית המדרש": kv.get("עזרה", ""),
                      "מתכון": dish, "הערה": kv.get("הערה", "")})
    for line in sec.get("ארוחת צהריים שישי", []):
        _, kv = fields("x · " + line)
        preps.append({"הכנה": "ארוחת צהריים שישי", "יום": "", "שעה": "", "משימה": "",
                      "כמות": kv.get("מה", ""), "אנשים": kv.get("אנשים", "2"),
                      "אחראי": lead(kv.get("אחראי", ""), "ארוחת צהריים שישי"),
                      "עזרה מבית המדרש": "", "מתכון": "", "הערה": ""})
    motz = keyed(sec.get('מוצ"ש', []))
    for key, group in CLEANING.items():
        n = motz.get(key, "") or DEFAULT_CLEANERS
        if n != DEFAULT_CLEANERS:
            if not n.isdigit() or int(n) < 1:
                warn("«{}: {}» — צריך מספר גדול מ-0; נשאר {}".format(key, n, DEFAULT_CLEANERS))
                continue
            preps.append({"הכנה": group, "יום": "מוצאי שבת", "שעה": "", "משימה": group, "כמות": "",
                          "אנשים": n, "אחראי": "", "עזרה מבית המדרש": "", "מתכון": "", "הערה": ""})
    if motz.get("ארוחת ערב"):
        preps.append({"הכנה": MOTZASH_DINNER, "יום": "מוצאי שבת", "שעה": "",
                      "משימה": "הכנת ארוחת ערב: " + motz["ארוחת ערב"], "כמות": "", "אנשים": "5",
                      "אחראי": "", "עזרה מבית המדרש": "", "מתכון": "", "הערה": ""})

    # --- תפריט ----------------------------------------------------------------
    menu = []
    def add(meal, text, split):
        items = [x.strip() for x in text.split(",")] if split else [text.strip()]
        menu.extend({"ארוחה": meal, "מנה": x, "כמות": "", "הערה": ""} for x in items if x)
    cat = keyed(sec.get("קייטרינג", []))
    for k in ("ארוחת ערב", "ארוחת צהריים", "סלטים"):
        add(k, cat.get(k, ""), True)
    frm = keyed(sec.get("מההכנות", []))
    add("מההכנות לערב", frm.get("לערב", ""), False)
    add("מההכנות לצהריים", frm.get("לצהריים", ""), False)
    cakes = keyed(sec.get("עוגות", []))
    for k in ("טיש", "קידוש", "סעודה שלישית"):
        add(k, cakes.get(k, ""), False)
    for k in ("ארוחת ערב", "ארוחת צהריים", "סלטים"):
        if not cat.get(k):
            warn("אין קייטרינג ל«{}» — המשימות יציגו סוגריים ריקים; לבדוק מול המטבח".format(k))
    return att, preps, menu, recipes


def main():
    ap = argparse.ArgumentParser(description="קליטת טופס השבת")
    ap.add_argument("--file", help="קובץ ההודעה (ברירת מחדל: stdin)")
    ap.add_argument("--dry-run", action="store_true", help="רק להציג, בלי לכתוב")
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    msg = parse(text)
    warnings = []
    att, preps, menu, recipes = build(msg, warnings.append)
    date, iso = msg["date"], msg["date"].isoformat()

    print("טופס שבת {} · מילא/ה: {} · שנה א': {}".format(iso, msg["filler"] or "—", "כן" if msg["shared"] else "לא"))
    print("  {} נוכחים · {} לא בשישי · {} עוזבים לפני מוצ\"ש".format(
        len(att), sum(r["לא זמין בשלב"] == FRIDAY for r in att), sum(r["לא זמין בשלב"] == MOTZASH for r in att)))
    for p in preps:
        print("  · {:<22} {:<16} {} אנשים{}{}".format(p["הכנה"], p["כמות"] or p["משימה"][:16], p["אנשים"],
              " · אחראי: " + p["אחראי"] if p["אחראי"] else "",
              " · עזרה: " + p["עזרה מבית המדרש"] if p["עזרה מבית המדרש"] else ""))
    for label, key in (("שינויים בלו\"ז", 'לו"ז'), ("הערות", "הערות")):
        for line in msg["sections"].get(key, []):
            print("  ✎ {} (לטיפול ידני): {}".format(label, line))
    for w in warnings:
        print("  ⚠ " + w)
    if args.dry_run:
        print("(dry-run — לא נכתב דבר)")
        return

    if attendance.path_for(date).exists():
        print("  (מחליף את קובץ הנוכחות הקיים)")
    write_csv(attendance.path_for(date), att, attendance.FIELDS)
    write_csv(DATA / "preps" / "{}.csv".format(iso), preps, PREP_FIELDS)
    write_csv(DATA / "menu" / "{}.csv".format(iso), menu, MENU_FIELDS)

    weeks = bw.read_csv("weeks.csv") if (DATA / "weeks.csv").exists() else []
    weeks = [w for w in weeks if w["תאריך"] != iso] + [
        {"תאריך": iso, "שבת משותפת": "כן" if msg["shared"] else "לא", "הערה": "מילא/ה: " + msg["filler"]}]
    write_csv(DATA / "weeks.csv", sorted(weeks, key=lambda w: w["תאריך"]), ["תאריך", "שבת משותפת", "הערה"])

    if recipes:
        rows = bw.read_csv("recipes.csv")
        qty = {p["הכנה"]: p["כמות"] for p in preps}
        for dish, (ing, steps) in recipes.items():
            rows = [r for r in rows if r["מנה"] != dish] + [
                {"קטגוריה": "", "מנה": dish, "כמות": qty.get(dish, ""), "מרכיבים": ing, "הוראות": steps, "הערה": ""}]
            print("  + מתכון: {}".format(dish))
        write_csv(DATA / "recipes.csv", rows, ["קטגוריה", "מנה", "כמות", "מרכיבים", "הוראות", "הערה"])
    print("\nנכתב. הבא: python3 tools/shabbat.py {}".format(iso))


if __name__ == "__main__":
    main()
