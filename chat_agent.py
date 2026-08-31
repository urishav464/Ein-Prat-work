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

9. **סגירת נושא פותחת את שלב המרצים — פרוס אותו באותה תשובה.** כשכלי
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
    if lessons:
        lines += ["", "**מבנה הערב עד כה:**"]
        for l in lessons:
            bits = [f"{l['slot_order']}."]
            if l.get("start_time"):
                bits.append(l["start_time"])
            bits.append(l.get("title") or "— ללא כותרת")
            if l.get("speaker_name"):
                bits.append(f"· {l['speaker_name']} ({l.get('speaker_status') or ''})")
            lines.append("  " + " ".join(bits))
    else:
        lines += ["", "**מבנה הערב:** עדיין ריק."]

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
            "שומר או מעדכן מקטע אחד בלוז הערב. slot_order הוא 1,2,3... "
            "לא חייבים להיות בדיוק ארבעה — טקס, מעגל שירה או שלושה שיעורים לגיטימיים."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_order": {"type": "integer"},
                "title": {"type": "string"},
                "start_time": {"type": "string", "description": "למשל 20:30"},
                "description": {"type": "string"},
                "lesson_role": {"type": "string", "description": "יסודות / ערעור / טוויסט / נחיתה / טקס / אחר"},
                "speaker_name": {"type": "string"},
                "format": {"type": "string", "description": "הרצאה / חבורות / דיבייט / כתיבה"},
            },
            "required": ["slot_order"],
        },
    },
    {
        "name": "add_task",
        "description": "מוסיף משימה חדשה למשמר. תאריך היעד נגזר אוטומטית מהקטגוריה.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "category": {"type": "string", "enum": list(dm.TASK_CATEGORIES)},
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
            # form path: the 20:00 skeleton, only if the evening is empty.
            created = dm.create_default_timeline(mishmar_id)
            if created:
                out["timeline_created"] = (
                    f"נבנה שלד ערב: {created} משבצות מ-20:00 — שלושה שיעורים, "
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
                start_time=args.get("start_time"),
                description=args.get("description"),
                lesson_role=args.get("lesson_role"),
                speaker_name=args.get("speaker_name"),
                fmt=args.get("format"),
            )
            return {"ok": True, "lesson_id": lesson_id,
                    "lessons": dm.get_lessons(mishmar_id)}

        if name == "add_task":
            tid = dm.add_task(
                mishmar_id, args["description"],
                category=args.get("category"),
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

SCOUT_SYSTEM = """\
אתה סוקר מועמדים להרצאה במשמר של מדרשת עין פרת. תקבל תוצאות חיפוש גולמיות:
התאמות מהמאגר המשותף (עם סטטוס ויומן פניות) ושמות שנכרו מתוצאות חיפוש רשת.

בחר את 3–4 המועמדים הטובים ביותר לנושא ולשיעור. כללים קשיחים:
1. **רק שמות שמופיעים בקלט.** אל תמציא שם, תואר, שיוך מוסדי או פרט קשר.
2. **לעולם לא אדם שאינו בחיים.** הוגה היסטורי שצץ בתוצאות אינו מועמד.
3. שם שמקורו ברשת חייב לשאת דגל "⚠️ לאמת" — הוא לא אומת.
4. אם במאגר כתוב שכבר פנו לאדם — זה חייב להופיע בכרטיס שלו.
5. עדיף מועמד מהמאגר עם היסטוריה טובה על שם רשת לא מוכר, אבל אל תסתפק רק
   במאגר אם הרשת העלתה שם רלוונטי באמת.

החזר JSON בלבד, במבנה:
{"candidates": [{"name": "...", "title": "ד\"ר/הרב/... או null",
  "source": "index" או "web", "rationale": "משפט אחד למה מתאים",
  "evidence": [{"title": "...", "href": "..."}], "flags": ["⚠️ לאמת", ...]}]}
"""


def _history_line(name: str) -> Optional[str]:
    """One line of institutional memory, or None — silence is not a review."""
    try:
        h = archive.speaker_history(name)
    except Exception:
        return None
    if h.get("avg_rating"):
        return f"⭐ {h['avg_rating']} ({h['times_rated']} דירוגים)"
    return None


def scout_speakers(topic: str, lesson: str = "1") -> dict:
    """One search → 3-4 vetted candidates, or a fallback the UI can render raw.

    Gathers through the existing throttled paths (index + web discovery) and
    spends exactly ONE model call to curate. Every failure mode — no API key,
    refused JSON, empty search — degrades to {"fallback": True, "raw": ...}
    so the screen keeps working without the synthesis.
    """
    raw = ss.search_candidates(topic, lesson=lesson)
    if raw.get("skipped"):
        return {"fallback": True, "raw": raw}

    # Compact inputs: the synthesis pays per token, and evidence snippets are
    # long. Project before sending, exactly like tool results are compacted.
    index_part = []
    for r in raw.get("index_hits", [])[:8]:
        status_rows = dm.get_speaker_status(r["name"])
        cur = status_rows[0] if status_rows else {}
        index_part.append({
            "name": dm.display_name(r),
            "topics": r.get("expertise_topics"),
            "notes": (r.get("notes") or "")[:120],
            "status": cur.get("current_status") or r.get("status"),
            "already_approached": bool(cur.get("has_outreach")),
            "history": _history_line(r["name"]),
        })
    web_part = [{
        "name": e.get("name"),
        "confidence": e.get("confidence"),
        "evidence": [{"title": (ev.get("title") or "")[:90],
                      "href": ev.get("href")} for ev in e.get("evidence", [])[:2]],
        "flags": e.get("flags", []),
    } for e in raw.get("web_names", [])[:10]]

    if not index_part and not web_part:
        return {"fallback": True, "raw": raw}

    payload = json.dumps(
        {"topic": topic, "lesson": lesson,
         "index_hits": index_part, "web_names": web_part},
        ensure_ascii=False)

    try:
        client = get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SCOUT_SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1])
        candidates = data.get("candidates") or []
    except (ChatUnavailable, Exception) as exc:
        return {"fallback": True, "raw": raw, "error": f"{type(exc).__name__}: {exc}"}

    # The no-invention rule, enforced and not just requested: a candidate
    # whose name matches nothing we sent is dropped.
    known = {ip["name"] for ip in index_part} | {r["name"] for r in raw.get("index_hits", [])}
    known_web = {w["name"] for w in web_part if w.get("name")}
    vetted = []
    for c in candidates[:4]:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        in_index = any(name in k or k in name for k in known)
        in_web = any(name == k for k in known_web)
        if not (in_index or in_web):
            continue
        c["source"] = "index" if in_index else "web"
        if c["source"] == "web" and "⚠️ לאמת" not in (c.get("flags") or []):
            c.setdefault("flags", []).append("⚠️ לאמת")
        row = next((ip for ip in index_part if name in ip["name"] or ip["name"] in name), None)
        c["index_status"] = (row or {}).get("status")
        c["already_approached"] = bool((row or {}).get("already_approached"))
        c["history"] = (row or {}).get("history")
        vetted.append(c)

    if not vetted:
        return {"fallback": True, "raw": raw, "error": "empty synthesis"}
    return {"fallback": False, "candidates": vetted, "raw": raw}


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
