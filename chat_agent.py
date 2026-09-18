"""
chat_agent.py — the conversational layer trainees actually work against.

This is what turns the app from a task board into a building partner. The
generator prompt stops being a file someone pastes into an external chat and
becomes this agent's system prompt, loaded from disk so there is still exactly
one copy of the pedagogy.

THE SCOPING RULE, which is the important one: every tool that writes is bound
to the Mishmar in the session context. The model never supplies a mishmar_id.
A trainee's chat therefore cannot modify another pair's Mishmar even if the
conversation asks it to — the id is not a parameter the model can reach.

No synthesis happens client-side and no speaker is ever invented: the agent
gets tools that read the real index, run a real web search, and read the real
archive, and it is told to say "I don't know" rather than fill a gap.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator, Optional

import archive
import data_manager as dm
import speaker_search as ss

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000

# --- The context budget ---------------------------------------------------
# A turn re-sends its entire history on every API call, and a tool-using turn
# makes several calls. The two multiply, so anything unbounded in here is paid
# for again on every round: one 20k-char tool result carried through six rounds
# is billed six times. Three ceilings keep a turn flat instead of quadratic.
MAX_TOOL_ROUNDS = 3        # API calls per user message; the last cannot use tools
HISTORY_WINDOW = 8         # trailing messages sent to the model
TOOL_RESULT_LIMIT = 1500   # chars of any one tool result kept in the history
MAX_SPEAKER_ROWS = 8       # rows a speaker search may hand back
MAX_SCOUT_CANDIDATES = 5   # researched names the search screen returns

GENERATOR_PROMPT_PATH = os.path.join(
    dm.REPO_ROOT, "Mishmer-section", "generator", "mishmar-generator-prompt.md"
)
WORKFILE_TEMPLATE_PATH = os.path.join(
    dm.REPO_ROOT, "Mishmer-section", "templates", "mishmar-workfile-template.md"
)


class ChatUnavailable(RuntimeError):
    """No API key, or the SDK is missing. Surfaced to the user, never crashed on."""


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def get_client():
    try:
        import anthropic
    except ImportError as exc:
        raise ChatUnavailable(
            "החבילה `anthropic` לא מותקנת. הריצו: pip install -r requirements.txt"
        ) from exc

    # Streamlit Secrets is the deployment path and the only one that exists in
    # production; the env var is a convenience for scripts.
    key = None
    try:
        import streamlit as st

        key = st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[attr-defined]
    except Exception:
        key = None
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ChatUnavailable(
            "לא נמצא מפתח API. הוסיפו ANTHROPIC_API_KEY ל-Secrets של Streamlit "
            "(Settings → Secrets). ראו DEPLOY.md."
        )
    return anthropic.Anthropic(api_key=key)


# --------------------------------------------------------------------------
# System prompt — stable half (cached) and live half
# --------------------------------------------------------------------------

ROLE_PROMPT = """\
אתה שותף לבניית משמר במדרשת עין פרת, שנה ב׳ · תשפ״ז.
אתה מדבר עם חניך שבונה משמר אמיתי, בעברית, בגובה העיניים.

**התפקיד שלך**
לעזור לחניך לבנות משמר מההתחלה ועד הסוף: לבחור נושא, לבנות את מבנה הערב,
למצוא מרצים אמיתיים, ולסגור את כל הפרטים. אתה שותף — לא מנוע שליפה.

**כללי ברזל**
1. **אל תמציא כלום.** לא נושאים, לא מרצים, לא טקסטים, לא תאריכים, לא פרטי קשר.
   מה שלא ידוע — נשאר TBD. עדיף "אין לי שם קונקרטי" מאשר שם מומצא.
2. **אל תמציא מרצה, ולעולם אל תציע אדם שאינו בחיים.** ההוגים שמופיעים במחולל
   (שפינוזה, קפקא, עגנון, לוינס, הרב קוק) הם טקסטים ללימוד — לא מועמדים להרצאה.
3. **כל שם שאינו מהמאגר נושא ⚠️ לאמת** עם הצ'קליסט המלא.
4. **פרטי קשר לעולם לא ממולאים אוטומטית.**
5. **קרא לפני שאתה עונה.** יש לך כלים שקוראים את המסד האמיתי. אל תענה על
   משימות, תאריכים או מרצים מהזיכרון — תשתמש בכלים.
6. **ארבעת השיעורים הם ברירת מחדל מצוינת, לא חוק.** אם החניך רוצה מבנה אחר —
   טקס, מעגל שירה, שלושה שיעורים — עזור לו לבנות את מה שהוא רוצה. אמור מה
   הקשת של ארבעת השיעורים הייתה נותנת, ואז תבנה איתו את שלו.
   לעולם אל תגיד לחניך שהמשמר שלו שגוי כי יש בו שלושה שיעורים.
7. **כשאתה משנה משהו במסד — תגיד בדיוק מה השתנה.** לא "עדכנתי" סתם.
8. **כל פנייה למרצה נרשמת ביומן המשותף.** אם החניך אומר "פניתי ל...", "הוא
   אישר", "היא לא יכולה" — קרא ל-`record_speaker_outreach` מיד. עשרה חניכים
   מחפשים מרצים במקביל; יומן שלא מתעדכן הוא איך ששני זוגות פונים לאותו אדם
   בלי לדעת. לפני שאתה מציע מרצה — בדוק אם כבר פנו אליו.

9. **מבנה הערב הוא משטח העבודה המרכזי — שקף אותו במדויק.** המשכים קובעים
   את השעות (save_lesson); מועמדי מרצים נוספים ב-add_candidate_speaker;
   «סגרתי את X» = close_speaker (השאר יוסרו ויירשם ✅ ביומן); דף מקורות
   שהגיע = set_source_sheet. כל שינוי שהחניך מספר עליו — בצע בכלי, ואמור
   בדיוק מה השתנה בלוז.
10. **סגירת נושא פותחת את שלב המרצים — פרוס אותו באותה תשובה.** כשכלי
   `close_topic` מחזיר `phase_opened`: ברך בקצרה, הצג את משימות שלב המרצים
   שנפתחו, נקוב בשמות ההתאמות מהמאגר (`index_matches`) כנקודת פתיחה — כולל
   מי שכבר פנו אליו — והצע שני המשכים: לפרט או להוסיף משימות (`add_task`),
   או חיפוש רשת לשמות חדשים (`discover_speakers_online`). את חיפוש הרשת
   הצע — אל תריץ אותו מיוזמתך, הוא איטי ומוגבל-קצב.

