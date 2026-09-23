# -*- coding: utf-8 -*-
"""קליטת ההודעה שהטופס (docs/index.html, ב-GitHub Pages) הרכיב — לקבצי השבת.

    python3 tools/import_form.py < הודעה.txt
    python3 tools/import_form.py --file הודעה.txt --dry-run

ההודעה נפתחת ב«📋 טופס שבת v2 · <תאריך>», ובנויה מקטעים «— שם —» של שורות «מפתח: ערך»
מחוברות ב-« · ». הכלי כותב:
  data/attendance/<תאריך>.csv — כל החניכים פחות «לא בשבת»; «לא בשישי» / «עוזבים» הופכים
                                 ל«לא זמין בשלב», ומעבירי החבורות — «לא בקבוצה: ארוחת צהריים שבת»
  data/preps/<תאריך>.csv      — ההכנות, ארוחת צהריים שישי, מספרי המנקים וארוחת מוצ"ש
  data/menu/<תאריך>.csv       — קייטרינג, סלטי קייטרינג, הסלטים שלפני הארוחה וחלוקת העוגות
  data/schedule/<תאריך>.csv   — מי מעביר טיש/חבורות/שיעור, סעודה שלישית, ערב חברה, מקומות
                                 (רק שורות «מקור=טופס» מוחלפות; שורות שהוספו ידנית נשמרות)
  data/recipes/<תאריך>.csv    — המתכונים שצורפו (ומנה חדשה נכנסת גם ל-data/recipes.csv)
  data/weeks.csv               — שבת משותפת, וחלון התנורים שלנו
«שינויים נוספים בלו"ז» וההערות — טקסט חופשי — מודפסים לטיפול ידני. אחר כך: tools/shabbat.py <תאריך>.
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
TIME = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
PREP_FIELDS = ["הכנה", "יום", "שעה", "עוגן", "משימה", "כמות", "אנשים", "אחראי", "עזרה", "מתכון", "הערה"]
MENU_FIELDS = ["ארוחה", "מנה", "כמות", "הערה"]
SCHED_FIELDS = ["יום", "אירוע", "מקום", "בסיס", "היסט", "עיגול", "הערה", "פעולה", "מקור"]
WEEK_FIELDS = ["תאריך", "שבת משותפת", "תנורים", "הערה"]
FORM = "טופס"                                    # «מקור» של שורות לו"ז שהייבוא כותב
FRIDAY = "הכנות שישי;תורנות שישי"
MOTZASH = bw.STAGES[-1]
HAVURA_BLOCK = "ארוחת צהריים שבת"                # מעבירי החבורות (11:45) לא בעריכת השולחן
MOTZASH_DINNER = 'ארוחת ערב מוצ"ש'
DEFAULT_CLEANERS = "12"
CLEANING = {"חדר האוכל בשישי": (bw.FRIDAY_DINING, "שישי"),
            'בית המדרש במוצ"ש': ("ניקיון בית המדרש", "מוצאי שבת"),
            'חדר האוכל במוצ"ש': ("ניקיון חדר האוכל", "מוצאי שבת"),
            "ניקיון בית המדרש": ("ניקיון בית המדרש", "מוצאי שבת"),          # הודעה בגרסה הקודמת
            "ניקיון חדר האוכל": ("ניקיון חדר האוכל", "מוצאי שבת")}


def parse(text):
    """{"date", "v2", "shared", "ovens", "filler", sections: {שם: [שורות]}} — בלי ניחושים: מבנה קבוע."""
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    head = next((l for l in lines if "טופס שבת" in l), "")
    m = re.search(r"\d{4}-\d{2}-\d{2}", head)
    if not m:
        raise SystemExit("✗ לא נמצאה שורת «📋 טופס שבת · <תאריך>» — זו לא הודעה מהטופס?")
    msg = {"date": datetime.strptime(m.group(0), "%Y-%m-%d").date(), "v2": " v2" in head, "shared": False,
           "ovens": "", "filler": "", "sections": {}}
    current = None
    for line in lines:
        s = SECTION.match(line)
        if s:
            current = s.group(1)
            msg["sections"].setdefault(current, [])
        elif current is None:
            value = line.split(":", 1)[-1].strip()
            if line.startswith("שנה א'"):
                msg["shared"] = value == "כן"
            elif line.startswith("תנורים"):
                msg["ovens"] = value
            elif line.startswith("מילא/ה"):
                msg["filler"] = value
        elif current != "סוף":
            msg["sections"][current].append(line)
    for k, v in msg["sections"].items():            # שורות ריקות רק בתוך מתכון
        if not k.startswith("מתכון"):
            msg["sections"][k] = [l for l in v if l]
    if "סוף" not in msg["sections"]:
        print("⚠ ההודעה לא מסתיימת ב«— סוף —» — ייתכן שנחתכה בהעתקה. בודקים שהכול נכנס.")
    if not msg["shared"]:
        msg["ovens"] = ""
    return msg


def fields(line):
    """«חלות · כמה: 10 ק"ג · אנשים: 5» → ("חלות", {כמה: ..., אנשים: ...})."""
    parts = [p.strip() for p in line.split(" · ")]
    return parts[0], kv(" · ".join(parts[1:]))


