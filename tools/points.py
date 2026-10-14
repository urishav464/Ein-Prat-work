# -*- coding: utf-8 -*-
"""טבלת הניקוד לחניכים — כמה שווה כל תורנות. עמוד A4 אחד (PDF + PNG) בעיצוב של המדריך והפליירים.

    python3 tools/points.py           # → docs/ניקוד תורנויות.pdf|png

המספרים לא מוקלדים כאן: הניקוד של כל קבוצה בא מ-data/group_plan.csv («ניקוד»), וכל הכנה שהאחראים
מוסיפים שווה bw.PREP_POINTS. גם «מתי יש» נגזר מעמודת «תנאי» של הקבוצה. כאן רק התיאור במילים (DUTIES) —
וקבוצה ב-group_plan בלי תיאור עוצרת את הסקריפט, כדי שתורנות חדשה לא תיעלם מהטבלה בשקט.
משנים ניקוד ב-group_plan.csv ומריצים שוב.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assign_groups as ag
import build_workbook as bw
import export_pdf as ep
import guide

PREP = "כל הכנה בשישי"
# ניקיונות מוצ"ש = צאה + 20, מעוגל למעלה לרבע שעה (schedule_template) — בפועל 23–34 דקות אחרי
CLEANING = "כחצי שעה אחרי צאת השבת — 20 דקות, מעוגל לרבע השעה הבאה (השעה המדויקת בלו\"ז)"
# מה עושים ומתי — במילים. השעות כאן הן ברירת המחדל של הלו"ז (data/schedule_template.csv, task_library.csv).
DUTIES = {
    PREP: "חלות, עוגות, סלטים… — כל הכנה שהאחראים בוחרים היא תורנות משלה. מתחילים ב-8:00 "
          "(ב-11:00 כשהתנורים שלנו מ-11:00), והחלות שעה לפני",
    "ארוחת צהריים שישי": "מבשלים את ארוחת הצהריים, מגישים ב-12:00, ומקפלים ושוטפים ב-13:00",
    "בית מדרש": "מסדרים את בית המדרש ב-8:00, וב-8:45 מצטרפים למטבח",
    "ניקיון חדר האוכל בשישי": "מנקים את חדר האוכל ב-14:00 (כשהתנורים שלנו מ-11:00 — קודם מצטרפים להכנות ב-11:00)",
    "הכנת ארוחת ערב": "מתחילים בשישי ב-14:00 בפריקת האוכל למקרר; לפני כניסת השבת — חימום, ואחר כך סלטים, "
                      "עריכת השולחן והגשה",
    "פינוי ארוחת ערב": "מפנים את הארוחה לפני הטיש, ושוטפים את הגסטרונומים בסיום הטיש",
    "טיש": "חימום העוגות, סידור המרחב והשולחן, וטאטוא בסיום",
    "קידוש": "פינת הקפה, חימום והוצאת העוגות, סידור וטאטוא",
    "הכנת ארוחת צהריים שבת": "הכנסת האוכל לתנור ב-11:00, סלטים, עריכת השולחן והגשה",
    "פינוי ארוחת צהריים שבת": "מפנים את השולחנות ושוטפים את הגסטרונומים, וכשיש סעודה שלישית — מוציאים אליה "
                              "את העוגות",
    "ניקיון בית המדרש": CLEANING,
    "ניקיון חדר האוכל": CLEANING,
    'ארוחת ערב מוצ"ש': "מבשלים ארוחת ערב לכולם — מתחילים עם הניקיונות, ומגישים שעה ורבע אחרי תחילתם",
}
STAGE_WHEN = {"הכנות שישי": "שישי בבוקר", "תורנות שישי": "שישי", "תורנות שבת": 'שישי אחה"צ, ליל שבת ושבת',
              'תורנות מוצ"ש': "מוצאי שבת"}
# «תנאי» של קבוצה → מתי היא שלנו, במילים. «תנורים כל היום» = שבת נפרדת (או משותפת בלי חלון תנורים)
TAG_TEXT = {"נפרדת": "בשבת נפרדת", "תנורים כל היום": "בשבת נפרדת",
            "תנורים " + bw.OVENS_EARLY: "כשהתנורים שלנו " + bw.OVENS_EARLY,
            "תנורים " + bw.OVENS_LATE: "כשהתנורים שלנו " + bw.OVENS_LATE}

RULES = [
    "כל תורנות שווה את הנקודות שלה <b>פעם אחת בשבת</b> — לא משנה כמה משימות יש בה.",
    "הנקודות <b>מצטברות</b> מכל השבתות של השנה.",
    "בכל שבת המערכת משבצת קודם את <b>מי שצבר/ה הכי מעט נקודות</b> — כך העומס מתאזן לאורך השנה.",
    "לכל היותר תורנות אחת בכל שלב, ותורנויות ב-<b>{} שלבים לכל היותר</b> בשבת.".format(ag.MAX_STAGES),
    "מי שעובד/ת בבוקר שישי משובץ/ת קודם ליום שבת ולא לערב שישי (כשיש מספיק אחרים לערב).",
    "מי שלא בשישי בבוקר לא משובץ/ת להכנת ארוחת הערב — היא מתחילה ב-14:00.",
    "מעבירי החבורות לא משובצים לארוחת הצהריים בשבת — לא להכנה ולא לפינוי.",
]

CSS = """
.sheet{padding:10mm 12mm 8mm}
h1{font-size:24pt}
.sub{text-align:center;font-size:11.5pt;color:#5A6572;margin-top:.5mm}
.stage{margin-top:3.2mm}
.stage h2{font-family:'Rubik',sans-serif;font-size:13pt;display:flex;align-items:baseline;gap:2.5mm;
  border-bottom:2px solid #1F2430;padding-bottom:1mm}
.stage h2 small{font-family:'Heebo',sans-serif;font-weight:400;font-size:10pt;color:#5A6572}
.row{display:grid;grid-template-columns:1fr 17mm;align-items:center;gap:4mm;padding:1.1mm 0;
  border-bottom:1px solid #D5DBE3}
.row .name{font-family:'Rubik',sans-serif;font-weight:600;font-size:11.5pt}
.row .only{font-family:'Heebo',sans-serif;font-weight:500;font-size:9pt;color:#9A6212;margin-inline-start:2mm}
.row .what{font-size:9.8pt;color:#3A4552;line-height:1.4;text-wrap:pretty}
.pts{justify-self:center;width:15mm;height:9.5mm;border:1.6px solid #1F2430;border-radius:2mm;display:flex;
  align-items:center;justify-content:center;gap:1mm;font-family:'Rubik',sans-serif}
.pts b{font-size:17pt;line-height:1}
.pts span{font-size:8.5pt;color:#5A6572}
.pts.p3{background:#1F2430;color:#fff}.pts.p3 span{color:#D5DBE3}
.pts.p2{background:#E3E8EF}
.rules{margin-top:4mm;border:2px solid #1F2430;background:#F1F3F6;padding:3mm 5mm}
.rules h2{font-family:'Rubik',sans-serif;font-size:12.5pt;margin-bottom:1mm}
.rules li{font-size:10.3pt;line-height:1.45;margin-inline-start:4mm}
footer{margin-top:3.5mm}
"""


def only_text(condition):
    """«תנאי» של קבוצה → «רק בשבת נפרדת, או כשהתנורים שלנו מ-11:00» (ריק = בכל שבת)."""
    tags = [t.strip() for t in (condition or "").split(";") if t.strip()]
    unknown = [t for t in tags if t not in TAG_TEXT]
    if unknown:
        raise SystemExit("שגיאה: אין ב-TAG_TEXT תיאור לתנאי {} — להוסיף ב-tools/points.py".format(unknown))
    texts = list(dict.fromkeys(TAG_TEXT[t] for t in tags))
    return "רק " + ", או ".join(texts) if texts else ""


def duties():
    """[(שלב, [(שם, ניקוד, תיאור, מתי)])] לפי סדר השלבים — הכנה כללית ראשונה, ואחריה group_plan."""
    plan = bw.read_csv("group_plan.csv")
    missing = [r["קבוצה"] for r in plan if r["קבוצה"] not in DUTIES]
    if missing:
        raise SystemExit("שגיאה: אין תיאור בטבלת הניקוד ל-{} — להוסיף ל-DUTIES ב-tools/points.py".format(
            ", ".join(missing)))
    extra = [k for k in DUTIES if k != PREP and k not in {r["קבוצה"] for r in plan}]
    if extra:
        print("⚠ ב-DUTIES יש קבוצות שכבר לא ב-group_plan.csv: {}".format(", ".join(extra)))
    rows = {s: [] for s in bw.STAGES}
    rows[bw.STAGES[0]].append((PREP, bw.PREP_POINTS, DUTIES[PREP], ""))
    for r in plan:
        stage = r["שלב"]
        if stage not in rows:
            raise SystemExit("שגיאה: השלב «{}» של «{}» אינו ב-bw.STAGES".format(stage, r["קבוצה"]))
        rows[stage].append((r["קבוצה"], int(r["ניקוד"]), DUTIES[r["קבוצה"]], only_text(r.get("תנאי"))))
    return [(s, rows[s]) for s in bw.STAGES if rows[s]]


def points_html(fit=1.0, measure=False):
    blocks = []
    for stage, items in duties():
        rows = "".join(
            '<div class="row"><div><div class="name">{name}{only}</div><div class="what">{what}</div></div>'
            '<div class="pts p{p}"><b>{p}</b><span>נק\'</span></div></div>'.format(
                name=name, what=guide.nodash(what), p=p,
                only='<span class="only">· {}</span>'.format(only) if only else "")
            for name, p, what, only in items)
        blocks.append('<div class="stage"><h2>{}<small>{}</small></h2>{}</div>'.format(
            stage, STAGE_WHEN.get(stage, ""), rows))
    rules = "".join("<li>{}</li>".format(guide.nodash(r)) for r in RULES)
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>{fonts}{base}{css}:root{{--fit:{fit}}}</style></head><body><div class="sheet page fixed"><div class="inner">
<h1>כמה שווה כל תורנות</h1>
<div class="sub">הניקוד של התורנויות בשבתות — ואיך המערכת משתמשת בו</div>
{blocks}
<div class="rules"><h2>איך זה עובד</h2><ul>{rules}</ul></div>
<footer>מדרשת עין פרת</footer>
</div></div>{script}</body></html>""".format(
        fonts=ep.font_face_css(), base=ep.BASE_CSS, css=CSS, fit=fit, blocks="".join(blocks), rules=rules,
        script=guide.MEASURE_SCRIPT if measure else "")


def main():
    guide.one_page(lambda fit, measure: points_html(fit=fit, measure=measure), "ניקוד תורנויות",
                   what="טבלת הניקוד")


if __name__ == "__main__":
    main()