**סגנון**
תשובות קצרות וממוקדות. שאלה אחת בכל פעם, לא שש. כשהחניך תקוע — הצע צעד אחד
קונקרטי, לא רשימה של עשר אפשרויות.
"""


# The roster is bounded by these two headings inside נספח א׳.
_ROSTER_START = "**\u05dc\u05d9\u05de\u05d3\u05d5 \u05d0\u05e6\u05dc\u05e0\u05d5:**"
_ROSTER_END = "**\u05dc\u05d9\u05d3\u05d9\u05dd \u05dc\u05dc\u05d0 \u05e9\u05dd**"


def _drop_speaker_roster(text: str) -> str:
    """Remove the 44-name roster from the generator prompt.

    It is a dated snapshot of the same rows `search_speaker_index` reads live,
    so carrying it costs ~3.2k chars on every single request in order to give
    the model *staler* speaker data than its own tool returns — and it is the
    one part of the prompt that goes out of date by itself.

    What surrounds it is not duplicated anywhere and stays: the legend, the
    ה1–ה7 name-collision flags with their "do not merge them on your own
    judgement" rule, the unnamed leads, and the list of institutions to search.
    The file itself is untouched — it is still pasted whole into external chat
    windows, which have no tools.
    """
    a, b = text.find(_ROSTER_START), text.find(_ROSTER_END)
    if a == -1 or b == -1 or b <= a:
        return text
    return (
        text[:a]
        + "**\u05e8\u05e9\u05d9\u05de\u05ea \u05d4\u05e9\u05de\u05d5\u05ea "
          "\u05d0\u05d9\u05e0\u05d4 \u05db\u05d0\u05df \u05d1\u05db\u05d5\u05d5\u05e0\u05d4** \u2014 "
          "\u05d9\u05e9 \u05dc\u05da \u05d0\u05d5\u05ea\u05d4 \u05d7\u05d9\u05d4 \u05d1\u05de\u05e1\u05d3. "
          "\u05e7\u05e8\u05d0 \u05dc-`search_speaker_index` \u05db\u05d3\u05d9 \u05dc\u05e7\u05d1\u05dc "
          "\u05d0\u05ea \u05d4\u05de\u05d0\u05d2\u05e8 \u05d4\u05de\u05e2\u05d5\u05d3\u05db\u05df, "
          "\u05db\u05d5\u05dc\u05dc \u05de\u05d9 \u05db\u05d1\u05e8 \u05e4\u05e0\u05d4 \u05dc\u05de\u05d9.\n\n"
        + text[b:]
    )


_STABLE_PROMPT: Optional[str] = None
_STABLE_KEY: Optional[tuple] = None


def _source_key() -> tuple:
    """Modification times of the files the stable prompt is built from."""
    out = []
    for path in (GENERATOR_PROMPT_PATH, WORKFILE_TEMPLATE_PATH):
        try:
            out.append(os.path.getmtime(path))
        except OSError:
            out.append(None)
    return tuple(out)


def build_stable_prompt() -> str:
    """The half that never changes between turns, so it can be cached.

    Built once and reused: it is read from disk and identical on every round of
    every turn, so rebuilding it per API call was pure I/O. Keyed on the source
    files' mtimes rather than built once per process, so editing the generator
    prompt still takes effect on the next message instead of needing a restart.
    """
    global _STABLE_PROMPT, _STABLE_KEY
    key = _source_key()
    if _STABLE_PROMPT is not None and _STABLE_KEY == key:
        return _STABLE_PROMPT
    parts = [ROLE_PROMPT]
    generator = _drop_speaker_roster(_read(GENERATOR_PROMPT_PATH))
    if generator:
        parts.append(
            "\n\n---\n\n# מחולל המשמרים — הפדגוגיה ורף האיכות\n\n"
            "זהו המסמך שמגדיר איך נבנה משמר טוב. עבוד לפיו, כולל ה-QUALITY BAR.\n\n"
            + generator
        )
    template = _read(WORKFILE_TEMPLATE_PATH)
    if template:
        parts.append(
            "\n\n---\n\n# פורמט קובץ העבודה בפועל\n\n"
            "המחולל מתאר מבנה אידיאלי; זה הפורמט שבו משמרים באמת מנוהלים.\n\n"
            + template
        )
    _STABLE_PROMPT, _STABLE_KEY = "".join(parts), key
    return _STABLE_PROMPT


def build_context(student_id: Optional[int], mishmar_id: Optional[int]) -> dict:
    """Everything the agent needs to know about who it is talking to, right now."""
    ctx: dict[str, Any] = {"student_id": student_id, "mishmar_id": mishmar_id}

    if student_id:
        ctx["student"] = dm.get_student(student_id)
        ctx["my_mishmarim"] = dm.get_mishmarim_for_student(student_id)

    if mishmar_id:
        ctx["mishmar"] = dm.get_mishmar(mishmar_id)
        ctx["lessons"] = dm.get_lessons(mishmar_id)
        ctx["candidates"] = dm.get_lesson_speakers(mishmar_id)
        tasks = dm.get_tasks_for_mishmar(mishmar_id)
        ctx["tasks"] = [dm.annotate_deadline(t) for t in tasks]
        ctx["partners"] = dm.get_partners(mishmar_id, exclude_student_id=student_id)
    return ctx


def render_context(ctx: dict) -> str:
    """The live half of the system prompt. Changes every turn — never cached."""
    lines = ["# ההקשר החי — נכון לרגע זה", ""]

    student = ctx.get("student")
    if student:
        lines.append(f"**החניך:** {student['name']}")

    m = ctx.get("mishmar")
    if not m:
        lines.append("\n**עוד לא נבחר משמר לשיחה הזו.**")
        mine = ctx.get("my_mishmarim") or []
        if mine:
            lines.append("המשמרים שלו: " + " · ".join(
                f"#{x['id']:02d} ({x['gregorian_date']})" for x in mine))
        return "\n".join(lines)

    partners = ctx.get("partners") or []
    lines += [
        "",
        f"**המשמר:** #{m['id']:02d} · {m['gregorian_date']} · {m['hebrew_date']}",
        f"**סוג:** {m.get('mishmar_type') or 'לא נקבע'}"
        + (f" · **שותף:** {partners[0]['name']}" if partners else ""),
        f"**נושא:** {m.get('topic') or '❗ עדיין לא נסגר'}",
    ]
    if m.get("note"):
        lines.append(f"**הערה:** {m['note']}")

    lessons = ctx.get("lessons") or []
    candidates = ctx.get("candidates") or {}
    if lessons:
        lines += ["", "**מבנה הערב (השעות נגזרות מהמשכים — עריכה דרך save_lesson):**"]
        for l in lessons:
            if l.get("is_break"):
                lines.append(
                    f"  {l['slot_order']}. ☕ הפסקה {l.get('duration_minutes') or 30} דק'")
                continue
            bits = [f"{l['slot_order']}."]
            if l.get("start_time"):
                bits.append(l["start_time"])
            bits.append(l.get("title") or "— ללא כותרת")
            if l.get("lesson_role"):
                bits.append(f"[{l['lesson_role']}]")
            if l.get("speaker_name"):
                bits.append(f"· 🎤 {l['speaker_name']} ✅")
            elif candidates.get(l["id"]):
                # names + status only. Phones NEVER enter the chat context.
                bits.append("· מועמדים: " + ", ".join(
                    f"{c['name']} ({c['status']})" for c in candidates[l["id"]][:4]))
            if l.get("source_url"):
                bits.append("· 📎 יש דף מקורות")
            lines.append("  " + " ".join(bits))
    else:
        lines += ["", "**מבנה הערב:** עדיין ריק — ייבנה אוטומטית כשייסגר נושא."]

    tasks = ctx.get("tasks") or []
    open_tasks = [t for t in tasks if t["status"] != "DONE"]
    if open_tasks:
        lines += ["", f"**משימות פתוחות ({len(open_tasks)} מתוך {len(tasks)}):**"]
        for t in sorted(open_tasks, key=lambda x: x.get("due_date") or "9999"):
            mark = "❗" if t.get("overdue") else "•"
            due = f" (מומלץ עד {t['due_date']})" if t.get("due_date") else ""
            nudge = f" — {t['nudge']}" if t.get("nudge") else ""
            lines.append(
                f"  {mark} [{t['id']}] {t['task_description']}{due}{nudge}"
            )
    else:
        lines += ["", "**אין משימות פתוחות.**"]

    lines += ["", "השתמש במזהי המשימות בסוגריים כשאתה מסמן משימה כבוצעה."]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "close_topic",
        "description": (
            "סוגר את נושא המשמר ומסמן את משימת 'סגירת נושא' כבוצעה. "
            "השתמש רק אחרי שהחניך אישר במפורש את הניסוח."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "שם הנושא הסופי"}},
            "required": ["topic"],
        },
    },
    {
        "name": "save_lesson",
        "description": (
            "שומר או מעדכן מקטע בלוז הערב. slot_order הוא 1,2,3... "
            "השעות נגזרות מהמשכים אוטומטית, משעת ההתחלה של המשמר — אל תקבע שעות ידנית. "
            "הפסקות הן משבצות לוז רגילות עם is_break."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_order": {"type": "integer"},
                "title": {"type": "string"},
                "duration_minutes": {"type": "integer", "description": "60 / 75 / 90 לשיעור, 15–30 להפסקה"},
                "description": {"type": "string"},
                "lesson_role": {"type": "string", "description": "יסודות / ערעור / טוויסט / חבורות / טקס / אחר"},
                "format": {"type": "string", "description": "הרצאה / חבורות / דיבייט / כתיבה"},
            },
            "required": ["slot_order"],
        },
    },
    {
        "name": "add_candidate_speaker",
        "description": (
            "מוסיף מרצה אופציונלי לשיעור (מועמד — עוד לא נסגר). השם נלמד "
            "אוטומטית גם במאגר המשותף. טלפון — רק אם החניך מסר אותו."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_order": {"type": "integer"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["slot_order", "name"],
        },
    },
    {
        "name": "close_speaker",
        "description": (
            "«סגרתי את X» — הופך מועמד למרצה הסגור של השיעור: נרשם ✅ ביומן "
            "המשותף, ושאר המועמדים של השיעור מוסרים. חובה לקרוא לזה כשחניך "
            "מספר שמרצה סגר סופית."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_order": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["slot_order", "name"],
        },
    },
    {
        "name": "set_source_sheet",
        "description": "שומר קישור לדף המקורות של שיעור (המרצה שלח קובץ/קישור).",
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_order": {"type": "integer"},
                "url": {"type": "string"},
            },
            "required": ["slot_order", "url"],
        },
    },
    {
        "name": "add_task",
        "description": (
            "מוסיף משימה חדשה למשמר. תאריך היעד נגזר אוטומטית מהקטגוריה. "
            "אם המשימה שייכת למקטע מסוים בערב (למשל «מי מעביר את החבורות») — "
            "העבירו את slot_order של אותו מקטע, והמשימה תיפתח ישירות שם."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "category": {"type": "string", "enum": list(dm.TASK_CATEGORIES)},
                "slot_order": {"type": "integer",
                               "description": "מספר המקטע בלוז, אם המשימה שייכת לאחד"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "update_task",
        "description": "מעדכן סטטוס של משימה קיימת לפי המזהה שמופיע בהקשר.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {"type": "string", "enum": list(dm.TASK_STATUSES)},
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "search_speaker_index",
        "description": (
            "מחפש מרצים במאגר המקומי לפי נושא. זו נקודת פתיחה, לא גבול החיפוש — "
            "אם כל השמות שהצעת הגיעו מכאן, החיפוש היה צר מדי."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "lesson": {"type": "string", "description": "1/2/3/4, אופציונלי"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "discover_speakers_online",
        "description": (
            "חיפוש רשת אמיתי שמחלץ שמות חדשים מהתוצאות. זה הנתיב שמעלה מרצה "
            "שאף אחד לא הכיר. איטי (יש השהיה מכוונת) — השתמש כשבאמת צריך שמות חדשים."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "lesson": {"type": "string", "description": "1, 2 או 3"},
            },
            "required": ["topic", "lesson"],
        },
    },
    {
        "name": "verify_speaker",
        "description": "מריץ את צ'קליסט ⚠️ לאמת על שם: חי? פעיל? איפה? כבר פנינו אליו?",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "topic": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "record_speaker_outreach",
        "description": (
            "רושם ביומן המשותף שפנינו למרצה ומה קרה. **חובה לקרוא לזה בכל פעם "
            "שהחניך מספר שפנה, שקיבל תשובה, או שסגר מרצה** — אחרת זוג אחר לא "
            "יידע ויפנה לאותו אדם. אם יש כמה אנשים באותו שם, הכלי יחזיר את "
            "האפשרויות ותצטרך לשאול את החניך במי מדובר."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string", "enum": list(dm.SPEAKER_STATUSES)},
                "note": {"type": "string"},
                "speaker_id": {
                    "type": "integer",
                    "description": "רק כשהכלי כבר החזיר אפשרויות והחניך בחר",
                },
            },
            "required": ["name", "status"],
        },
    },
    {
        "name": "check_archive",
        "description": (
            "בודק אם היה משמר דומה בשנים קודמות. הארכיון קטן (5 קבצים) — "
            "היעדר תוצאה אינו הוכחה שלא היה."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
    {
        "name": "speaker_history",
        "description": "מה ידוע על מרצה מהעבר — מה לימד אצלנו, ואיך זה הלך (משוב).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    """Execute one tool. mishmar_id comes from ctx, NEVER from the model."""
    mishmar_id = ctx.get("mishmar_id")
    student_id = ctx.get("student_id")

    needs_mishmar = {"close_topic", "save_lesson", "add_task"}
    if name in needs_mishmar and not mishmar_id:
        return {"error": "לא נבחר משמר. בקש מהחניך לבחור משמר בראש העמוד."}

    try:
        if name == "close_topic":
            topic = (args.get("topic") or "").strip()
            if not topic:
                return {"error": "topic ריק"}
            dm.set_mishmar_topic(mishmar_id, topic)
            closed = []
            for t in dm.get_tasks_for_mishmar(mishmar_id):
                if t.get("category") == "נושא" and t["status"] != "DONE":
                    dm.update_task_status(t["id"], "DONE")
                    closed.append(t["task_description"])

            # Closing a topic advances the build phase. Hand the model the
            # newly-current phase and topical index matches, so the SAME
            # response can unfold the next steps instead of stopping at
            # "נסגר" — the Todoist/Linear move: the moment of completion is
            # the moment the next work is laid out.
            out: dict[str, Any] = {"ok": True, "topic": topic,
                                   "tasks_marked_done": closed}
            # The structure appears the moment the topic closes — same as the
            # form path: the skeleton from the evening's own start time, only
            # if the evening is empty.
            created = dm.create_default_timeline(mishmar_id)
            if created:
                out["timeline_created"] = (
                    f"נבנה שלד ערב: {created} משבצות מ-{dm.mishmar_start(mishmar_id)} — שלושה שיעורים, "
                    "הפסקות, ושעת חבורות. הכותרות ריקות ומחכות לתוכן."
                )
            progress = dm.mishmar_progress(mishmar_id=mishmar_id)
            cur = progress["phases"][progress["current"]]
            out["phase_opened"] = {
                "label": cur["label"],
                "open_tasks": [
                    {"id": t["id"], "task": t["task_description"]}
                    for t in cur["tasks"] if t.get("status") != "DONE"
                ][:6],
            }
            # A closed topic is a SENTENCE ("תשובה — האם אדם יכול לשכתב את
            # העבר?"), and an ilike on the whole sentence matches nothing.
            # Fall back to its meaningful words, deduped by row id.
            found = dm.search_speakers_by_topic(topic)
            if not found:
                seen_ids = set()
                for word in topic.replace("?", " ").replace("—", " ").split():
                    if len(word) < 4:
                        continue
                    for r in dm.search_speakers_by_topic(word):
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            found.append(r)
                    if len(found) >= 5:
                        break
            matches = []
            for r in found[:5]:
                status = dm.get_speaker_status(r["name"])
                current = status[0] if status else {}
                matches.append({
                    "name": dm.display_name(r),
                    "topics": r.get("expertise_topics"),
                    "status": current.get("current_status") or r.get("status"),
                    "already_approached": bool(current.get("has_outreach")),
                })
            out["index_matches"] = matches
            return out

        if name == "save_lesson":
            lesson_id = dm.upsert_lesson(
                mishmar_id,
                int(args["slot_order"]),
                title=args.get("title"),
                description=args.get("description"),
                lesson_role=args.get("lesson_role"),
                fmt=args.get("format"),
            )
            if args.get("duration_minutes") and lesson_id:
                dm._t("lessons").update(
                    {"duration_minutes": int(args["duration_minutes"])}
                ).eq("id", lesson_id).execute()
            dm.recompute_lesson_times(mishmar_id)
            return {"ok": True, "lesson_id": lesson_id,
                    "schedule": [
                        {"slot": l["slot_order"], "time": l.get("start_time"),
                         "title": l.get("title"),
                         "break": bool(l.get("is_break"))}
                        for l in dm.get_lessons(mishmar_id)
                    ]}

        if name in ("add_candidate_speaker", "close_speaker", "set_source_sheet"):
            if not mishmar_id:
                return {"error": "לא נבחר משמר."}
            lessons = dm.get_lessons(mishmar_id)
            slot = int(args.get("slot_order") or 0)
            lesson = next((l for l in lessons if l["slot_order"] == slot), None)
            if not lesson:
                return {"error": f"אין מקטע {slot}. המקטעים: "
                        + ", ".join(str(l["slot_order"]) for l in lessons)}
            if name == "add_candidate_speaker":
                cid = dm.add_lesson_speaker(
                    lesson["id"], args["name"], phone=args.get("phone"),
                    student_id=ctx.get("student_id"))
                return {"ok": bool(cid), "candidate": args["name"],
                        "note": "נוסף כמועמד לשיעור וגם למאגר המשותף"}
            if name == "close_speaker":
                res = dm.close_lesson_speaker(
                    lesson["id"], args["name"], mishmar_id=mishmar_id,
                    student_id=ctx.get("student_id"))
                return {"ok": True, **res,
                        "visible_to": "נרשם ✅ ביומן המשותף — כל הזוגות רואים"}
            dm.set_lesson_source(lesson["id"], args["url"])
            return {"ok": True, "slot": slot, "source_url": args["url"]}

        if name == "add_task":
            # The slot is resolved INSIDE the context Mishmar — the model names
            # a slot_order, never a lesson id and never another Mishmar.
            lesson_id = None
            if args.get("slot_order") is not None:
                lesson = next((l for l in dm.get_lessons(mishmar_id)
                               if l["slot_order"] == int(args["slot_order"])), None)
                if lesson is None:
                    return {"error": f"אין מקטע {args['slot_order']} בלוז של המשמר הזה."}
                lesson_id = lesson["id"]
            tid = dm.add_task(
                mishmar_id, args["description"],
                category=args.get("category"), lesson_id=lesson_id,
            )
            return {"ok": True, "task": dm.get_task(tid) or {"id": tid}}

        if name == "update_task":
            # Guard: a trainee's chat may only touch tasks on their own Mishmar.
            task = dm.get_task(int(args["task_id"]))
            if not task:
                return {"error": f"אין משימה עם מזהה {args['task_id']}"}
            if mishmar_id and task["mishmar_id"] != mishmar_id:
                return {"error": "המשימה הזו שייכת למשמר אחר."}
            ok = dm.update_task_status(int(args["task_id"]), args["status"])
            return {"ok": ok, "task_id": args["task_id"], "status": args["status"]}

        if name == "search_speaker_index":
            found = dm.search_speakers_by_topic(
                args["topic"], lesson=args.get("lesson"))
            # Cap BEFORE enriching, for two reasons. Every row costs two more
            # Supabase round-trips below, and a one-letter topic — which is
            # what a model sends when it widens a search — matched 46 rows and
            # produced a 20k-char tool result that was then re-sent on every
            # later round of the turn.
            total = len(found)
            found = found[:MAX_SPEAKER_ROWS]
            # Attach live outreach state, so the model can say "someone already
            # contacted them" instead of proposing a name that is already taken.
            enriched = []
            for r in found:
                status = dm.get_speaker_status(r["name"])
                current = status[0] if status else {}
                out = dm.get_outreach_for_speaker(
                    current["speaker_id"]) if current else []
                notes = (r.get("notes") or "")
                enriched.append({
                    # Projected, not **r: name_norm, verification_url and
                    # created_at are noise to the model, and `contact` must not
                    # travel into a conversation at all.
                    "speaker_id": current.get("speaker_id") or r.get("id"),
                    "name": dm.display_name(r),   # title rejoined for the model
                    "expertise_topics": r.get("expertise_topics"),
                    "lesson_fit": r.get("lesson_fit"),
                    "region": r.get("region"),
                    "notes": notes[:160] + ("…" if len(notes) > 160 else ""),
                    "current_status": current.get("current_status") or r.get("status"),
                    "already_approached": bool(out),
                    "outreach": [
                        {"status": o["status"], "mishmar_id": o.get("mishmar_id"),
                         "by": o.get("student_name"), "when": (o.get("created_at") or "")[:10]}
                        for o in out[:2]
                    ],
                })
            res = {"count": total, "shown": len(enriched), "speakers": enriched,
                   "reminder": "אלה רק מי שכבר מוכר למדרשה. הרחב עם discover_speakers_online."}
            if total > len(enriched):
                res["truncated"] = f"הוצגו {len(enriched)} מתוך {total}. חדד את הנושא."
            return res

        if name == "discover_speakers_online":
            res = ss.search_candidates(
                args["topic"], lesson=args.get("lesson", "1"))
            out = {
                "index_hits": res["index_hits"][:MAX_SPEAKER_ROWS],
                "web_names": res["web_names"][:8],
                "skipped": res.get("skipped"), "reason": res.get("reason"),
            }
            # The query list is only useful when something failed and the
            # trainee needs a link to run by hand; otherwise it is ~1k chars of
            # text the model never acts on.
            if res["errors"]:
                out["errors"] = [
                    {"query": e["query"], "manual": e["manual"]["duckduckgo"]}
                    for e in res["errors"][:3]
                ]
            return out

        if name == "verify_speaker":
            return ss.verify_speaker(args["name"], topic=args.get("topic"))

        if name == "record_speaker_outreach":
            try:
                res = dm.record_outreach(
                    args["status"],
                    name=args.get("name"),
                    speaker_id=args.get("speaker_id"),
                    mishmar_id=mishmar_id,
                    student_id=student_id,
                    note=args.get("note"),
                )
            except dm.AmbiguousSpeaker as exc:
                # Flag ה7: several real people share this name. Hand the
                # options back so the model asks, rather than picking one.
                return {
                    "ambiguous": True,
                    "message": f"יש {len(exc.candidates)} אנשים בשם «{exc.name}». שאל את החניך במי מדובר.",
                    "candidates": [
                        {"speaker_id": c["id"], "name": c["name"],
                         "topics": c.get("expertise_topics"), "notes": c.get("notes")}
                        for c in exc.candidates
                    ],
                }
            return {"ok": True, **res,
                    "visible_to": "כל הזוגות רואים את זה מעכשיו במאגר המשותף"}

        if name == "check_archive":
            return archive.summarise_for_topic(args["topic"])

        if name == "speaker_history":
            return archive.speaker_history(args["name"])

    except ss.SearchUnavailable as exc:
        return {"error": str(exc), "manual_search": ss.manual_search_links(exc.query)}
    except Exception as exc:  # a tool must never take the whole chat down
        return {"error": f"{type(exc).__name__}: {exc}"}

    return {"error": f"כלי לא מוכר: {name}"}


# --------------------------------------------------------------------------
# The in-app speaker scout — the speaker-search screen's synthesis step
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The scout: map → people → fit
#
# Two model calls per search. The FIRST (`scout_map`, no tools, cheap) turns
# the topic into fields: for each angle, a discipline, the kind of person, a
# few BROAD Hebrew search terms — never the topic phrase — and where such
# people sit. The trainee sees the map, edits it, and only then pays for the
# SECOND (`scout_speakers`): the model searches the web itself, with the
# server-side web_search and web_fetch tools, reads staff pages and returns
# names with the angle they answer. The old pipeline quoted the literal topic
# into fourteen fixed queries and mined names out of snippets with regex —
# which is why a lesson topic made it narrower instead of wider.
# --------------------------------------------------------------------------

SCOUT_MAX_SEARCHES = 8      # web searches one run may spend — $10 per 1,000
SCOUT_MAX_FETCHES = 4       # pages it may open — free beyond their tokens
SCOUT_MAX_CONTINUES = 2     # pause_turn resumptions before «truncated»
SCOUT_FETCH_TOKENS = 8000   # cap on a fetched page
SCOUT_SEARCH_TOOL = "web_search_20260318"
SCOUT_FETCH_TOOL = "web_fetch_20260318"

ANGLES = {"1": "יסודות", "2": "ערעור / טוויסט", "3": "זווית מפתיעה"}

# Grounding: an evidence URL on one of these is what makes a name «high».
_INSTITUTIONAL = ("ac.il", "org.il", "hartman", "vanleer", "bac.org", "herzog",
                  "shazar", "pardes", "alma", "bina", "einprat", "gov.il", "muni.il")

MAP_SYSTEM = """\
אתה עוזר לצוות של מדרשת עין פרת לתכנן משמר — ערב לימוד של לילה שלם, בנוי
משלושה שיעורים ושעת חבורות. כל שיעור פונה לנושא הערב מזווית אחרת:
1. **יסודות** — התחום שהנושא שייך אליו. היסטוריון/ית, חוקר/ת, איש/אשת אקדמיה,
   לימוד טקסטואלי. מה צריך לדעת כדי לדבר על זה בכלל.
