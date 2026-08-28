"""
app.py — Streamlit frontend for the Mishmar management app.

SCOPE IS HARDCODED: שנה ב' · תשפ"ז · 5787 · 2026-2027 · מדרשת עין פרת.

All data access goes through data_manager.py. This file renders; it does not
open the database or read files directly.

⚠️ V1 HAS NO AUTHENTICATION. Typing "Uri" grants full admin rights over every
trainee's tasks. That is a deliberate v1 decision — run this locally only, and
do not expose it while the speaker index holds contact details.
"""

from __future__ import annotations

import html

import streamlit as st

import data_manager as dm
import speaker_search as ss
import chat_agent as ca

# --------------------------------------------------------------------------
# Page config must be the first Streamlit call.
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="ניהול משמרים — תשפ״ז",
    page_icon="🕯️",
    layout="wide",
)

ADMIN_NAMES = {"uri", "אורי", "ori"}


# --------------------------------------------------------------------------
# 1. Initialisation
# --------------------------------------------------------------------------


@st.cache_resource
def bootstrap() -> dict:
    """Create the schema and migrate the Markdown, once per process.

    Streamlit reruns this whole script on every interaction, so this must be
    cached — otherwise every click reopens the database. The migration itself
    is additionally guarded by a _meta flag inside data_manager, so it can
    never run twice even if the cache is cleared.
    """
    dm.init_db()
    return dm.migrate_and_archive_md()


# --------------------------------------------------------------------------
# 2. RTL
# --------------------------------------------------------------------------

RTL_CSS = """
<style>
  /* The whole UI is Hebrew; Streamlit has no native RTL mode. */
  .stApp,
  [data-testid="stAppViewContainer"],
  [data-testid="stSidebar"],
  [data-testid="stMarkdownContainer"],
  [data-testid="stMetric"] {
      direction: rtl;
      text-align: right;
  }
  .stTextInput input,
  .stTextArea textarea,
  .stSelectbox div[data-baseweb="select"] {
      direction: rtl;
      text-align: right;
  }
  [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { direction: rtl; }
  h1, h2, h3, h4, h5, h6 { text-align: right; }
  [data-testid="stDataFrame"] { direction: rtl; }

  .kanban-card {
      background: var(--secondary-background-color, #f3f0e8);
      border-inline-start: 4px solid #c9a961;
      border-radius: 6px;
      padding: 0.55rem 0.75rem;
      margin-bottom: 0.5rem;
      font-size: 0.9rem;
      line-height: 1.45;
  }
  .kanban-card .meta { opacity: 0.65; font-size: 0.78rem; }
</style>
"""


