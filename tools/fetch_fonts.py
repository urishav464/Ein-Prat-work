# -*- coding: utf-8 -*-
"""הורדת פונטים עבריים מ-Google Fonts אל assets/fonts/ (פעם אחת).

הפונטים מוטמעים בפליירים כ-data URI, כך שהפקת ה-PDF לא תלויה ברשת.
רישיון: SIL Open Font License 1.1 — ראו assets/fonts/OFL.txt

    python3 tools/fetch_fonts.py
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "fonts"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
FAMILIES = ["Heebo:wght@400;500;700", "Rubik:wght@500;700"]
WANTED = ("hebrew", "latin")          # תת-הקבוצות שמעניינות אותנו


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved = []
    for spec in FAMILIES:
        family = spec.split(":")[0]
        css = get("https://fonts.googleapis.com/css2?family={}&display=swap".format(spec)).decode()
        blocks = re.split(r"/\*\s*([a-z\-]+)\s*\*/", css)
        for subset, block in zip(blocks[1::2], blocks[2::2]):
            if subset not in WANTED:
                continue
            weight = re.search(r"font-weight:\s*(\d+)", block)
            url = re.search(r"src:\s*url\((https://[^)]+\.woff2)\)", block)
            if not (weight and url):
                continue
            # Heebo ו-Rubik הם פונטים משתנים: אותו קובץ משרת את כל המשקלים,
            # ולכן שומרים קובץ אחד לכל (משפחה, תת-קבוצה).
            name = "{}-{}.woff2".format(family, subset)
            path = OUT / name
            if not path.exists():
                path.write_bytes(get(url.group(1)))
                saved.append((name, path.stat().st_size))
            elif name not in [n for n, _ in saved]:
                saved.append((name, path.stat().st_size))

    license_path = OUT / "OFL.txt"
    if not license_path.exists():
        license_path.write_text(
            "Heebo ו-Rubik מופצים תחת SIL Open Font License 1.1.\n"
            "https://openfontlicense.org/\n"
            "מקור: https://fonts.google.com/\n", encoding="utf-8")

    for name, size in saved:
        print("  {:<28} {:>7,} bytes".format(name, size))
    print("{} קבצים ← {}".format(len(saved), OUT.relative_to(ROOT)))
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