2. **ערעור / טוויסט** — תחום שמערער על היסודות. פילוסוף/ית, הוגה, מחשבת ישראל,
   מי שהופך את השאלה.
3. **זווית מפתיעה** — תחום סמוך שלא היינו חושבים עליו. אמנות, קולנוע, פסיכולוגיה,
   סוציולוגיה, מדע, מוזיקה, השוואתי.

תקבל נושא של משמר, אולי גם נושא של שיעור בתוכו, ואולי זווית שנבחרה. תפקידך:
**לתרגם את הנושא לתחומים** ולומר איזה סוג של אדם עוסק בהם — לא למצוא אנשים.

כללים:
- `terms` הם 2–4 מונחי חיפוש **רחבים** בעברית, כפי שחוקרים בתחום מכנים אותו
  (למשל «זיכרון קולקטיבי», «היסטוריוגרפיה», «פסיכולוגיה של הזיכרון»). **לעולם
  לא הביטוי של הנושא עצמו** ולא משפט — הנושא הוא שאלה של ערב; מונח חיפוש הוא
  שם של שדה מחקר.
- `where` — 1–3 מוסדות או חוגים בישראל שבהם אנשים כאלה יושבים באמת. אל תמציא
  חוג שאינך בטוח שקיים; מוסד כללי («האוניברסיטה העברית») עדיף על חוג מומצא.
