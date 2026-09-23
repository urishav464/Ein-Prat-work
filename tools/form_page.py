# -*- coding: utf-8 -*-
"""בונה את טופס השבת לאחראים — דף אחד (docs/index.html), שמתפרסם ב-GitHub Pages:
https://urishav464.github.io/Ein-Prat-work/

    python3 tools/form_page.py                              # → docs/index.html
    python3 tools/form_page.py --demo late --out X.html     # דף ממולא לדוגמה (separate|early|late)

הדף עצמו ב-tools/form_page.html; כאן מוטמעים בו רשימת החניכים (students.csv), השבתות
שסגרנו (shabbatot.csv — עם אנשי הצוות, הספר והלו"ז המחושב של כל שבת) ושמות המתכונים.
הדף מרכיב הודעה אחת, והיא נקראת ע"י tools/import_form.py. כשהרשימה או השבתות משתנות —
בונים מחדש ודוחפים ל-Shabbat, ו-Pages מתעדכן לבד.
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_workbook as bw
import roster

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "form_page.html"
OUT = ROOT / "docs" / "index.html"


def date_range(d):
    e = d + timedelta(days=1)
    return "{}-{}.{}".format(d.day, e.day, e.month) if d.month == e.month else \
        "{}.{}-{}.{}".format(d.day, d.month, e.day, e.month)


def staff_text(staff):
    if len(staff) >= 5:
        return "כל הצוות"
    return " ו".join([", ".join(staff[:-1]), staff[-1]]) if len(staff) > 1 else "".join(staff)


def week_times(d, candle, havdalah, shared=False, ovens=""):
    """{«יום|אירוע»: «HH:MM»} ללו"ז של השבת, כשכל האירועים האופציונליים דולקים."""
    week = {"preps": [], "menu": [], "schedule": [], "recipes": [], "shared": shared, "ovens": ovens,
            "info": bw.read_shabbat(d)}
    return {"{}|{}".format(r["יום"], r["אירוע"]): r["שעה"].strftime("%H:%M") if r["שעה"] else ""
            for r in bw.schedule_rows(d, candle, havdalah, optional=True, week=week)}


def page_data(demo=None):
    students = [{"name": s["שם"], "program": s.get("תוכנית") or ""} for s in roster.read_students()]
    zmanim = {z["תאריך"]: z for z in bw.read_zmanim()}
    dates = []
    for s in bw.read_csv("shabbatot.csv"):
        staff = [x.strip() for x in (s.get("אנשי צוות") or "").split(";") if x.strip()]
        if not staff:                                   # רק שבתות שסגרנו (עם אנשי צוות)
            continue
        d = date.fromisoformat(s["תאריך"].strip())
        z = zmanim.get(d)
        if z is None:
            print("⚠ {} לא בלוח הזמנים — לא נכנס לטופס".format(d))
            continue
        c, h = bw.as_time(z["כניסת שבת"]), bw.as_time(z["צאת שבת"])
        times = week_times(d, c, h)
        late = week_times(d, c, h, shared=True, ovens=bw.OVENS_LATE)
        title = (s.get("שם") or "").strip()
        label = " · ".join(x for x in (title, date_range(d), z["פרשה"], staff_text(staff)) if x)
        dates.append({"iso": d.isoformat(), "parasha": z["פרשה"], "label": label, "title": title,
                      "range": date_range(d), "staff": staff, "staffText": staff_text(staff),
                      "book": (s.get("ספר") or "").strip(), "times": times,
                      "start": {"normal": times.get("שישי|תחילת עבודה", ""),
                                "late": late.get("שישי|תחילת עבודה", "")}})
    dishes = [r["מנה"].strip() for r in bw.recipe_rows() if (r.get("מנה") or "").strip()]
    data = {"students": students, "dates": dates, "dishes": dishes, "demo": None}
    if demo:
        upcoming = [d for d in dates if d["iso"] >= date.today().isoformat()]
        if not upcoming:
            raise SystemExit("אין שבת סגורה עתידית ב-shabbatot.csv — אין על מה להריץ דמו")
        data["demo"] = demo_state(students, demo, upcoming[0])
    return data