def kv(line):
    """«שעה: 16:00 · מעביר/ה: שלמה» → {שעה: "16:00", מעביר/ה: "שלמה"} — כל חלק הוא מפתח: ערך."""
    out = {}
    for p in line.split(" · "):
        if p.strip():
            k, _, v = p.partition(":")
            out[k.strip()] = v.strip()
    return out


def keyed(lines):
    """שורות «מפתח: ערך · מפתח: ערך» → מילון אחד."""
    out = {}
    for l in lines:
        out.update(kv(l))
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


def names_of(text):
    text = (text or "").strip()
    return [] if not text or text == "טרם" else [n.strip() for n in text.split(",") if n.strip()]


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_rows(path):
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def last_havurot():
    """החבורה של כל חניך מקובץ הנוכחות האחרון שיש בו חבורות."""
    for path in sorted((DATA / "attendance").glob("*.csv"), reverse=True):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            h = {r["שם"]: (r.get("חבורה") or "").strip() for r in csv.DictReader(fh)}
        if any(h.values()):
            return h
    return {}


def library_slot(group, day, tags):
    """(שעה, עוגן) של המשימה הקבועה של הקבוצה בסוג השבת הזה — כדי ששורת ה-override תחליף אותה."""
    for r in bw.read_csv("task_library.csv"):
        if r["קבוצה"] == group and r["יום"] == day and bw.applies(r.get("תנאי"), tags):
            return r["שעה"], r["עוגן"]
    return "", ""