- `who` — סוג האדם במילה או שתיים, לא שם של אדם.
- `why` — משפט אחד: איך התחום הזה מדבר עם הנושא הספציפי.
- אם נבחרה זווית — החזר רק אותה. אחרת החזר את שלושתן.
- עברית בלבד, JSON בלבד, בלי הקדמות.

{"reading": "משפט אחד — על מה הנושא באמת, במילים של שדה מחקר",
 "angles": [{"key": "1", "label": "יסודות", "field": "...", "who": "...",
             "terms": ["...", "..."], "where": ["..."], "why": "..."}]}
"""

SCOUT_SYSTEM = """\
אתה סוקר מרצים למשמר של מדרשת עין פרת — ערב לימוד של לילה שלם, שלושה שיעורים
מזוויות שונות על נושא אחד. תקבל את הנושא ו**מפה**: לכל זווית — תחום, סוג האדם,
מונחי חיפוש ומוסדות. תפקידך למצוא **אנשים חיים ופעילים בישראל** שעוסקים בתחומים
האלה ומתאימים לנושא, בעזרת חיפוש ברשת.

השיטה:
1. חפש לפי **מונחי המפה והמוסדות** — לא לפי ניסוח הנושא. דפים שמכילים את ניסוח
   הנושא הם מאמרים; אנשים נמצאים בדפי סגל, רשימות עמיתים, תוכניות כנסים, פרקי
   פודקאסט, ספרים שיצאו לאחרונה, ראיונות.
