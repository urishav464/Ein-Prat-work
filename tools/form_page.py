# -*- coding: utf-8 -*-
"""בונה את טופס השבת לאחראים — דף אחד (docs/טופס שבת.html) שמתפרסם כ-Artifact.

    python3 tools/form_page.py                    # → docs/טופס שבת.html
    python3 tools/form_page.py --demo --out X.html  # דף עם נתוני דוגמה ממולאים (לבדיקה)

הדף עצמו ב-tools/form_page.html; כאן מוטמעים בו רשימת החניכים (students.csv), ימי השישי
הקרובים (zmanim.csv) ושמות מנות להשלמה (recipes.csv). הדף מרכיב הודעה אחת, והיא נקראת
ע"י tools/import_form.py. כשהרשימה משתנה — בונים מחדש ומפרסמים לאותו קישור.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_workbook as bw
import roster

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "form_page.html"
OUT = ROOT / "docs" / "טופס שבת.html"
COMMON_DISHES = ["חלות", "עוגות שמרים", "עוגת דבש", "עוגיות שוקולד צ'יפס", "בראוניז ללא גלוטן",
                 "מטבוחה", "סלט חצילים", "סלט כרוב", "חומוס"]


def page_data(demo=False):
    students = [{"name": s["שם"], "program": s.get("תוכנית") or ""} for s in roster.read_students()]
    dates = []
    for r in bw.read_csv("zmanim.csv"):
        d = datetime.strptime(r["תאריך"], "%d/%m/%Y").date()
        dates.append({"iso": d.isoformat(), "parasha": r["פרשה"], "label": "שבת {}-{}.{} · {}".format(
            d.day, (d + timedelta(days=1)).day, d.month, r["פרשה"])})
    dishes = list(dict.fromkeys(COMMON_DISHES + [r["מנה"] for r in bw.read_csv("recipes.csv")]))
    data = {"students": students, "dates": dates, "dishes": dishes, "demo": None}
    if demo:
        data["demo"] = demo_state(students, dates)
    return data


def demo_state(students, dates):
    """מילוי לדוגמה — רק לבדיקה מקצה לקצה, לא בדף שמתפרסם."""
    names = [s["name"] for s in students]
    att = {n: "in" for n in names}
    for n in names[:6]:
        att[n] = "out"
    att[names[10]] = att[names[11]] = "nofri"
    att[names[20]] = "leave"
    return {"date": "2026-10-16", "shared": "לא", "filler": names[30], "att": att,
            "why": {names[10]: "שמירה בליל חמישי", names[11]: "מגיע ב-12:00"},
            "extra": "", "preps": [
                {"what": "חלות", "qty": '8 ק"ג קמח', "ppl": "4", "lead": names[31], "help": "6", "note": "",
                 "ing": "", "steps": ""},
                {"what": "עוגת גזר", "qty": "6 תבניות", "ppl": "3", "lead": names[32], "help": "",
                 "note": "לסמן 2 תבניות לסעודה שלישית", "ing": "1 ק\"ג גזר\n6 ביצים\n2 כוסות קמח",
                 "steps": "מגררים את הגזר\nמערבבים הכול\nאופים 40 דקות ב-180"},
            ],
            "lunch-what": "שקשוקה ולחם", "lunch-ppl": "3", "lunch-lead": names[33],
            "m-dinner": "שניצל, אורז, שעועית ירוקה", "m-lunch": "חמין, קוגל", "m-salads": "טחינה, חומוס, מטבוחה",
            "m-from-eve": "חצי מהחלות", "m-from-noon": "שאר החלות",
            "m-tish": "3 תבניות עוגת גזר", "m-kiddush": "1 תבנית עוגת גזר", "m-seuda": "2 תבניות עוגת גזר",
            "z-bm": "10", "z-ha": "12", "z-dinner": "פסטה ברוטב עגבניות",
            "sched": "השיעור של משה, 16:30", "notes": ""}


def build(out, demo=False):
    data = json.dumps(page_data(demo), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="טופס השבת לאחראים")
    ap.add_argument("--demo", action="store_true", help="מילוי לדוגמה (לבדיקה)")
    ap.add_argument("--out", help="נתיב פלט (ברירת מחדל: docs/טופס שבת.html)")
    args = ap.parse_args()
    out = build(Path(args.out) if args.out else OUT, args.demo)
    print("נכתב:", out)


if __name__ == "__main__":
    main()
