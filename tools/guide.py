# -*- coding: utf-8 -*-
"""מדריך לאחראי השבת — עמוד A4 אחד (PDF + PNG) בעיצוב של הפליירים.

    python3 tools/guide.py            # → docs/מדריך לאחראי שבת.pdf|png

שישה כרטיסים של מה שהחניכים האחראים סוגרים במהלך השבוע — 1 | 2, 3 לרוחב, 4 | 5, 6 לרוחב —
ומתחתם מה שולחים לאורי ומה המערכת עושה לבד. הטופס עצמו — docs/index.html ב-GitHub Pages (tools/form_page.py).

הדף חייב להיות עמוד אחד: מעבר --dump-dom מודד קודם כמה התוכן גבוה מהעמוד (הסקריפט כותב את
היחס ל-document.title), והיחס נאפה ל-transform: scale על ‎.inner — לא מתחת ל-MIN_FIT.
אם בכל זאת לא יוצא עמוד אחד, יוצאים בשגיאה והקבצים הקודמים ב-docs/ נשארים כמו שהם.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_pdf as ep

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"

SECTIONS = [                       # בסדר הקריאה: 1 | 2, אחר כך 3 לרוחב, 4 | 5, ואז 6 לרוחב
    ('1', 'מי בשבת', [
        'רשימה של <b>כל מי שנשאר</b> לשבת',
        'מי <b>לא בשישי בבוקר</b> (שמירה בליל חמישי, מגיעים מאוחר) — ולמה',
        'מי <b>עוזב לפני מוצ"ש</b>',
        "האם <b>שנה א'</b> איתנו בשבת?",
    ]),
    ('2', 'לו"ז — מה אתם סוגרים', [
        '<b>הטיש</b>: אחד מאנשי הצוות שבקמפוס מעביר — סוגרים איתו/ה מראש',
        '<b>חבורות</b> אחרי הקידוש: 2–3 חניכים שמעבירים',
        '<b>שיעור בצהריים</b> (לא חובה): שעה, ואיש צוות שמעביר',
        '<b>סעודה שלישית</b> (לא חובה): מה עושים, מי מעביר, ועוגות',
        '<b>ערב חברה</b> אחרי הטיש (לא חובה): משחק, ומשחקי קופסא לחדר האוכל',
        'השעות מחושבות לבד מכניסת השבת (הארוחה לא לפני 19:00)',
    ]),
    ('3', 'הכנות שישי — אתם מחליטים', [
        '<b>מה מכינים</b>: חלות, עוגות, סלטים, מטבוחה…',
        'לכל הכנה: <b>כמה</b> (ק"ג קמח, תבניות, יחידות), <b>כמה אנשים</b> צריך, ו<b>מי אחראי/ת</b>',
        'מתחילים ב-8:00 — וכשהתנורים שלנו מ-11:00, ב-11:00. החלות שעה לפני כולם',
        'צריך <b>עזרה</b> מתורנות שישי? לאיזו הכנה וכמה אנשים',
        '<b>ארוחת צהריים שישי</b>: מה מבשלים, ומתכון',
        'לוודא שיש <b>את כל המצרכים</b> במטבח · מתכון — בונוס, אם יש',
    ]),
    ('4', 'מה מוגש בשבת', [
        '<b>קייטרינג</b> לארוחת ערב ולצהריים, ו<b>סלטי קייטרינג</b> — שואלים במטבח',
        '<b>סלטים שמכינים לפני הארוחה</b> (ערב וצהריים): אילו, ומתכון',
        '<b>חלוקת העוגות</b>: טיש, קידוש, סעודה שלישית',
    ]),
    ('5', 'מוצ"ש', [
        '<b>ניקיונות</b> 20 דקות אחרי צאת שבת — 12 בכל מקום שעלינו',
        '<b>ארוחת ערב</b> שעה ורבע אחר כך — 5 מכינים: מה מבשלים, ומתכון',
        '<b>כריכה לכריכה</b> בתנ"ך עם אבישי — חצי שעה אחרי הארוחה',
    ]),
    ('6', 'שבת משותפת או נפרדת', [
        "<b>משותפת</b>: סוגרים עם שנה א' מי מקבל את <b>התנורים עד 11:00</b> ומי <b>מ-11:00</b>",
        'התנורים שלנו עד 11:00 ← אנחנו מסדרים את <b>בית המדרש</b> בשישי ומנקים את <b>חדר האוכל</b> במוצ"ש',
        'התנורים שלנו מ-11:00 ← ההכנות ב-11:00, מנקים את <b>חדר האוכל</b> בשישי ואת <b>בית המדרש</b> במוצ"ש',
        "<b>משותפת</b>: מתאמים עם שנה א' את המקום לארוחת הערב ולקבלת שבת ישראלית"
        " (אפשר לאכול יחד בחדר האוכל)",
        '<b>נפרדת</b>: קבלת שבת ישראלית במצפה, ובגשם — בחדר האוכל. בית המדרש וחדר האוכל כולם שלנו',
    ]),
]
WIDE = {"3", "6"}                  # כרטיס לכל רוחב הדף; השאר זוגות זה לצד זה
SPAN = {"1": 4, "2": 8}            # רוחב מתוך 12 (ברירת מחדל 6): 2 ארוך בהרבה מ-1 — כך לא נשאר חור ב-1

FORM_LINK = "urishav464.github.io/Ein-Prat-work"
SEND = ('ממלאים את <b>«טופס שבת»</b> בקישור <b><bdi dir="ltr" class="link">{link}</bdi></b> ושולחים לאורי'
        ' את ההודעה שנוצרת <b>עד שבוע לפני השבת</b>.<br>'
        'משם יוצאים לבד: <b>פלייר לכל תורנות</b>, <b>לו"ז צל</b> ושיבוץ השמות.').format(link=FORM_LINK)
AUTO = ('לא צריך לדאוג ל: צוות שבת · התורנויות עצמן (ארוחות, טיש, קידוש, בית המדרש, ניקיונות) ·'
        ' מי עושה כמה — המערכת משבצת לפי הניקוד ומאזנת מול השבתות הקודמות.'
        ' את מי שמעביר את הטיש סוגרים אתם.')

MIN_FIT = 0.85                     # מתחת לזה הטקסט קטן מדי — עדיף לצופף את הריווח

CSS = """
.sheet{padding:10mm 12mm 8mm}
h1{font-size:23pt}
.sub{text-align:center;font-size:11.5pt;color:#5A6572;margin-top:.5mm}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:3.5mm;margin-top:4.5mm}
.card{grid-column:span 6;border:1px solid #1F2430;padding:2.8mm 4.5mm 2.3mm;break-inside:avoid}
.card.wide{grid-column:1 / -1}
.card h2{font-family:'Rubik',sans-serif;font-size:13pt;display:flex;align-items:center;gap:2.5mm;margin-bottom:1.2mm}
.card h2 span{display:inline-flex;align-items:center;justify-content:center;width:6.5mm;height:6.5mm;
  border-radius:50%;background:#1F2430;color:#fff;font-size:10pt}
.card ul{list-style:none;padding:0}
.card li{font-size:10.5pt;line-height:1.38;padding:.45mm 5.5mm .45mm 0;position:relative;text-wrap:pretty}
.card li b{white-space:nowrap}
.card li:before{content:'';position:absolute;right:0;top:1.2mm;width:3mm;height:3mm;border:1.3px solid #1F2430;border-radius:.6mm}
.send{margin-top:4mm;border:2px solid #1F2430;background:#F1F3F6;padding:2.8mm 5mm;text-align:center;font-size:11.5pt;line-height:1.5;text-wrap:balance}
.send b{font-family:'Rubik',sans-serif}
.send .link{white-space:nowrap}
.auto{margin-top:2.8mm;text-align:center;font-size:9.5pt;color:#5A6572;line-height:1.45}
footer{margin-top:3.5mm}
"""

# מדידה ייעודית למדריך (ה-MEASURE_SCRIPT של export_pdf מצפה לטבלה): היחס בין הגובה הפנוי
# בעמוד לגובה התוכן, כשהתוכן עוד לא מכווץ (1 ומעלה = נכנס), וגובה החלון שבאמת מצויר.
MEASURE_SCRIPT = """<script>
(function(){
  function report(){
    var page = document.querySelector('.page');
    var inner = page.querySelector('.inner');
    var cs = getComputedStyle(page);
    var avail = page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var used = inner.getBoundingClientRect().height;
    document.title = 'GUIDE:' + (avail / used) + '|AVAIL:' + Math.round(avail) +
                     '|USED:' + Math.round(used) + '|VIEW:' + window.innerHeight;
  }
  window.addEventListener('load', report);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(report); }
})();
</script>"""

PAGE_W, PAGE_H = 794, 1123         # A4 ב-px של CSS


def nodash(text):
    """מקף ארוך לא פותח שורה — נצמד למילה שלפניו."""
    return text.replace(" — ", "&nbsp;— ")


def guide_html(fit=1.0, measure=False):
    cards = []
    for num, title, items in SECTIONS:
        lis = "".join("<li>{}</li>".format(nodash(x)) for x in items)
        cards.append('<div class="card{}"{}><h2><span>{}</span>{}</h2><ul>{}</ul></div>'.format(
            " wide" if num in WIDE else "",
            ' style="grid-column:span {}"'.format(SPAN[num]) if num in SPAN else "", num, title, lis))
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body><div class="sheet page fixed"><div class="inner">
<h1>מדריך לאחראי השבת</h1>
<div class="sub">מה בודקים במהלך השבוע — ומה שולחים לאורי</div>
<div class="grid">{cards}</div>
<div class="send">{send}</div>
<div class="auto">{auto}</div>
<footer>מדרשת עין פרת</footer>
</div></div>{script}</body></html>""".format(
        fonts=ep.font_face_css(), base=ep.BASE_CSS, css=CSS, fit=fit, cards="".join(cards),
        send=nodash(SEND), auto=nodash(AUTO), script=MEASURE_SCRIPT if measure else "")


def shot_binary():
    """הדפדפן לצילום ה-PNG — ep.shot_binary (headless_shell מצייר את כל החלון). אם הוא חסר,
    screenshot מגדיל את החלון בהפרש שנמדד."""
    return ep.shot_binary()


def run_chrome(html_text, *args):
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "guide.html"
        source.write_text(html_text, encoding="utf-8")
        return subprocess.run(
            [shot_binary(), "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             "--virtual-time-budget=8000", "--user-data-dir={}/profile".format(tmp)] + list(args) +
            [source.as_uri()], capture_output=True, timeout=180)


def measure(html_text):
    """(יחס, גובה פנוי, גובה התוכן, גובה החלון שמצויר) בפיקסלים, בחלון בגודל A4."""
    result = run_chrome(html_text, "--window-size={},{}".format(PAGE_W, PAGE_H), "--dump-dom")
    match = re.search(r"GUIDE:([0-9.]+)\|AVAIL:([0-9]+)\|USED:([0-9]+)\|VIEW:([0-9]+)",
                      result.stdout.decode("utf-8", "replace"))
    if not match:
        raise SystemExit("שגיאה: מדידת המדריך נכשלה — Chromium לא החזיר את גובה העמוד")
    return float(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))


def screenshot(html_text, out_png, view_h):
    """PNG של העמוד כולו, ברזולוציה כפולה. אם החלון מצייר פחות מגובהו (view_h < PAGE_H),
    מגדילים אותו בהפרש — ואז התמונה ארוכה מ-A4 ברצועה לבנה, אבל שום דבר לא נחתך."""
    run_chrome(html_text, "--window-size={},{}".format(PAGE_W, PAGE_H + max(0, PAGE_H - view_h)),
               "--force-device-scale-factor=2", "--screenshot={}".format(out_png)).check_returncode()


def main():
    ratio, avail, used, view_h = measure(guide_html(measure=True))
    fit = 1.0 if ratio >= 1.0 else round(ratio * 0.99, 3)      # 1% מרווח ביטחון לעיגולים
    print("מדידה: תוכן {}px מתוך {}px פנויים (יחס {:.3f}) → כיווץ {}".format(used, avail, ratio, fit))
    if fit < MIN_FIT:
        raise SystemExit("שגיאה: המדריך ארוך מדי לעמוד אחד — היה צריך לכווץ ל-{} והמינימום הוא {}. "
                         "צריך לצופף את הריווח ב-CSS (הקבצים ב-docs/ לא השתנו)".format(fit, MIN_FIT))
    OUT.mkdir(exist_ok=True)
    pdf, png = OUT / "מדריך לאחראי שבת.pdf", OUT / "מדריך לאחראי שבת.png"
    html_text = guide_html(fit=fit)
    with tempfile.TemporaryDirectory() as tmp:        # קודם לבדוק, ורק אז להחליף את מה שב-docs/
        tmp_pdf, tmp_png = Path(tmp) / "guide.pdf", Path(tmp) / "guide.png"
        pages = ep.render(html_text, tmp_pdf)
        if pages != 1:
            raise SystemExit("שגיאה: המדריך יצא {} עמודים במקום עמוד אחד — "
                             "הקבצים ב-docs/ לא השתנו".format(pages))
        screenshot(html_text, tmp_png, view_h)
        shutil.move(str(tmp_pdf), str(pdf))
        shutil.move(str(tmp_png), str(png))
    print("{} (עמוד אחד, כיווץ {})\n{}".format(pdf.relative_to(ROOT), fit, png.relative_to(ROOT)))


if __name__ == "__main__":
    main()
