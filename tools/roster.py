# -*- coding: utf-8 -*-
"""קריאת רשימת החניכים מתיקיית data/ ונרמולה ל-data/students.csv.

מזהה אוטומטית כל קובץ .xlsx/.csv ששמו מכיל "חניכ" או "students" (למשל ייצוא של
טופס גוגל), לוקח את עמודת השמות ומייצר רשימה נקייה. אם אין קובץ — נוצרים
placeholders, כדי שהמערכת תמשיך לעבוד עד שהרשימה האמיתית תגיע.

    python3 tools/roster.py
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "students.csv"
HEADERS = ["שם", "קבוצה קבועה", "הערה"]
PLACEHOLDER_COUNT = 40

NAME_HINTS = ("שם", "name", "חניך")
SKIP_HINTS = ("חותמת", "timestamp", "מייל", "email", "טלפון", "phone")


def _source_files():
    pattern = re.compile(r"(חניכ|students|רשימ)", re.UNICODE)
    return sorted(p for p in DATA.glob("*")
                  if p.suffix.lower() in (".xlsx", ".xlsm", ".csv")
                  and p.name != OUT.name and pattern.search(p.stem))


def _pick_name_column(header, rows):
    """עמודת השמות: לפי כותרת אם אפשר, אחרת העמודה עם הכי הרבה ערכי טקסט."""
    for i, title in enumerate(header):
        t = str(title or "").strip().lower()
        if any(h in t for h in NAME_HINTS) and not any(s in t for s in SKIP_HINTS):
            return i
    best, best_score = 0, -1
    for i in range(len(header)):
        score = sum(1 for r in rows if i < len(r) and isinstance(r[i], str) and r[i].strip())
        if score > best_score:
            best, best_score = i, score
    return best


def _read_rows(path):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        return (rows[0] if rows else []), rows[1:]
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return (rows[0] if rows else []), rows[1:]


def load_names():
    for path in _source_files():
        try:
            header, rows = _read_rows(path)
        except Exception as exc:                       # קובץ פגום/נעול — ננסה את הבא
            print("דילוג על {}: {}".format(path.name, exc))
            continue
        if not rows:
            continue
        col = _pick_name_column(header, rows)
        names, seen = [], set()
        for row in rows:
            value = row[col] if col < len(row) else None
            name = " ".join(str(value).split()) if value else ""
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        if names:
            return names, path.name
    return ["חניך {}".format(i) for i in range(1, PLACEHOLDER_COUNT + 1)], None


def read_students():
    """הרשימה המנורמלת כ-[{שם, קבוצה קבועה, הערה}], אחרי שהורצה main()."""
    if not OUT.exists():
        main()
    with OUT.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    names, source = load_names()
    existing = {}
    if OUT.exists():                                   # שימור נעילות והערות קיימות
        with OUT.open(encoding="utf-8-sig", newline="") as fh:
            existing = {r["שם"]: r for r in csv.DictReader(fh)}

    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        for name in names:
            prev = existing.get(name, {})
            writer.writerow({"שם": name,
                             "קבוצה קבועה": prev.get("קבוצה קבועה", ""),
                             "הערה": prev.get("הערה", "")})

    print("{} חניכים ← {} (מקור: {})".format(
        len(names), OUT.relative_to(ROOT), source or "placeholder"))
    return names


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
