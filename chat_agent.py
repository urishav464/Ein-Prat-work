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

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        # Streamlit secrets are the deployment path; the env var is the local one.
        try:
            import streamlit as st

            key = st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[attr-defined]
        except Exception:
            key = None
    if not key:
        raise ChatUnavailable(
            "לא נמצא מפתח API. הגדירו ANTHROPIC_API_KEY בסביבה, "
            "או ANTHROPIC_API_KEY ב-secrets של Streamlit."
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

**סגנון**
תשובות קצרות וממוקדות. שאלה אחת בכל פעם, לא שש. כשהחניך תקוע — הצע צעד אחד
קונקרטי, לא רשימה של עשר אפשרויות.
"""


def build_stable_prompt() -> str:
    """The half that never changes between turns, so it can be cached."""
    parts = [ROLE_PROMPT]
    generator = _read(GENERATOR_PROMPT_PATH)
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
    return "".join(parts)


def build_context(student_id: Optional[int], mishmar_id: Optional[int],
                  db_path: str = dm.DB_PATH) -> dict:
    """Everything the agent needs to know about who it is talking to, right now."""
    ctx: dict[str, Any] = {"student_id": student_id, "mishmar_id": mishmar_id}

    if student_id:
        rows = dm._query("SELECT * FROM Students WHERE id = ?", (student_id,), db_path=db_path)
        ctx["student"] = rows[0] if rows else None
        ctx["my_mishmarim"] = dm.get_mishmarim_for_student(student_id, db_path=db_path)

    if mishmar_id:
        ctx["mishmar"] = dm.get_mishmar(mishmar_id, db_path=db_path)
        ctx["lessons"] = dm.get_lessons(mishmar_id, db_path=db_path)
        tasks = dm.get_tasks_for_mishmar(mishmar_id, db_path=db_path)
        ctx["tasks"] = [dm.annotate_deadline(t) for t in tasks]
        partners = dm._query(
            """SELECT s.id, s.name FROM Students s
               JOIN Assignments a ON a.student_id = s.id
               WHERE a.mishmar_id = ?""",
            (mishmar_id,), db_path=db_path,
        )
        ctx["partners"] = [p for p in partners if p["id"] != student_id]
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


def run_tool(name: str, args: dict, ctx: dict, db_path: str = dm.DB_PATH) -> dict:
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
            dm.set_mishmar_topic(mishmar_id, topic, db_path=db_path)
            closed = []
            for t in dm.get_tasks_for_mishmar(mishmar_id, db_path=db_path):
                if t.get("category") == "נושא" and t["status"] != "DONE":
                    dm.update_task_status(t["id"], "DONE", db_path=db_path)
                    closed.append(t["task_description"])
            return {"ok": True, "topic": topic, "tasks_marked_done": closed}

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
                db_path=db_path,
            )
            return {"ok": True, "lesson_id": lesson_id,
                    "lessons": dm.get_lessons(mishmar_id, db_path=db_path)}

        if name == "add_task":
            tid = dm.add_task(
                mishmar_id, args["description"],
                category=args.get("category"), db_path=db_path,
            )
            rows = dm._query("SELECT * FROM Tasks WHERE id = ?", (tid,), db_path=db_path)
            return {"ok": True, "task": rows[0] if rows else {"id": tid}}

        if name == "update_task":
            # Guard: a trainee's chat may only touch tasks on their own Mishmar.
            rows = dm._query("SELECT mishmar_id FROM Tasks WHERE id = ?",
                             (int(args["task_id"]),), db_path=db_path)
            if not rows:
                return {"error": f"אין משימה עם מזהה {args['task_id']}"}
            if mishmar_id and rows[0]["mishmar_id"] != mishmar_id:
                return {"error": "המשימה הזו שייכת למשמר אחר."}
            ok = dm.update_task_status(int(args["task_id"]), args["status"], db_path=db_path)
            return {"ok": ok, "task_id": args["task_id"], "status": args["status"]}

        if name == "search_speaker_index":
            found = dm.search_speakers_by_topic(
                args["topic"], lesson=args.get("lesson"), db_path=db_path)
            return {"count": len(found), "speakers": found,
                    "reminder": "אלה רק מי שכבר מוכר למדרשה. הרחב עם discover_speakers_online."}

        if name == "discover_speakers_online":
            res = ss.search_candidates(
                args["topic"], lesson=args.get("lesson", "1"), db_path=db_path)
            return {
                "index_hits": res["index_hits"],
                "web_names": res["web_names"][:12],
                "queries": res["queries"],
                "errors": [{"query": e["query"], "manual": e["manual"]["duckduckgo"]}
                           for e in res["errors"]],
                "skipped": res.get("skipped"), "reason": res.get("reason"),
            }

        if name == "verify_speaker":
            return ss.verify_speaker(args["name"], topic=args.get("topic"), db_path=db_path)

        if name == "check_archive":
            return archive.summarise_for_topic(args["topic"], db_path=db_path)

        if name == "speaker_history":
            return archive.speaker_history(args["name"], db_path=db_path)

    except ss.SearchUnavailable as exc:
        return {"error": str(exc), "manual_search": ss.manual_search_links(exc.query)}
    except Exception as exc:  # a tool must never take the whole chat down
        return {"error": f"{type(exc).__name__}: {exc}"}

    return {"error": f"כלי לא מוכר: {name}"}


# --------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------


def stream_turn(
    history: list[dict], ctx: dict, db_path: str = dm.DB_PATH, max_rounds: int = 6,
) -> Iterator[dict]:
    """Run one conversational turn, yielding events as they happen.

    Yields {"type": "text"|"tool"|"tool_result"|"final"|"error", ...}.
    `history` is mutated in place so the caller keeps the full thread, including
    thinking blocks, which must be echoed back unchanged on the same model.
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

    for _ in range(max_rounds):
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=history,
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
            output = run_tool(block.name, dict(block.input), ctx, db_path=db_path)
            yield {"type": "tool_result", "name": block.name, "output": output}
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(output, ensure_ascii=False, default=str),
                "is_error": bool(output.get("error")),
            })
        # All results go back in ONE user message — splitting them teaches the
        # model to stop making parallel tool calls.
        history.append({"role": "user", "content": results})

    yield {"type": "error", "message": "עצרתי אחרי יותר מדי סבבי כלים."}