def build(msg, warn):
    sec = msg["sections"]
    date = msg["date"]
    students = roster.read_students()
    names = [s["שם"] for s in students]
    program = {s["שם"]: s.get("תוכנית", "") for s in students}
    info = bw.read_shabbat(date)
    staff = [x for x in info.get("אנשי צוות", "").split(";") if x]
    if not staff:
        warn("{} אינו ברשימת השבתות שסגרנו (data/shabbatot.csv)".format(date))
    if not msg["v2"]:
        warn("טופס בגרסה הקודמת — בלי טיש, חבורות, סעודה שלישית כאירוע, ניקיונות לפי סוג השבת. "
             "כדאי לבקש מהאחראים למלא בקישור החדש")
    if msg["shared"] and msg["ovens"] not in (bw.OVENS_EARLY, bw.OVENS_LATE):
        warn("שבת משותפת בלי חלון תנורים — נחשבת «תנורים כל היום» (מסדרים את בית המדרש, מנקים את שניהם)")

    def who(raw):
        name, how = roster.match_name(raw, names)
        if name is None:
            warn("לא זוהה ברשימה: «{}»".format(raw))
        return name

    def staff_member(raw, what):
        raw = (raw or "").strip()
        if not raw or raw == "טרם":
            warn("עוד לא נקבע מי מעביר את ה{}".format(what))
            return ""
        if staff and raw not in staff:
            warn("«{}» מעביר/ה את ה{} — לא מאנשי הצוות שרשומים לשבת ({})".format(raw, what, ", ".join(staff)))
        return raw

    def clock(raw, what):
        raw = (raw or "").strip()
        if raw and not TIME.match(raw):
            warn("שעה לא ברורה ל{}: «{}» — נשארת ברירת המחדל".format(what, raw))
            return ""
        return raw

    # --- לו"ז: מי מעביר, אירועים אופציונליים, מקומות --------------------------------
    sched = []
    def event(day, name, place="", when="", note=""):
        sched.append({"יום": day, "אירוע": name, "מקום": place, "בסיס": "קבוע" if when else "",
                      "היסט": when, "עיגול": "", "הערה": note, "פעולה": "", "מקור": FORM})

    tish = keyed(sec.get("טיש", []))
    tish_by = staff_member(tish.get("מעביר/ה"), "טיש")
    if tish_by and tish.get("סגרנו") != "כן":
        warn("הטיש עוד לא נסגר עם {}".format(tish_by))
    if tish_by:
        event("שישי", "טיש", note="מעביר/ה: " + tish_by)

    havurot = [n for n in (who(x) for x in names_of(keyed(sec.get("חבורות", [])).get("מעבירים"))) if n]
    if not havurot:
        warn("מעבירי החבורות עוד לא נקבעו")
    elif len(havurot) < 2:
        warn("רק מעביר/ה אחד/ת לחבורות — צריך 2–3")
    if havurot:
        event("שבת", "חבורות", note="מעבירים: " + ", ".join(havurot))

    if "שיעור" in sec:
        s = keyed(sec["שיעור"])
        by, when = staff_member(s.get("מעביר/ה"), "שיעור"), clock(s.get("שעה"), "השיעור")
        if by and s.get("סגרנו") != "כן":
            warn("השיעור עוד לא נסגר עם {}".format(by))
        if when:
            event("שבת", "שיעור של " + by if by else "שיעור", place=s.get("מקום") or "בית המדרש", when=when)
        else:
            warn("שיעור בלי שעה — לא נכנס ללו\"ז")

    def optional(section, day, name, people_key):
        s = keyed(sec.get(section, []))
        on = s.get("קורה") == "כן" or (section == "סעודה שלישית" and not msg["v2"])
        if on:
            people = [who(x) or x for x in names_of(s.get(people_key))]
            note = " · ".join(x for x in (s.get("מה", ""), (people_key + ": " + ", ".join(people)) if people else "") if x)
            event(day, name, when=clock(s.get("שעה"), name), note=note)
        return on
    seuda = optional("סעודה שלישית", "שבת", "סעודה שלישית", "מעבירים")
    optional("ערב חברה", "שישי", "ערב חברה", "מכינים")

    if msg["shared"]:
        places = keyed([])
        for line in sec.get("מקומות", []):
            d = kv(line)
            for event_name in ("קבלת שבת ישראלית", "סעודת שבת"):
                if event_name in d:
                    places[event_name] = (d[event_name], clock(d.get("שעה"), event_name))
        for event_name, (place, when) in places.items():
            if place or when:
                event("שישי", event_name, place=place, when=when)
        if not places.get("קבלת שבת ישראלית", ("", ""))[0]:
            warn("לא נכתב איפה קבלת שבת ישראלית — לתאם עם שנה א'")

    # --- נוכחות --------------------------------------------------------------
    out = {who(n) for n in sec.get("לא בשבת", [])} - {None}
    nofri = {}
    for line in sec.get("לא בשישי", []):
        name = line.split(" · ", 1)[0].strip()
        n = who(name)
        if n:
            nofri[n] = line.split(" · ", 1)[1].strip() if " · " in line else ""
    leave = {who(n) for n in sec.get('עוזבים לפני מוצ"ש', [])} - {None}
    for raw in sec.get("לא ברשימה", []):
        if roster.match_name(raw, names)[0] is None:
            warn("«{}» לא ברשימת החניכים — מוסיפים ל-data/students.csv ומריצים שוב".format(raw))
    havurot_all = last_havurot()
    present = [n for n in names if n not in out]
    for n in havurot:
        if n in out:
            warn("{} מעביר/ה חבורה אבל מסומן/ת «לא בשבת»".format(n))
    att = []
    for n in present:
        blocked = FRIDAY if n in nofri else (MOTZASH if n in leave else "")
        note = ("לא בשישי" + (" — " + nofri[n] if nofri.get(n) else "")) if n in nofri else \
               ("עוזב/ת לפני מוצ\"ש" if n in leave else "")
        if n in havurot:
            note = " · ".join(x for x in (note, "מעביר/ה חבורה") if x)
        att.append({"שם": n, "תוכנית": program.get(n, ""), "חבורה": havurot_all.get(n, ""), "זמין לתורנות": "כן",
                    "לא זמין בשלב": blocked, "לא בקבוצה": HAVURA_BLOCK if n in havurot else "",
                    "צוות שבת": "", "שיבוץ ידני": "", "אחראי על": "", "הערה": note})

    # --- הכנות ----------------------------------------------------------------
    recipes = recipes_of(sec)
    library = {r["מנה"].strip() for r in bw.recipe_rows() if (r.get("מנה") or "").strip()}
    known = library | set(recipes)
    friday_ok = set(present) - set(nofri)
    tags = bw.tags_for(msg["shared"], msg["ovens"])
    groups = {r["קבוצה"]: r for r in bw.read_csv("group_plan.csv")}

    def lead(name, group):
        if not name:
            return ""
        n = who(name)
        if n and n not in friday_ok:
            warn("{} אחראי/ת על «{}» אבל לא בשישי בבוקר".format(n, group))
        return n or ""

    def dish(name):
        """שם מנה (הכנה או סלט) → המתכון: זהה, ואחרת כמו בטופס — הכלה יחידה בספרייה."""
        name = (name or "").strip()
        if name in known:
            return name
        return bw.match_recipe(name, library) or bw.match_recipe(name, known) or ""

    def exact(name):
        """תיאור חופשי של ארוחה («שקשוקה ולחם») — רק מתכון בשם הזה בדיוק."""
        name = (name or "").strip()
        return name if name in known else ""

    preps, kinds = [], {}
    def prep(**row):
        preps.append({k: row.get(k, "") for k in PREP_FIELDS})

    for line in sec.get("הכנות", []):
        name, d = fields(line)
        if not d.get("אנשים", "").isdigit() or int(d["אנשים"]) < 1:
            warn("ל«{}» חסר כמה אנשים".format(name))
        prep(הכנה=name, שעה="-60" if name.startswith("חלות") else "", כמות=d.get("כמה", ""),
             אנשים=d.get("אנשים", ""), אחראי=lead(d.get("אחראי", ""), name), עזרה=d.get("עזרה", ""),
             מתכון=dish(name), הערה=d.get("הערה", ""))
    for line in sec.get("ארוחת צהריים שישי", []):
        d = kv(line)
        prep(הכנה=bw.FRIDAY_LUNCH, כמות=d.get("מה", ""), אנשים=d.get("אנשים", "2"),
             אחראי=lead(d.get("אחראי", ""), bw.FRIDAY_LUNCH), מתכון=exact(d.get("מה", "")))
        kinds[d.get("מה", "")] = "ארוחת צהריים שישי"

    cleaning = keyed(sec.get("ניקיונות", [])) if msg["v2"] else keyed(sec.get('מוצ"ש', []))
    for key, (group, day) in CLEANING.items():
        n = cleaning.get(key, "")
        if not n or n == DEFAULT_CLEANERS:
            continue
        if not bw.applies(groups.get(group, {}).get("תנאי"), tags):
            warn("«{}: {}» — אין את הניקיון הזה בסוג השבת הזו; לא נכנס".format(key, n))
            continue
        if not n.isdigit() or int(n) < 1:
            warn("«{}: {}» — צריך מספר גדול מ-0; נשאר {}".format(key, n, DEFAULT_CLEANERS))
            continue
        hour, anchor = library_slot(group, day, tags)
        prep(הכנה=group, יום=day, שעה=hour, עוגן=anchor, אנשים=n)
    motz = keyed(sec.get('מוצ"ש', []))
    if motz.get("ארוחת ערב"):
        prep(הכנה=MOTZASH_DINNER, יום="מוצאי שבת", משימה="הכנת ארוחת ערב: " + motz["ארוחת ערב"], אנשים="5",
             מתכון=exact(motz["ארוחת ערב"]))
        kinds[motz["ארוחת ערב"]] = "בישול"

    # --- תפריט ----------------------------------------------------------------
    menu = []
    def add(meal, text, split=True, match=False):
        items = [x.strip() for x in text.split(",")] if split else [text.strip()]
        for x in items:
            if x:
                menu.append({"ארוחה": meal, "מנה": (dish(x) or x) if match else x, "כמות": "", "הערה": ""})
    cat = keyed(sec.get("קייטרינג", []))
    cat.setdefault("סלטי קייטרינג", cat.get("סלטים", ""))
    for key, meal in (("ארוחת ערב", "ארוחת ערב"), ("ארוחת צהריים", "ארוחת צהריים"), ("סלטי קייטרינג", "סלטים")):
        add(meal, cat.get(key, ""))
        if not cat.get(key):
            warn("אין קייטרינג ל«{}» — לבדוק מול המטבח".format(key))
    fresh = keyed(sec.get("סלטים לפני הארוחה", []))
    for key, meal in (("לערב", "סלטים לערב"), ("לצהריים", "סלטים לצהריים")):
        add(meal, fresh.get(key, ""), match=True)
        if msg["v2"] and not names_of(fresh.get(key)):
            warn("אין סלטים {} בטופס — המשימה תחזור לברירת המחדל (סלט כרוב וסלט טחינה)".format(key))
        for x in names_of(fresh.get(key)):
            kinds.setdefault(x, "סלטים")
            if not dish(x):
                warn("אין מתכון ל«{}» — הפלייר של תורני הארוחה יוצג בלי המצרכים שלו".format(x))
    frm = keyed(sec.get("מההכנות", []))                 # רק בהודעה בגרסה הקודמת
    add("מההכנות לערב", frm.get("לערב", ""), split=False)
    add("מההכנות לצהריים", frm.get("לצהריים", ""), split=False)
    cakes = keyed(sec.get("עוגות", []))
    for k in ("טיש", "קידוש", "סעודה שלישית"):
        if k == "סעודה שלישית" and cakes.get(k) and not seuda:
            warn("יש עוגות לסעודה שלישית, אבל אין סעודה שלישית — לא נכנס")
            continue
        add(k, cakes.get(k, ""), split=False)

    qty = {p["הכנה"]: p["כמות"] for p in preps}
    return att, preps, menu, recipes, sched, {"kinds": kinds, "qty": qty}