def demo_state(students, kind, shabbat):
    """מילוי לדוגמה לכל סוג שבת, על השבת הסגורה הקרובה — רק לבדיקה מקצה לקצה, לא בדף שמתפרסם."""
    names = [s["name"] for s in students]
    staff = shabbat["staff"]
    att = {n: "in" for n in names}
    for n in names[:6]:
        att[n] = "out"
    att[names[10]] = att[names[11]] = "nofri"
    att[names[20]] = "leave"
    state = {"date": shabbat["iso"], "filler": names[30], "att": att,
             "why": {names[10]: "שמירה בליל חמישי", names[11]: "מגיע ב-12:00"}, "extra": "",
             "preps": [
                 {"what": "חלות", "qty": '8 ק"ג קמח', "ppl": "4", "lead": names[31], "help": "6", "note": "",
                  "ing": "", "steps": ""},
                 {"what": "עוגת גזר", "qty": "6 תבניות", "ppl": "3", "lead": names[32], "help": "",
                  "note": "לסמן 2 תבניות לסעודה שלישית", "ing": "1 ק\"ג גזר\n6 ביצים\n2 כוסות קמח",
                  "steps": "מגררים את הגזר\nמערבבים הכול\nאופים 40 דקות ב-180"}],
             "lunch-what": "שקשוקה ולחם", "lunch-ppl": "3", "lunch-lead": names[33],
             "lunch-ing": "30 ביצים\n2 ק\"ג עגבניות", "lunch-steps": "מטגנים בצל\nמוסיפים עגבניות וביצים",
             "clean-fri": "12", "clean-bm": "12", "clean-ha": "12",
             "m-dinner": "שניצל, אורז, שעועית ירוקה", "m-lunch": "חמין, קוגל", "m-salads": "טחינה, חומוס, מטבוחה",
             "salads": {"eve": [{"name": "סלט כרוב מרענן", "ing": "", "steps": ""},
                                {"name": "סלט ירקות", "ing": "5 מלפפונים\n5 עגבניות", "steps": "חותכים דק"}],
                        "noon": [{"name": "סלט טחינה", "ing": "", "steps": ""}]},
             "m-tish": "3 תבניות עוגת גזר", "m-kiddush": "1 תבנית עוגת גזר", "m-seuda": "2 תבניות עוגת גזר",
             "tish-by": staff[-1], "tish-ok": "כן", "hav-1": names[40], "hav-2": names[41], "hav-3": "",
             "shiur": "לא", "seuda": "לא", "chevra": "לא",
             "pl-dinner": "חדר אוכל", "shiur-place": "בית המדרש", "chevra-what": "משחק, ולהביא משחקי קופסא לחדר האוכל",
             "z-dinner": "פסטה ברוטב עגבניות", "z-ing": "4 ק\"ג פסטה\n3 צנצנות רוטב", "z-steps": "מבשלים ומערבבים",
             "sched": "", "notes": ""}
    if kind == "separate":
        seuda = shabbat["times"].get("שבת|סעודה שלישית", "16:00")
        shiur = "{:02d}:{:02d}".format(*divmod(int(seuda[:2]) * 60 + int(seuda[3:]) - 75, 60))
        state.update({"shared": "לא", "shiur": "כן", "shiur-time": shiur, "shiur-by": staff[0], "shiur-ok": "כן",
                      "seuda": "כן", "seuda-what": "דבר תורה ושירה", "seuda-by-1": names[42]})
    elif kind == "early":
        state.update({"shared": "כן", "ovens": bw.OVENS_EARLY, "pl-kabbalat": "הדק של שנה א'",
                      "clean-ha": "10"})
    else:
        state.update({"shared": "כן", "ovens": bw.OVENS_LATE, "pl-kabbalat": "המצפה", "tm-kabbalat": "17:00",
                      "seuda": "כן", "seuda-what": "שירה", "seuda-time": "", "chevra": "כן",
                      "chevra-what": "משחק מחבואים, ולהביא משחקי קופסא", "chevra-by-1": names[43],
                      "tish-by": "__other", "tish-other": "אבישי", "tish-ok": "לא", "havurot-later": True,
                      "hav-1": "", "hav-2": "", "clean-fri": "10"})
    return state


def build(out, demo=None):
    data = json.dumps(page_data(demo), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="טופס השבת לאחראים")
    ap.add_argument("--demo", choices=["separate", "early", "late"], help="מילוי לדוגמה (לבדיקה)")
    ap.add_argument("--out", help="נתיב פלט (ברירת מחדל: docs/index.html)")
    args = ap.parse_args()
    out = build(Path(args.out) if args.out else OUT, args.demo)
    print("נכתב:", out)


if __name__ == "__main__":
    main()