2. כשעלה שם מבטיח — פתח דף אחד עליו (עמוד מוסדי, ראיון) כדי לבסס שיוך ופעילות
   עדכנית. אל תפתח יותר מדף אחד לאדם.
3. החזר **1–2 שמות לכל זווית** שנשארה במפה, ולא יותר מ-{max} בסך הכל.

כללים קשיחים:
1. **לעולם לא אדם שאינו בחיים.** הוגה היסטורי שצץ בתוצאות אינו מועמד — שפינוזה,
   לוינס, קפקא ועגנון הם טקסטים ללמוד, לא אנשים להזמין. ספק — לא להחזיר.
2. **פרטי קשר לעולם לא.** אין טלפון, אין אימייל, גם אם הם מופיעים בדף. במקום זה —
   הקישור המוסדי שבו אדם יוכל למצוא אותם.
3. כל שדה שאינך יכול לבסס על דף שקראת — החזר "" ריק. ניחוש הוא המצאה, ועדיף
   שדה ריק על פרט שגוי שחניך יסתמך עליו כשהוא מתקשר.
4. `link` ו-`evidence[].href` חייבים להיות כתובות שהופיעו **בתוצאות החיפוש שלך**.
   כתובת שלא ראית — אל תכתוב.
5. **אל תמלא מקומות סתם.** אם רק שניים באמת מתאימים — החזר שניים. רשימה
   מרופדת גרועה מרשימה קצרה וכנה.
6. ב-`rejected` פרט שמות ששקלת ופסלת ולמה (משפט קצר) — כדי שלא יחפשו אותם שוב.
7. עברית בלבד. JSON בלבד, בלי הקדמה ובלי סיכום אחרי.

{"candidates": [{"name": "שם בלי תואר", "title": "ד\\"ר/הרב/פרופ׳ או \\"\\"",
  "angle": "1|2|3",
  "affiliation": "מוסד / חוג, אם עולה מהדפים",
  "region_hint": "עיר או אזור, אם עולה מהדפים",
  "bio": "משפט אחד — מי זה ובמה עוסק/ת",
  "fit": "משפט אחד — מה בעבודה שלו/ה נוגע לנושא הזה דווקא",
  "link": "הקישור הכי רלוונטי לנושא מתוך מה שקראת",
  "evidence": [{"title": "...", "href": "..."}]}],
 "rejected": [{"name": "...", "why": "..."}]}

--- חומר עזר קבוע (זהה בכל קריאה) ---

המוסדות שהתוכנית מזמינה מהם, לזיהוי שיוך מוסדי: האוניברסיטה העברית, בר-אילן,
תל אביב, בן-גוריון, חיפה, מכון שלום הרטמן, מכון ון ליר, בית אבי חי, בית מורשה,
מכללת הרצוג, מרכז זלמן שזר, מכון פרדס, עלמא, בינה, קולות, המדרשה באורנים,
ישיבת הקיבוץ הדתי, מכון הדר, מדרשת עין פרת עצמה.

רצועות מרחק מהמדרשה (כפר אדומים) — הערב נגמר ב-02:00, ולכן מרחק שוקל יותר
מאשר באירוע יום: 🟢 עד ~40 דק׳ — ירושלים · מעלה אדומים · כפר אדומים · גוש
עציון · אפרת · מבשרת. 🟡 ~1–1.5 שעות — בית שמש · מודיעין · תל אביב · המרכז ·
רעננה · פתח תקווה · רחובות. 🔴 שעתיים ומעלה — חיפה · הגליל · הגולן · באר שבע ·
אילת · הנגב · חו״ל. אל תנחש רצועה — אם אין מקום בדפים, השאר region_hint ריק.

דוגמה לרשומה תקינה (השדות ריקים כשאין ביסוס):
{"name": "רות לוי", "title": "ד\\"ר", "angle": "2",
 "affiliation": "החוג למחשבת ישראל, האוניברסיטה העברית", "region_hint": "ירושלים",
 "bio": "חוקרת הגות יהודית מודרנית, מלמדת גם במכון הרטמן",
 "fit": "מאמרה על תשובה וזיכרון נוגע ישירות בשאלת הערב",
 "link": "https://…/article", "evidence": [{"title": "…", "href": "https://…"}]}