def main():
    ap = argparse.ArgumentParser(description="קליטת טופס השבת")
    ap.add_argument("--file", help="קובץ ההודעה (ברירת מחדל: stdin)")
    ap.add_argument("--dry-run", action="store_true", help="רק להציג, בלי לכתוב")
    args = ap.parse_args()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    msg = parse(text)
    warnings = []
    att, preps, menu, recipes, sched, extra = build(msg, warnings.append)
    date, iso = msg["date"], msg["date"].isoformat()

    print("טופס שבת {} · מילא/ה: {} · שנה א': {}{}".format(
        iso, msg["filler"] or "—", "כן" if msg["shared"] else "לא",
        " · תנורים " + msg["ovens"] if msg["ovens"] else ""))
    print("  {} נוכחים · {} לא בשישי · {} עוזבים לפני מוצ\"ש".format(
        len(att), sum(r["לא זמין בשלב"] == FRIDAY for r in att), sum(r["לא זמין בשלב"] == MOTZASH for r in att)))
    for p in preps:
        print("  · {:<22} {:<16} {} אנשים{}{}".format(p["הכנה"], p["כמות"] or p["משימה"][:16], p["אנשים"],
              " · אחראי: " + p["אחראי"] if p["אחראי"] else "", " · עזרה: " + p["עזרה"] if p["עזרה"] else ""))
    for s in sched:
        print("  ◷ {} {}{}{}".format(s["יום"], s["אירוע"], " " + s["היסט"] if s["היסט"] else "",
                                    " — " + " · ".join(x for x in (s["מקום"], s["הערה"]) if x) if s["מקום"] or s["הערה"] else ""))
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

    path = DATA / "schedule" / "{}.csv".format(iso)
    old, _ = read_rows(path)
    manual = [r for r in old if (r.get("מקור") or "").strip() != FORM]
    if old:
        print("  (הלו\"ז של השבוע קיים — {} שורות ידניות נשמרות, שורות הטופס מוחלפות)".format(len(manual)))
    write_csv(path, sched + manual, SCHED_FIELDS)             # הידניות אחרונות — הן גוברות

    weeks, header = read_rows(DATA / "weeks.csv")
    weeks = [w for w in weeks if w.get("תאריך") != iso] + [
        {"תאריך": iso, "שבת משותפת": "כן" if msg["shared"] else "לא", "תנורים": msg["ovens"],
         "הערה": "מילא/ה: " + msg["filler"]}]
    write_csv(DATA / "weeks.csv", sorted(weeks, key=lambda w: w["תאריך"]),
              list(dict.fromkeys(header + WEEK_FIELDS)))

    wpath = DATA / "recipes" / "{}.csv".format(iso)
    prev = {r["מנה"]: r for r in read_rows(wpath)[0]}      # ייבוא קודם של אותה שבת, אם היה
    base = bw.read_csv("recipes.csv")
    by_name = {r["מנה"]: r for r in base}
    week = []
    for dish, (ing, steps) in recipes.items():
        old = by_name.get(dish, {})
        row = {"קטגוריה": old.get("קטגוריה") or extra["kinds"].get(dish, ""), "מנה": dish,
               "כמות": extra["qty"].get(dish) or old.get("כמות", ""), "מרכיבים": ing or old.get("מרכיבים", ""),
               "הוראות": steps or old.get("הוראות", ""), "הערה": old.get("הערה", "")}
        week.append(row)
        if dish not in by_name:                        # מנה חדשה — גם לספרייה, לשבתות הבאות
            base.append(row)
        elif dish in prev and all((old.get(k) or "") == (prev[dish].get(k) or "") for k in bw.RECIPE_FIELDS):
            old.update(row)                            # נכנסה לספרייה בייבוא הקודם של השבת הזו — מתקנים
        print("  + מתכון: {}{}".format(dish, "" if dish not in by_name else " (הגרסה של השבוע)"))
    if week or prev:
        write_csv(wpath, week, bw.RECIPE_FIELDS)       # ייבוא חוזר בלי מתכונים מנקה את הגרסה הקודמת
    if recipes:
        write_csv(DATA / "recipes.csv", base, bw.RECIPE_FIELDS)
    print("\nנכתב. הבא: python3 tools/shabbat.py {}".format(iso))


if __name__ == "__main__":
    main()
