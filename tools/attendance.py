# -*- coding: utf-8 -*-
"""קליטת רשימת הנוכחים לשבת מסוימת.

מי נמצא משתנה בכל שבת, ולכן זו רשימה נפרדת לכל תאריך ולא תכונה של החניך.
הסקריפט קולט רשימה מודבקת (שם בכל שורה, מספור ותווי רשימה מותרים), מתאים כל
שם לשם הקנוני ב-data/students.csv ומדווח על מה שלא זוהה.

    python3 tools/attendance.py 2026-09-04 < names.txt
    python3 tools/attendance.py 2026-09-04 --file names.txt
    python3 tools/attendance.py 2026-09-04 --all          # כולם נוכחים
    python3 tools/attendance.py 2026-09-04 --show         # הצגת הרשימה הקיימת
"""
import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "attendance"
LINE_NOISE = re.compile(r"^\s*(?:[-•*]|\d+[.)]?)\s*")


def path_for(date):
    return DIR / "{}.csv".format(date.isoformat())


def _rows(date):
    path = path_for(date)
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("שם") or "").strip()]


def load(date):
    """שמות הנוכחים לתאריך, או None אם אין רשימה."""
    rows = _rows(date)
    return None if rows is None else [r["שם"] for r in rows]


def load_pins(date):
    """הצמדות ידניות של חניך לקבוצה בשבת הזו: {שם: קבוצה}."""
    rows = _rows(date)
    if rows is None:
        return {}
    return {r["שם"]: r["שיבוץ ידני"].strip() for r in rows
            if (r.get("שיבוץ ידני") or "").strip()}


def load_available(date):
    """רק מי שזמין לתורנות (עמודת «זמין לתורנות» = כן, או ריקה)."""
    rows = _rows(date)
    if rows is None:
        return None
    return [r["שם"] for r in rows if (r.get("זמין לתורנות") or "כן").strip() != "לא"]


def parse_names(text):
    names = []
    for line in text.splitlines():
        line = LINE_NOISE.sub("", line).strip().strip("*").strip()
        if not line or line.endswith(":") or line.startswith("#"):
            continue
        names.append(line)
    return names


def main():
    ap = argparse.ArgumentParser(description="רשימת נוכחים לשבת")
    ap.add_argument("date", help="תאריך יום שישי, למשל 2026-09-04")
    ap.add_argument("--file", help="קובץ טקסט עם שם בכל שורה (ברירת מחדל: stdin)")
    ap.add_argument("--all", action="store_true", help="כל החניכים נוכחים")
    ap.add_argument("--show", action="store_true", help="הצגת הרשימה הקיימת בלבד")
    args = ap.parse_args()

    date = datetime.strptime(args.date, "%Y-%m-%d").date()
    students = roster.read_students()
    all_names = [s["שם"] for s in students]
    program = {s["שם"]: s.get("תוכנית", "") for s in students}

    if args.show:
        present = load(date)
        if present is None:
            raise SystemExit("אין רשימת נוכחות ל-{}".format(args.date))
        print("{} נוכחים בשבת {}".format(len(present), date.strftime("%d/%m/%Y")))
        for name in present:
            print("   {:<26} {}".format(name, program.get(name, "")))
        return

    if args.all:
        matched, unknown = list(all_names), []
    else:
        text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        matched, unknown, seen = [], [], set()
        for raw in parse_names(text):
            name, how = roster.match_name(raw, all_names)
            if name is None:
                unknown.append(raw)
            elif name not in seen:
                seen.add(name)
                matched.append(name)
                if how != "מדויק":
                    print("  התאמה [{}]: «{}» ← {}".format(how, raw, name))

    DIR.mkdir(parents=True, exist_ok=True)
    with path_for(date).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["שם", "תוכנית"])
        writer.writeheader()
        for name in matched:
            writer.writerow({"שם": name, "תוכנית": program.get(name, "")})

    absent = [n for n in all_names if n not in matched]
    counts = {}
    for name in matched:
        counts[program.get(name, "")] = counts.get(program.get(name, ""), 0) + 1

    print("\nשבת {}: {} נוכחים ({})".format(
        date.strftime("%d/%m/%Y"), len(matched),
        ", ".join("{} {}".format(v, k) for k, v in sorted(counts.items()))))
    if unknown:
        print("\n⚠ שמות שלא זוהו ({}) — הוסיפו אותם לרשימת החניכים:".format(len(unknown)))
        for u in unknown:
            print("   -", u)
    if absent:
        print("\nלא נוכחים השבת ({}):".format(len(absent)))
        print("   " + ", ".join(absent))
    print("\nנכתב אל {}".format(path_for(date).relative_to(ROOT)))


if __name__ == "__main__":
    main()