דוגמה לדחייה נכונה: {"name": "ברוך שפינוזה", "why": "הוגה היסטורי — טקסט ללמוד, לא אדם להזמין"}.
"""


def _index_memory(name: str) -> Optional[str]:
    """One line of institutional memory for a name that is ALREADY in the
    index, or None when it is not. The index is not searched on this screen —
    but a name the model brings back must not be presented as new when we have
    invited the person before, and «when» is the useful part: what they taught
    here and on which date (the seed's «מה העביר אצלנו» notes carry
    «(18.9.25)»-style dates), this season's evenings, the last approach in the
    outreach journal, and the rating if any. Only what exists; silence beyond
    membership is said as such, never read as a review."""
    try:
        rows = dm.get_speaker_status(name)
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    bits = ["‼️ במאגר"]
    if len(rows) > 1:
        bits.append(f"{len(rows)} רשומות עם השם הזה — לבדוק מי מהם")
    # what the seed remembers: «נושא (18.9.25) · נושא (11.12.25)»
    dated = []
    for field in ("notes", "expertise_topics"):
        for part in re.split(r"\s·\s|;\s*|\n", r.get(field) or ""):
            if re.search(r"\(\s*\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\s*\)", part):
                dated.append(part.strip())
    # this season's evenings, by name (lessons.speaker_name)
    try:
        hist = dm.get_teaching_history().get(name) or {}
        dates = {m["id"]: m.get("gregorian_date") for m in dm.get_all_mishmarim()}
        for l in hist.get("taught") or []:
            when = dates.get(l.get("mishmar_id"))
            dated.append(f"{l.get('title') or 'שיעור'} — משמר #{l.get('mishmar_id'):02d}"
                         + (f" ({when})" if when else ""))
    except Exception:
        pass
    if dated:
        bits.append("לימד/ה אצלנו: " + " · ".join(dict.fromkeys(dated)))
    if r.get("has_outreach") and r.get("speaker_id"):
        try:
            o = (dm.get_outreach_for_speaker(int(r["speaker_id"])) or [None])[0]
        except Exception:
            o = None
        if o:
            target = (f" למשמר #{o['mishmar_id']:02d}" if o.get("mishmar_id") else "")
            when = f" ({o['gregorian_date']})" if o.get("gregorian_date") else ""
            who = f" · פנה/תה: {o['student_name']}" if o.get("student_name") else ""
            bits.append(f"פנייה אחרונה: {o.get('status') or ''}{target}{when}{who}")
    elif r.get("current_status") and not str(r["current_status"]).startswith("⬜"):
        bits.append(f"סטטוס במאגר: {r['current_status']}")
    try:
        fb = dm.get_feedback_for_speaker(name)
        ratings = [f["rating"] for f in fb if f.get("rating")]
        if ratings:
            bits.append(f"⭐ {sum(ratings) / len(ratings):.1f} ({len(ratings)} דירוגים)")
    except Exception:
        pass
    if len(bits) == 1:
        return "‼️ במאגר — אין תיעוד של הזמנה קודמת"
    return " · ".join(bits)


_NAME_MARKS = str.maketrans("", "", "׳״'\"")


def _usage_of(resp) -> dict:
    usage = getattr(resp, "usage", None)
    if not usage:
        return {}
    srv = getattr(usage, "server_tool_use", None)
    return {
        "input": getattr(usage, "input_tokens", None),
        "output": getattr(usage, "output_tokens", None),
        "cache_read": getattr(usage, "cache_read_input_tokens", None),
        "cache_write": getattr(usage, "cache_creation_input_tokens", None),
        "searches": getattr(srv, "web_search_requests", None) if srv else None,
        "fetches": getattr(srv, "web_fetch_requests", None) if srv else None,
    }


def _usage_sum(parts: list[dict]) -> dict:
    """Usage across a paused-and-resumed turn is the sum of its requests."""
    out: dict = {}
    for u in parts:
        for k, v in (u or {}).items():
            if v is not None:
                out[k] = (out.get(k) or 0) + v
    return out


def _scout_json(text: str) -> dict:
    """The JSON object in a reply that may carry prose around it — or be a
    bare array of candidates, which the old `{…}` slice turned into the first
    candidate alone and, from there, into «empty synthesis»."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in the reply")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    data = json.loads(text[start:end + 1])
    if isinstance(data, list):
        return {"candidates": data}
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    return data