def inject_rtl() -> None:
    st.markdown(RTL_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# 3. Authentication (session state only — no passwords in v1)
# --------------------------------------------------------------------------


def _init_session() -> None:
    st.session_state.setdefault("role", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("student_id", None)


def logout() -> None:
    for key in ("role", "user_name", "student_id", "search_result",
                "verify_name", "verify_cache", "nav",
                "chat_history", "chat_loaded_for", "chat_mishmar"):
        st.session_state.pop(key, None)


def show_login() -> None:
    st.title("🕯️ ניהול משמרים")
    st.caption('שנה ב׳ · תשפ״ז · מדרשת עין פרת')

    st.warning(
        "**גרסה 1 — ללא אימות.** ההזדהות היא בשם בלבד, בלי סיסמה. "
        "מי שמקליד «Uri» מקבל גישה מלאה לכל המשימות ולפרטי הקשר במאגר. "
        "להרצה מקומית בלבד — לא לפרסם בכתובת חיצונית."
    )

    students = dm.get_students()
    student_names = [s["name"] for s in students if s["role"] == "student"]

    with st.form("login"):
        name = st.text_input("מי אתה?", placeholder="למשל: חניך 3 · או Uri")
        submitted = st.form_submit_button("כניסה")

    if not submitted:
        if student_names:
            with st.expander("השמות הרשומים במערכת"):
                st.write(" · ".join(student_names))
        return

    typed = (name or "").strip()
    if not typed:
        st.error("צריך להקליד שם.")
        return

    if typed.lower() in ADMIN_NAMES:
        st.session_state.role = "admin"
        st.session_state.user_name = "Uri"
        st.rerun()

    match = next((s for s in students if s["name"] == typed), None)
    if match and match["role"] == "student":
        st.session_state.role = "student"
        st.session_state.user_name = match["name"]
        st.session_state.student_id = match["id"]
        st.rerun()

    st.error(f"לא מצאתי את «{typed}» ברשימת החניכים.")
    if student_names:
        st.info("השמות התקפים: " + " · ".join(student_names))


# --------------------------------------------------------------------------
# 4. Views
# --------------------------------------------------------------------------


def _fmt_nis(x: float) -> str:
    return f"{x:,.0f} ₪"


def _clean(text: str) -> str:
    """Kanban cards are raw HTML, so markdown from the task text would show
    literally (backticks, **bold**). Strip it and escape anything HTML-ish."""
    return (
        html.escape(text or "")
        .replace("`", "")
        .replace("**", "")
    )


def show_admin_dashboard() -> None:
    st.title("לוח בקרה — Uri")
    st.caption('כל 21 המשמרים · שנה ב׳ תשפ״ז')

    mishmarim = dm.get_all_mishmarim()
    budget = dm.get_budget_summary()

    if not mishmarim:
        st.info("אין עדיין נתונים במסד. ודא שההגירה מ-`students_tasks.md` רצה.")
        return

    with_topic = [m for m in mishmarim if m.get("topic")]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("משמרים", len(mishmarim))
    c2.metric("עם נושא סגור", f"{len(with_topic)} / {len(mishmarim)}")
    c3.metric("סה״כ הוצאות", _fmt_nis(budget["total_spent"]))
    c4.metric("אינדיקציה למשמר", _fmt_nis(budget["nominal_per_mishmar"]))

    st.divider()
    st.subheader("המשמרים")

    # st.dataframe does NOT mirror under `direction: rtl` the way st.columns does.
    # Keys are laid out left-to-right in insertion order, so the order below is
    # written in reverse: "#" is inserted last and therefore lands on the RIGHT,
    # which is where a Hebrew reader starts.
    rows = []
    for m in mishmarim:
        rows.append(
            {
                "הוצאות": _fmt_nis(m.get("budget_used") or 0),
                "אחראים": "צוות" if m.get("is_staff_built") else "זוג חניכים",
                "נושא": m.get("topic") or "TBD",
                "סוג": m.get("mishmar_type") or "—",
                "עברי": m["hebrew_date"],
                "תאריך": m["gregorian_date"],
                "#": m["id"],
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

    st.divider()
    st.subheader("תקציב")
    st.caption(
        "אין תקרה עונתית — זהו מעקב הוצאות מצטבר. חריגה במשמר בודד **אינה שגיאה**: "
        "היא נמשכת מהסעיף התקציבי הכולל, ומשמרים זולים מאזנים אותה."
    )
    over = budget["over_nominal"]
    if over:
        st.info(
            "מעל האינדיקציה של "
            + _fmt_nis(budget["nominal_per_mishmar"])
            + ": משמרים "
            + ", ".join(f"#{i:02d}" for i in over)
            + " — לידיעה, לא לדאגה."
        )
    else:
        st.success("אף משמר לא חרג מהאינדיקציה של " + _fmt_nis(budget["nominal_per_mishmar"]) + ".")

    missing = [m for m in mishmarim if not m.get("topic")]
    if missing:
        st.divider()
        st.subheader("ממתין לנושא")
        st.write(" · ".join(f"#{m['id']:02d} ({m['gregorian_date']})" for m in missing))


def show_student_view(student_name: str) -> None:
    student_id = st.session_state.student_id
    st.title(f"שלום, {student_name} 👋")

    mine = dm.get_mishmarim_for_student(student_id)
    if mine:
        st.caption(
            "המשמרים שלך: "
            + " · ".join(f"#{m['id']:02d} ({m['gregorian_date']} · {m['hebrew_date']})" for m in mine)
        )

    tasks = dm.get_tasks_for_student(student_id)
    if not tasks:
        st.info("אין משימות פתוחות כרגע.")
        return

    st.divider()

    # Under `direction: rtl` Streamlit's flex columns reverse, so listing
    # [TO DO, IN PROGRESS, DONE] renders TO DO on the RIGHT — Hebrew reading order.
    titles = {"TO DO": "לעשות", "IN PROGRESS": "בתהליך", "DONE": "הושלם"}
    columns = st.columns(len(dm.TASK_STATUSES))

    for col, status in zip(columns, dm.TASK_STATUSES):
        bucket = [t for t in tasks if t["status"] == status]
        with col:
            st.subheader(f"{titles[status]} ({len(bucket)})")
            for t in bucket:
                st.markdown(
                    f"<div class='kanban-card'>{_clean(t['task_description'])}"
                    f"<div class='meta'>משמר #{t['mishmar_id']:02d} · {t['gregorian_date']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                targets = [s for s in dm.TASK_STATUSES if s != status]
                btn_cols = st.columns(len(targets))
                for bc, target in zip(btn_cols, targets):
                    if bc.button(f"→ {titles[target]}", key=f"mv-{t['id']}-{target}"):
                        dm.update_task_status(t["id"], target)
                        st.toast(f"«{_clean(t['task_description'])[:40]}» → {titles[target]}")
                        st.rerun()


def _speaker_card(entry: dict, topic: str, lesson: str, idx: int) -> None:
    """One discovered candidate: name, confidence, flags, evidence, actions."""
    name = entry["name"]
    conf = {"high": "🟢 ודאות גבוהה", "medium": "🟡 ודאות בינונית", "low": "🟠 ודאות נמוכה"}
    bits = [conf.get(entry.get("confidence", "low"), "")]
    if entry.get("already_known"):
        bits.append("‼️ כבר במאגר — בדקו סטטוס לפני פנייה")
    bits.extend(entry.get("flags", []))

    st.markdown(f"**{_clean(name)}** — " + " · ".join(b for b in bits if b))
    for note in entry.get("index_notes", []):
        st.caption(note)

    for ev in entry.get("evidence", [])[:2]:
        href = ev.get("href", "")
        if href:
            st.caption(f"[{_clean(ev.get('title', href))[:90]}]({href})")

    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("הוסף למאגר", key=f"add-{idx}-{name}"):
        # Explicit write-back only. Auto-writing every search result would
        # grow the index fast and fill it with noise; this keeps
        # source_type='web_search' meaning "a human decided this is a person".
        href = entry["evidence"][0].get("href") if entry.get("evidence") else None
        new_id = dm.add_new_speaker(
            name=name,
            expertise_topics=topic,
            verification_url=href,
            source_type="web_search",
            lesson_fit=lesson,
            notes="נמצא בחיפוש רשת · ⚠️ לאמת לפני פנייה",
        )
        st.toast(f"«{name}» נוסף למאגר" if new_id else f"«{name}» כבר קיים במאגר")
    if c2.button("אמת", key=f"ver-{idx}-{name}"):
        st.session_state["verify_name"] = name


def show_speaker_search() -> None:
    st.title("חיפוש מרצים")
    st.caption("שני נתיבים מקבילים: המאגר המקומי, וגילוי שמות חדשים מהרשת")

    status = ss.search_status()
    cache = dm.cache_stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("קריאות רשת (בסשן)", status["network_calls"])
    c2.metric("נחסך מהמטמון", status["cache_hits"])
    c3.metric("שאילתות במטמון", cache["total"])
    if not status["available"]:
        st.warning(
            f"⏳ מנוע החיפוש חסם אותנו זמנית. ממתינים "
            f"{status['cooldown_remaining_sec']} שניות. "
            "בינתיים אפשר להשתמש בקישורי החיפוש הידני שמופיעים בתוצאות."
        )

    default_topic = ""
    if st.session_state.get("student_id"):
        for m in dm.get_mishmarim_for_student(st.session_state["student_id"]):
            if m.get("topic"):
                default_topic = m["topic"]
                break

    with st.form("speaker_search"):
        topic = st.text_input("נושא המשמר", value=default_topic, placeholder="למשל: תשובה")
        lesson = st.selectbox(
            "לאיזה שיעור?",
            options=["1", "2", "3", "4"],
            format_func=lambda k: (
                f"{k} · {ss.LESSON_PROFILES[k]['label']}" if k in ss.LESSON_PROFILES
                else "4 · נחיתה אל הלב (ללא מרצה חיצוני)"
            ),
        )
        go = st.form_submit_button("חפש")

    # The search fires ONLY here, and the result is kept in session state.
    # Streamlit reruns this whole script on every click, so calling the search
    # at render time would re-fire it on every button press in the page.
    if go and topic.strip():
        with st.spinner("מחפש… (יש השהיה מכוונת בין שאילתות כדי לא להיחסם)"):
            st.session_state["search_result"] = ss.search_candidates(topic, lesson)
        st.session_state.pop("verify_name", None)
        st.session_state.pop("verify_cache", None)

    result = st.session_state.get("search_result")
    if not result:
        st.info("הזינו נושא ובחרו שיעור כדי להתחיל.")
        return

    if result.get("skipped"):
        st.info(result["reason"])
        return

    st.divider()
    st.subheader(f"📗 מהמאגר ({len(result['index_hits'])})")
    if result["index_hits"]:
        for r in result["index_hits"]:
            st.markdown(
                f"**{_clean(r['name'])}** — {_clean(r.get('expertise_topics') or 'תחום לא רשום')} · "
                f"אזור: {r.get('region') or '⚪ לא ידוע'} · סטטוס: {r.get('status') or '—'}"
            )
            if "סירב" in (r.get("status") or ""):
                st.caption("↩️ סירוב הוא כמעט תמיד לתאריך מסוים — שווה לנסות שוב בתקופה אחרת")
    else:
        st.caption("אין התאמות במאגר לנושא הזה.")

    st.divider()
    st.subheader(f"🌐 שמות חדשים מהרשת ({len(result['web_names'])})")
    st.caption(
        "כל שם כאן הוא ⚠️ **לאמת** — הוא חולץ מתוצאות חיפוש, לא מהמאגר. "
        "ודאו שהאדם חי, פעיל, ועוסק בתחום לפני פנייה. פרטי קשר לעולם לא ממולאים אוטומטית."
    )
    if result["web_names"]:
        for i, entry in enumerate(result["web_names"][:20]):
            _speaker_card(entry, result["topic"], result["lesson"], i)
            st.divider()
    else:
        st.caption("לא חולצו שמות מהתוצאות.")

    if result.get("errors"):
        st.subheader("⚠️ שאילתות שלא רצו — הריצו ידנית")
        for err in result["errors"]:
            st.markdown(
                f"`{err['query']}` — [DuckDuckGo]({err['manual']['duckduckgo']}) · "
                f"[Google]({err['manual']['google']})"
            )

    if st.session_state.get("verify_name"):
        st.divider()
        name = st.session_state["verify_name"]
        st.subheader(f"אימות — {name}")
        # Cache per name. Without this the verification re-ran on every rerun —
        # i.e. on every unrelated button click on this page — which is exactly
        # the burst pattern the throttle exists to prevent.
        cache = st.session_state.setdefault("verify_cache", {})
        if name not in cache:
            with st.spinner("מאמת…"):
                cache[name] = ss.verify_speaker(name, topic=result["topic"])
        v = cache[name]
        for k, val in v["checklist"].items():
            st.markdown(f"- **{k}:** {val}")
        for f in v.get("flags", []):
            st.warning(f)
        if v.get("recent_years"):
            st.caption("שנים שהופיעו בתוצאות: " + ", ".join(v["recent_years"]))
        for ev in v.get("evidence", [])[:6]:
            if ev.get("href"):
                st.markdown(f"- [{_clean(ev.get('title', ''))[:90]}]({ev['href']})")
        for err in v.get("errors", []):
            st.markdown(f"`{err['query']}` — [חיפוש ידני]({err['manual']['duckduckgo']})")

    st.divider()
    with st.expander("📋 בלוק להעתקה לצ'אט (לסינתזה)"):
        st.caption(
            "האפליקציה אוספת ראיות; הדירוג וההמלצה נעשים בצ'אט. "
            "העתיקו את הבלוק והדביקו בשיחה."
        )
        st.code(ss.format_for_chat(result), language="markdown")


TOOL_LABELS = {
    "close_topic": "סוגר את הנושא",
    "save_lesson": "שומר מקטע בלוז",
    "add_task": "מוסיף משימה",
    "update_task": "מעדכן משימה",
    "search_speaker_index": "מחפש במאגר המרצים",
    "discover_speakers_online": "מחפש מרצים חדשים ברשת",
    "verify_speaker": "מאמת מרצה",
    "check_archive": "בודק בארכיון השנים הקודמות",
    "speaker_history": "בודק היסטוריית מרצה",
}


def _my_mishmarim() -> list[dict]:
    if st.session_state.role == "admin":
        return dm.get_all_mishmarim()
    return dm.get_mishmarim_for_student(st.session_state.student_id)


def show_chat() -> None:
    st.title("בניית משמר")

    mine = _my_mishmarim()
    if not mine:
        st.info("לא משובצים לך משמרים.")
        return

    labels = {
        m["id"]: f"#{m['id']:02d} · {m['gregorian_date']} · {m.get('topic') or 'ללא נושא'}"
        for m in mine
    }
    chosen = st.selectbox(
        "על איזה משמר עובדים?", options=list(labels), format_func=lambda i: labels[i],
        key="chat_mishmar",
    )

    # Switching Mishmar starts a new thread rather than carrying the old one
    # into a different evening's context.
    if st.session_state.get("chat_loaded_for") != chosen:
        st.session_state["chat_history"] = [
            {"role": r["role"], "content": r["content"]}
            for r in dm.get_chat_history(
                mishmar_id=chosen, student_id=st.session_state.student_id
            )
        ]
        st.session_state["chat_loaded_for"] = chosen

    ctx = ca.build_context(st.session_state.student_id, chosen)
    m = ctx.get("mishmar") or {}
    open_tasks = [t for t in (ctx.get("tasks") or []) if t["status"] != "DONE"]
    overdue = [t for t in open_tasks if t.get("overdue")]

    c1, c2, c3 = st.columns(3)
    c1.metric("נושא", m.get("topic") or "טרם נסגר")
    c2.metric("משימות פתוחות", len(open_tasks))
    c3.metric("מומלץ היה לסגור", len(overdue))
    if overdue:
        st.caption(
            "עברו את התאריך המומלץ: "
            + " · ".join(t["task_description"][:24] for t in overdue[:4])
            + "  \n*(המלצה, לא חוק — כך זה מוגדר במפגש הפתיחה)*"
        )

    history = st.session_state.setdefault("chat_history", [])
    for msg in history:
        content = msg["content"]
        if not isinstance(content, str):
            continue  # tool-result blocks are internal plumbing, not shown
        with st.chat_message(msg["role"]):
            st.markdown(content)

    prompt = st.chat_input("במה נתקדם? נושא, מרצים, מבנה הערב…")
    if not prompt:
        if not history:
            st.caption(
                "אפשר להתחיל ב: «עזור לי לבחור נושא» · «מצא מרצה לשיעור הראשון» · "
                "«היה משמר דומה בשנה שעברה?»"
            )
        return

    history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    dm.add_chat_message("user", prompt, mishmar_id=chosen,
                        student_id=st.session_state.student_id)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        text = ""
        try:
            for ev in ca.stream_turn(history, ctx):
                if ev["type"] == "text":
                    text += ev["text"]
                    placeholder.markdown(text)
                elif ev["type"] == "tool":
                    st.caption(f"🔧 {TOOL_LABELS.get(ev['name'], ev['name'])}…")
                elif ev["type"] == "tool_result":
                    out = ev.get("output") or {}
                    if out.get("error"):
                        st.caption(f"⚠️ {out['error'][:120]}")
                elif ev["type"] == "error":
                    st.warning(ev["message"])
        except ca.ChatUnavailable as exc:
            placeholder.empty()
            st.warning(str(exc))
            st.caption(
                "עד שהמפתח יוגדר אפשר להשתמש ב«חיפוש מרצים» ובבלוק ההעתקה לצ׳אט."
            )
            history.pop()   # do not leave a question with no answer in the thread
            return
        except Exception as exc:
            placeholder.empty()
            st.error(f"שגיאה בשיחה: {type(exc).__name__}: {exc}")
            history.pop()
            return

    if text.strip():
        dm.add_chat_message("assistant", text, mishmar_id=chosen,
                            student_id=st.session_state.student_id)
    st.rerun()


# --------------------------------------------------------------------------
# 5. Sidebar + routing
# --------------------------------------------------------------------------


def show_sidebar() -> None:
    with st.sidebar:
        st.markdown(f"### {st.session_state.user_name}")
        st.caption("מדריך (אדמין)" if st.session_state.role == "admin" else "חניך")
        st.divider()
        st.caption('שנה ב׳ · תשפ״ז · 5787')
        st.divider()
        home = "לוח בקרה" if st.session_state.role == "admin" else "המשימות שלי"
        st.radio("מסך", [home, "בניית משמר", "חיפוש מרצים"], key="nav")
        st.divider()
        if st.button("התנתק", width="stretch"):
            logout()
            st.rerun()


def main() -> None:
    inject_rtl()
    _init_session()

    info = bootstrap()
    if info.get("migrated"):
        st.toast(
            f"הועברו למסד: {info['tasks']} משימות · {info['mishmarim']} משמרים. "
            f"הקובץ נגנז."
        )

    if st.session_state.role is None:
        show_login()
        return

    show_sidebar()
    if st.session_state.get("nav") == "בניית משמר":
        show_chat()
    elif st.session_state.get("nav") == "חיפוש מרצים":
        show_speaker_search()
    elif st.session_state.role == "admin":
        show_admin_dashboard()
    else:
        show_student_view(st.session_state.user_name)


if __name__ == "__main__":
    main()
