# -*- coding: utf-8 -*-
"""מדריך לאחראי השבת — עמוד אחד (PDF + PNG) בעיצוב של הפליירים.

    python3 tools/guide.py            # → docs/מדריך לאחראי שבת.pdf|png

מה החניכים האחראים בודקים במהלך השבוע, ומה הם שולחים. הטופס עצמו — «טופס שבת.md».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_pdf as ep

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"

SECTIONS = [                       # בסדר הקריאה: 1 | 2, אחר כך 3 לרוחב, ואז 4 | 5
    ('1', 'מי בשבת', [
        'רשימה של <b>כל מי שנשאר</b> לשבת',
        'מי <b>לא בשישי בבוקר</b> (שמירה בליל חמישי, מגיעים מאוחר) — ולמה',
        'מי <b>עוזב לפני מוצ"ש</b>',
        "האם <b>שנה א'</b> איתנו בשבת?",
    ]),
    ('2', 'לו"ז', [
        '<b>רק שינויים</b>: מי מעביר שיעור, אירוע שזז, נוסף או בוטל',
        'השעות לפי כניסת השבת מחושבות לבד',
    ]),
    ('3', 'הכנות שישי — אתם מחליטים', [
        '<b>מה מכינים</b>: חלות, עוגות, סלטים, מטבוחה…',
        'לכל הכנה: <b>כמה</b> (ק"ג קמח, תבניות, יחידות), <b>כמה אנשים</b> צריך, ו<b>מי אחראי/ת</b>',
        'חלות מתחילות ב-7:00, כל השאר ב-8:00',
        'צריך <b>עזרה מבית המדרש</b> ב-10:00? לאיזו הכנה וכמה אנשים',
        '<b>ארוחת צהריים שישי</b>: מה מבשלים',
        'לוודא שיש <b>את כל המצרכים</b> במטבח',
        'מתכון — בונוס, אם יש',
    ]),
    ('4', 'מה מוגש בשבת', [
        'מהמטבח: מה מגיע בקייטרינג ל<b>ארוחת ערב</b>, ל<b>צהריים</b>, ואילו <b>סלטים</b>',
        'מה מההכנות יוצא לארוחת הערב ומה לצהריים',
        '<b>חלוקת העוגות</b>: כמה לטיש, כמה לקידוש, כמה לסעודה שלישית',
    ]),
    ('5', 'מוצ"ש', [
        'ניקיון <b>בית המדרש</b> ו<b>חדר האוכל</b> — 12 בכל אחד, אלא אם צריך אחרת',
        '<b>ארוחת ערב</b> — 5 מכינים: מה מבשלים',
    ]),
]
WIDE = "3"

CSS = """
.sheet{padding:14mm 14mm 12mm}
h1{font-size:26pt}
.sub{text-align:center;font-size:12pt;color:#5A6572;margin-top:2mm}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-top:8mm}
.card{border:1px solid #1F2430;padding:4mm 5mm 3.5mm;break-inside:avoid}
.card.wide{grid-column:1 / -1}
.card h2{font-family:'Rubik',sans-serif;font-size:14pt;display:flex;align-items:center;gap:2.5mm;margin-bottom:2mm}
.card h2 span{display:inline-flex;align-items:center;justify-content:center;width:7mm;height:7mm;
  border-radius:50%;background:#1F2430;color:#fff;font-size:10.5pt}
.card ul{list-style:none;padding:0}
.card li{font-size:11pt;line-height:1.5;padding:.8mm 0 .8mm 0;padding-right:5.5mm;position:relative}
.card li:before{content:'';position:absolute;right:0;top:2.6mm;width:3mm;height:3mm;border:1.3px solid #1F2430;border-radius:.6mm}
.send{margin-top:6mm;border:2px solid #1F2430;background:#F1F3F6;padding:4mm 6mm;text-align:center;font-size:12pt;line-height:1.6}
.send b{font-family:'Rubik',sans-serif}
.auto{margin-top:4mm;text-align:center;font-size:10pt;color:#5A6572;line-height:1.5}
"""


def guide_html():
    cards = []
    for num, title, items in SECTIONS:
        cls = " wide" if num == WIDE else ""
        cards.append('<div class="card{}"><h2><span>{}</span>{}</h2><ul>{}</ul></div>'.format(
            cls, num, title, "".join("<li>{}</li>".format(x) for x in items)))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}</style></head><body><div class="sheet">
<h1>מדריך לאחראי השבת</h1>
<div class="sub">מה בודקים במהלך השבוע — ומה שולחים לאורי</div>
<div class="grid">{cards}</div>
<div class="send">שולחים לאורי את <b>«טופס שבת»</b> מלא <b>עד שבוע לפני השבת</b> — הכנות, תפריט, מוצ"ש ורשימת הנוכחים.<br>
משם יוצאים לבד: <b>פלייר לכל תורנות</b>, <b>לו"ז צל</b> ושיבוץ השמות.</div>
<div class="auto">לא צריך לדאוג ל: צוות שבת · תורני ארוחות, טיש וקידוש · סידור בית המדרש בבוקר ·
מי עושה כמה — המערכת משבצת לפי הניקוד ומאזנת מול השבתות הקודמות.</div>
<footer>מדרשת עין פרת</footer>
</div></body></html>""".format(fonts=ep.font_face_css(), base=ep.BASE_CSS, css=CSS, cards="".join(cards))


def main():
    OUT.mkdir(exist_ok=True)
    pdf, png = OUT / "מדריך לאחראי שבת.pdf", OUT / "מדריך לאחראי שבת.png"
    pages = ep.render(guide_html(), pdf, png)
    print("{} ({} עמוד/ים)\n{}".format(pdf.relative_to(ROOT), pages, png.relative_to(ROOT)))


if __name__ == "__main__":
    main()