def scout_map(topic: str, lesson_topic: str = "", angle: str = "") -> dict:
    """The cheap first call: the topic read as FIELDS, one entry per angle.
    Returns {"reading", "angles"} or {"error", "reason"}; never raises."""
    payload = json.dumps({
        "topic": topic, "lesson_topic": lesson_topic or "",
        "angle": (f"{angle} — {ANGLES[angle]}" if angle in ANGLES else "לא נבחרה — שלוש הזוויות"),
    }, ensure_ascii=False)
    try:
        client = get_client()
        resp = client.messages.create(
            model=MODEL, max_tokens=1200,
            system=MAP_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(getattr(b, "text", "") for b in (resp.content or [])
                       if getattr(b, "type", None) == "text")
        data = _scout_json(text)
    except Exception as exc:                     # noqa: BLE001 — named, not hidden
        return {"error": f"{type(exc).__name__}: {exc}", "reason": "error",
                "angles": []}
    angles = []
    for a in data.get("angles") or []:
        if not isinstance(a, dict) or str(a.get("key")) not in ANGLES:
            continue
        key = str(a["key"])
        if angle in ANGLES and key != angle:
            continue
        terms = [str(x).strip() for x in (a.get("terms") or []) if str(x).strip()]
        if not terms:
            continue
        angles.append({
            "key": key, "label": ANGLES[key],
            "field": str(a.get("field") or "").strip(),
            "who": str(a.get("who") or "").strip(),
            "terms": terms[:4],
            "where": [str(x).strip() for x in (a.get("where") or []) if str(x).strip()][:3],
            "why": str(a.get("why") or "").strip(),
            "on": True,
        })
    if not angles:
        return {"error": "the map came back without angles", "reason": "empty_reply",
                "angles": []}
    angles.sort(key=lambda a: a["key"])
    return {"reading": str(data.get("reading") or "").strip(), "angles": angles,
            "usage": _usage_of(resp)}


def _scout_tools() -> list[dict]:
    return [
        {"type": SCOUT_SEARCH_TOOL, "name": "web_search",
         "max_uses": SCOUT_MAX_SEARCHES,
         # direct, not dynamic filtering: every result block then comes back
         # whole, and the harvested URLs are what grounds the names (below)
         "allowed_callers": ["direct"],
         "user_location": {"type": "approximate", "country": "IL",
                           "city": "Jerusalem", "timezone": "Asia/Jerusalem"}},
        {"type": SCOUT_FETCH_TOOL, "name": "web_fetch",
         "max_uses": SCOUT_MAX_FETCHES, "max_content_tokens": SCOUT_FETCH_TOKENS},
    ]


def _harvest_sources(content, sources: dict, queries: list[str]) -> None:
    """Every URL the model actually saw, from the response's own blocks —
    search results, fetched pages and citations — plus the queries it ran."""
    for b in content or []:
        kind = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        get = (lambda o, k: getattr(o, k, None)) if not isinstance(b, dict) else (lambda o, k: o.get(k))
        if kind == "server_tool_use":
            inp = get(b, "input") or {}
            q = inp.get("query") if isinstance(inp, dict) else None
            u = inp.get("url") if isinstance(inp, dict) else None
            if q:
                queries.append(f"🔎 {q}")
            elif u:
                queries.append(f"📄 {u}")
        elif kind == "web_search_tool_result":
            items = get(b, "content")
            for it in (items if isinstance(items, list) else []):
                url = getattr(it, "url", None) if not isinstance(it, dict) else it.get("url")
                if url:
                    sources[url] = {
                        "title": getattr(it, "title", None) if not isinstance(it, dict) else it.get("title"),
                        "page_age": getattr(it, "page_age", None) if not isinstance(it, dict) else it.get("page_age"),
                    }
        elif kind == "web_fetch_tool_result":
            res = get(b, "content")
            url = getattr(res, "url", None) if not isinstance(res, dict) else (res or {}).get("url")
            if url:
                doc = getattr(res, "content", None) if not isinstance(res, dict) else res.get("content")
                title = getattr(doc, "title", None) if not isinstance(doc, dict) else (doc or {}).get("title")
                sources.setdefault(url, {"title": title, "page_age": None})
        elif kind == "text":
            for c in get(b, "citations") or []:
                url = getattr(c, "url", None) if not isinstance(c, dict) else c.get("url")
                if url:
                    sources.setdefault(url, {
                        "title": getattr(c, "title", None) if not isinstance(c, dict) else c.get("title"),
                        "page_age": None})


def _confidence(urls: list[str], sources: dict) -> str:
    """high = an institutional page AND recent activity in the evidence;
    medium = one of the two; low = neither. The same promotion rule the old
    scout applied to mined snippets, applied to the pages the model read."""
    institutional = any(any(k in (u or "").lower() for k in _INSTITUTIONAL) for u in urls)
    years = []
    for u in urls:
        years += [int(y) for y in re.findall(r"20\d\d", str((sources.get(u) or {}).get("page_age") or ""))]
    recent = any(y >= 2024 for y in years)
    if institutional and recent:
        return "high"
    if institutional or recent:
        return "medium"
    return "low"


def _ground(candidates: list, sources: dict, rejected: list) -> list[dict]:
    """The no-invention rule, enforced in code: a candidate is kept only when
    at least one of its links is a page the model actually retrieved; a link
    outside that set is blanked; contact fields are stripped whatever came
    back; every name is «⚠️ לאמת». The old scout kept a name only if it was
    among the names WE sent — with the model doing the searching, the
    anchor moves from names to URLs."""
    out = []
    for c in candidates[:MAX_SCOUT_CANDIDATES * 2]:
        if not isinstance(c, dict) or not (c.get("name") or "").strip():
            continue
        name = " ".join(str(c["name"]).split())
        ev = [e for e in (c.get("evidence") or []) if isinstance(e, dict) and e.get("href")]
        kept_ev = [e for e in ev if e["href"] in sources]
        link = c.get("link") if c.get("link") in sources else ""
        urls = [e["href"] for e in kept_ev] + ([link] if link else [])
        if not urls:
            rejected.append({"name": name, "why": "לא נתמך בדף שהחיפוש הביא — נזרק (ungrounded)"})
            continue
        for e in kept_ev:
            e.setdefault("title", (sources.get(e["href"]) or {}).get("title") or "")
        for banned in ("contact", "phone", "email", "טלפון", "מייל"):
            c.pop(banned, None)
        angle = str(c.get("angle") or "")
        out.append({
            "name": name, "title": str(c.get("title") or "").strip(),
            "angle": angle if angle in ANGLES else "",
            "affiliation": str(c.get("affiliation") or "").strip(),
            "region_hint": str(c.get("region_hint") or "").strip(),
            "bio": str(c.get("bio") or "").strip(),
            "fit": str(c.get("fit") or "").strip(),
            "rationale": str(c.get("rationale") or c.get("fit") or "").strip(),
            "link": link or (kept_ev[0]["href"] if kept_ev else ""),
            "evidence": [{"title": e.get("title") or "", "href": e["href"]} for e in kept_ev][:4],
            "flags": ["⚠️ לאמת"], "source": "web",
            "confidence": _confidence(urls, sources),
        })
        if len(out) >= MAX_SCOUT_CANDIDATES:
            break
    return out


def _search_disabled(exc: Exception) -> bool:
    s = str(exc).lower()
    return "web search" in s or "web_search" in s


def scout_speakers(topic: str, lesson: str = "", lesson_topic: str = "",
                   progress=None, scout_map_result: Optional[dict] = None) -> dict:
    """The expensive call: the model searches the web along the map and comes
    back with grounded names. `progress` gets one Hebrew line per search and
    per page opened. Every failure degrades to {"fallback": True, "reason":…}
    with the map and the queries kept, so the screen can still hand the pair
    one manual link per term. `lesson` is kept for the saved-search columns."""
    smap = scout_map_result or {}
    angles = [a for a in (smap.get("angles") or []) if a.get("on", True)]
    if not angles:
        return {"fallback": True, "reason": "no_map", "map": smap, "queries": [],
                "rejected": [], "usage": {}}
    payload = json.dumps({
        "topic": topic, "lesson_topic": lesson_topic or "",
        "reading": smap.get("reading") or "",
        "angles": [{k: a[k] for k in ("key", "label", "field", "who", "terms", "where", "why")}
                   for a in angles],
        "max_candidates": min(MAX_SCOUT_CANDIDATES, 2 * len(angles)),
    }, ensure_ascii=False)

    sources: dict = {}
    queries: list[str] = []
    usages: list[dict] = []
    messages: list[dict] = [{"role": "user", "content": payload}]
    text = ""
    try:
        client = get_client()
        for attempt in range(SCOUT_MAX_CONTINUES + 1):
            with client.messages.stream(
                model=MODEL, max_tokens=5000,
                system=[{"type": "text",
                         "text": SCOUT_SYSTEM.replace("{max}", str(MAX_SCOUT_CANDIDATES)),
                         "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                output_config={"effort": "medium"},
                tools=_scout_tools(),
                messages=messages,
            ) as stream:
                seen_blocks = 0
                for event in stream:
                    if getattr(event, "type", None) != "content_block_stop":
                        continue
                    snap = stream.current_message_snapshot
                    blocks = list(snap.content or [])
                    for b in blocks[seen_blocks:]:
                        seen_blocks += 1
                        if getattr(b, "type", None) == "server_tool_use" and progress:
                            inp = getattr(b, "input", None) or {}
                            if inp.get("query"):
                                progress(f"מחפש: {inp['query']}")
                            elif inp.get("url"):
                                progress(f"קורא: {inp['url'][:90]}")
                msg = stream.get_final_message()
            usages.append(_usage_of(msg))
            _harvest_sources(msg.content, sources, queries)
            text += "".join(getattr(b, "text", "") for b in (msg.content or [])
                            if getattr(b, "type", None) == "text")
            if getattr(msg, "stop_reason", None) == "pause_turn" and attempt < SCOUT_MAX_CONTINUES:
                if progress:
                    progress("ממשיך את החיפוש…")
                messages.append({"role": "assistant",
                                 "content": [b.model_dump(exclude_none=True) for b in msg.content]})
                text = ""            # the final answer comes after the resumption
                continue
            break
        usage = _usage_sum(usages)
        stop = getattr(msg, "stop_reason", None)
        if stop == "max_tokens" or stop == "pause_turn":
            return {"fallback": True, "reason": "truncated", "error": stop, "map": smap,
                    "queries": queries, "rejected": [], "usage": usage}
        if not text.strip():
            return {"fallback": True, "reason": "empty_reply", "error": "empty reply",
                    "map": smap, "queries": queries, "rejected": [], "usage": usage}
        if progress:
            progress("מסנן ומבסס — רק שמות שנתמכים בדף שנקרא")
        data = _scout_json(text)
    except ChatUnavailable as exc:
        return {"fallback": True, "reason": "error", "error": str(exc), "map": smap,
                "queries": queries, "rejected": [], "usage": {}}
    except Exception as exc:                     # noqa: BLE001 — named, not hidden
        reason = "search_disabled" if _search_disabled(exc) else "error"
        return {"fallback": True, "reason": reason, "map": smap,
                "error": f"{type(exc).__name__}: {exc}",
                "queries": queries, "rejected": [], "usage": _usage_sum(usages)}

    rejected = [r for r in (data.get("rejected") or []) if isinstance(r, dict)][:8]
    vetted = _ground(data.get("candidates") or [], sources, rejected)
    for c in vetted:
        c["region_flag"] = dm.region_flag(c.get("region_hint"), c.get("affiliation"))
        c["memory"] = _index_memory(c["name"])
        c["already_approached"] = bool(c["memory"] and "פנייה אחרונה" in c["memory"])
        if c["memory"]:
            c["flags"].append("‼️ כבר במאגר")
    if not vetted:
        return {"fallback": True, "reason": "model_rejected_all" if data.get("candidates") else "no_names",
                "map": smap, "queries": queries, "rejected": rejected[:8], "usage": usage,
                "sources": len(sources)}
    strong = sum(1 for c in vetted if c["confidence"] == "high")
    return {"fallback": False, "candidates": vetted, "rejected": rejected[:6],
            "strong": strong, "target": ss.MIN_STRONG_CANDIDATES, "usage": usage,
            "queries": queries, "map": smap, "sources": len(sources)}


def slim_for_storage(result: dict) -> dict:
    """What a search leaves behind: the map, the queries, the names with the
    fields that describe a person, the rejections, the outcome and the cost.
    Never evidence snippets or raw pages. A few KB, so every run is kept."""
    smap = result.get("map") or {}
    return {
        "fallback": bool(result.get("fallback")),
        "reason": result.get("reason"),
        "error": (result.get("error") or "")[:200] or None,
        "map": {"reading": smap.get("reading") or "",
                "angles": [{k: a.get(k) for k in ("key", "label", "field", "who", "terms", "where", "why", "on")}
                           for a in (smap.get("angles") or [])]},
        "queries": list(result.get("queries") or [])[:20],
        "candidates": [{k: c.get(k) for k in
                        ("name", "title", "angle", "affiliation", "region_hint", "region_flag",
                         "bio", "fit", "rationale", "link", "evidence", "flags", "confidence",
                         "memory", "already_approached")}
                       for c in (result.get("candidates") or [])],
        "rejected": list(result.get("rejected") or [])[:8],
        "strong": result.get("strong", 0), "target": result.get("target", ss.MIN_STRONG_CANDIDATES),
        "usage": result.get("usage") or {},
        "added": list(result.get("added") or []),
    }


# --------------------------------------------------------------------------
# Keeping the context flat
# --------------------------------------------------------------------------


def _shrink(value: Any, str_cap: int, list_cap: int) -> Any:
    """Structurally reduce a value: fewer rows, shorter strings."""
    if isinstance(value, str):
        return value if len(value) <= str_cap else value[:str_cap].rstrip() + "\u2026"
    if isinstance(value, list):
        out = [_shrink(v, str_cap, list_cap) for v in value[:list_cap]]
        if len(value) > list_cap:
            out.append(
                "\u2026\u05d5\u05e2\u05d5\u05d3 %d \u05e9\u05dc\u05d0 \u05e0\u05e9\u05dc\u05d7\u05d5"
                % (len(value) - list_cap)
            )
        return out
    if isinstance(value, dict):
        return {k: _shrink(v, str_cap, list_cap) for k, v in value.items()}
    return value


def compact_tool_output(output: Any, limit: int = TOOL_RESULT_LIMIT) -> str:
    """Serialise a tool result small enough to carry for the rest of the turn.

    Shrinks structurally rather than cutting the JSON text: a result truncated
    mid-string is no longer JSON, and the model cannot read it at all — so the
    naive fix would spend the tokens and lose the answer. Rows and long strings
    go first, and the model is told the output was cut so it can ask again for
    one specific name instead of assuming it saw everything.
    """
    dumped = json.dumps(output, ensure_ascii=False, default=str)
    if len(dumped) <= limit:
        return dumped
    for str_cap, list_cap in ((400, 8), (200, 5), (120, 3), (80, 2)):
        small = _shrink(output, str_cap, list_cap)
        if isinstance(small, dict):
            small["_note"] = (
                "\u05d4\u05e4\u05dc\u05d8 \u05e7\u05d5\u05e6\u05e5 \u05db\u05d3\u05d9 "
                "\u05dc\u05d7\u05e1\u05d5\u05da \u05d1\u05d4\u05e7\u05e9\u05e8. "
                "\u05d1\u05e7\u05e9 \u05e4\u05d9\u05e8\u05d5\u05d8 \u05e2\u05dc \u05e9\u05dd "
                "\u05d0\u05d7\u05d3 \u05d0\u05dd \u05e6\u05e8\u05d9\u05da."
            )
        dumped = json.dumps(small, ensure_ascii=False, default=str)
        if len(dumped) <= limit:
            return dumped
    return json.dumps({"_note": "output too large", "preview": dumped[:limit]},
                      ensure_ascii=False)


def _block_type(block: Any) -> Optional[str]:
    return getattr(block, "type", None) or (
        block.get("type") if isinstance(block, dict) else None)


def _has_tool_result(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, str):
        return False
    return any(_block_type(b) == "tool_result" for b in (content or []))


def trim_history(history: list[dict], window: int = HISTORY_WINDOW) -> list[dict]:
    """The trailing `window` messages — cut only where a cut is legal.

    The window may not open in the middle of an exchange. A `tool_result` whose
    matching `tool_use` was trimmed away is a 400 from the API, not a cheaper
    request, and that is the way this optimisation usually breaks. So the cut
    always lands on a real user turn, and never later than the current
    question: the turn in flight is sent whole, thinking blocks included.

    Trimming is what the model *sees*; the caller's `history` keeps everything,
    so the trainee's thread on screen is never shortened.
    """
    if len(history) <= window:
        return history
    starts = [i for i, m in enumerate(history)
              if m.get("role") == "user" and not _has_tool_result(m)]
    if not starts:
        return history
    cut = len(history) - window
    return history[next((i for i in starts if i >= cut), starts[-1]):]


# --------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------


def stream_turn(
    history: list[dict], ctx: dict, max_rounds: int = MAX_TOOL_ROUNDS,
) -> Iterator[dict]:
    """Run one conversational turn, yielding events as they happen.

    Yields {"type": "text"|"tool"|"tool_result"|"final"|"error", ...}.
    `history` is mutated in place so the caller keeps the full thread, including
    thinking blocks, which must be echoed back unchanged on the same model.
    What is *sent* is the trimmed window; what is kept is everything.
    """
    client = get_client()
    system = [
        # Stable half — the generator prompt and the role. Cached; it is by far
        # the biggest part of the request and it does not change between turns.
        {"type": "text", "text": build_stable_prompt(),
         "cache_control": {"type": "ephemeral"}},
        # Live half — changes every turn, so it sits AFTER the cache breakpoint.
        {"type": "text", "text": render_context(ctx)},
    ]

    rounds = max(1, max_rounds)
    for index in range(rounds):
        # On the final round the model may not call another tool, so a trainee
        # ends the turn with an answer rather than "I ran out of steps".
        extra = {"tool_choice": {"type": "none"}} if index == rounds - 1 else {}
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=trim_history(history),
            **extra,
        ) as stream:
            for event in stream.text_stream:
                yield {"type": "text", "text": event}
            final = stream.get_final_message()

        # Echo the assistant turn back verbatim — thinking blocks included.
        history.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            yield {"type": "final", "message": final}
            return

        results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name, "input": block.input}
            output = run_tool(block.name, dict(block.input), ctx)
            yield {"type": "tool_result", "name": block.name, "output": output}
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                # Compact, not verbatim: this block is re-sent on every
                # remaining round of the turn, and on every later turn that is
                # still inside the window.
                "content": compact_tool_output(output),
                "is_error": bool(isinstance(output, dict) and output.get("error")),
            })
        # All results go back in ONE user message — splitting them teaches the
        # model to stop making parallel tool calls.
        history.append({"role": "user", "content": results})

    yield {"type": "error", "message": "עצרתי אחרי יותר מדי סבבי כלים."}
