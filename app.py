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
from typing import Optional

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
    """Check storage and seed it once, per process.

    Streamlit reruns this whole script on every interaction, so this is cached
    — otherwise every click would re-probe Supabase. The seed itself is
    additionally guarded by an app_meta flag, so it cannot run twice even if
    the cache is cleared.
    """
    return dm.bootstrap()


# --------------------------------------------------------------------------
# 2. RTL
# --------------------------------------------------------------------------

RTL_CSS = """
<style>
  /* ---- Typography: Heebo is the app's voice. Loaded from Google Fonts on
     the deployed app; sandboxes without network fall back silently. ---- */
  @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700;800&display=swap');
  html, body, .stApp, [class^="st-"], button, input, textarea, select {
      font-family: 'Heebo', 'Segoe UI', system-ui, -apple-system, sans-serif !important;
  }
  /* The override above must NOT reach Streamlit's icon glyphs — they are
     ligature text ("keyboard_arrow_down") that renders literally without
     the Material font. */
  [data-testid="stIconMaterial"], span[class*="material-symbols"] {
      font-family: 'Material Symbols Rounded' !important;
  }
  h1, h2, h3 { font-weight: 800 !important; letter-spacing: -0.01em; }

  /* ---- RTL: the whole UI is Hebrew; Streamlit has no native mode. ---- */
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
  .stButton button, .stFormSubmitButton button { direction: rtl; }
  [data-testid="stExpander"] summary { direction: rtl; text-align: right; }
  [data-testid="stProgress"] { direction: rtl; }
  [data-testid="stChatInput"] textarea { direction: rtl; text-align: right; }

  /* ---- Sidebar: warm ground, and the nav radio restyled as cards.
     The radio circle is hidden; the label IS the card. ---- */
  [data-testid="stSidebar"] {
      background: #f4f1ea;
      border-inline-end: 1px solid #e6e0d2;
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label {
      display: flex; align-items: center;
      background: #ffffff;
      border: 1px solid #e8e2d4;
      border-radius: 12px;
      padding: 0.6rem 0.9rem;
      margin-bottom: 0.4rem;
      width: 100%;
      cursor: pointer;
      transition: border-color .15s ease, background .15s ease, transform .1s ease;
      box-shadow: 0 1px 2px rgba(60,50,20,.05);
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
      border-color: #c9a961;
      transform: translateX(-2px);
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
      background: linear-gradient(135deg, #f7efdd, #f2e6c9);
      border-color: #c9a961;
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {
      font-weight: 700;
  }
  /* the visual radio mark. Two places, because the DOM has both a hidden
     input wrapper (label > span) and the drawn 16px circle nested beside the
     text (label > div > div > div:first-child). Hiding them keeps the label
     clickable — it still wraps the real input. */
  [data-testid="stSidebar"] div[role="radiogroup"] > label > span:first-child {
      display: none;
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label > div > div > div:first-child {
      display: none;
  }

  .side-avatar {
      width: 44px; height: 44px; border-radius: 50%;
      background: linear-gradient(135deg, #c9a961, #a9873f);
      color: #fff; font-weight: 800; font-size: 1.15rem;
      display: flex; align-items: center; justify-content: center;
      margin-bottom: .3rem;
  }

  /* ---- Cards: st.container(border=True) is the app's card primitive ---- */
  [data-testid="stVerticalBlockBorderWrapper"] {
      background: #ffffff;
      border-radius: 14px;
      box-shadow: 0 1px 5px rgba(60, 50, 20, 0.07);
  }

  /* ---- Chat: bubbles, not a white box ---- */
  .chat-head {
      background: linear-gradient(135deg, #2f2a1d, #4a4028);
      color: #f7efdd;
      border-radius: 14px;
      padding: .55rem .9rem;
      font-weight: 700;
      margin-bottom: .45rem;
      display: flex; align-items: center; gap: .5rem;
  }
  .chat-head small { font-weight: 400; opacity: .75; font-size: .72rem; }
  [data-testid="stChatMessage"] {
      border-radius: 16px;
      padding: .7rem .95rem;
      margin-bottom: .3rem;
      background: #ffffff;
      border: 1px solid #eee7d8;
      box-shadow: 0 1px 2px rgba(60,50,20,.04);
  }
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
      background: #f5edda;
      border-color: #e8d9b4;
  }
  [data-testid^="stChatMessageAvatar"] { display: none; }
  [data-testid="stChatMessage"] p { line-height: 1.55; }
  [data-testid="stChatInput"] {
      border-radius: 14px;
      border: 1px solid #e0d8c4;
  }
  .st-key-chat_reopen button {
      border-radius: 50%;
      width: 52px; height: 52px;
      font-size: 1.25rem;
      border: 1px solid #c9a961;
      background: #f7efdd;
      box-shadow: 0 2px 8px rgba(60,50,20,.15);
  }
  .st-key-chat_close button {
      border: none; background: transparent;
      color: #f7efdd; font-size: .9rem;
      padding: 0 .3rem; min-height: 0;
  }

  /* ---- Chips ---- */
  .chip {
      display: inline-block;
      padding: 1px 10px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 600;
      margin-inline-end: 4px;
      white-space: nowrap;
  }
  .chip-red    { background: #fdecea; color: #b3261e; }
  .chip-yellow { background: #fef3d5; color: #92600a; }
  .chip-green  { background: #e6f4ea; color: #137333; }
  .chip-gray   { background: #eeece7; color: #5a564c; }
  .chip-gold   { background: #f5edda; color: #8a6d1d; }
  .chip-blue   { background: #e8f0fe; color: #1a56b4; }

  .task-desc { font-weight: 600; line-height: 1.45; margin-bottom: 4px; }
  .card-meta { opacity: 0.65; font-size: 0.78rem; margin-top: 4px; }

  /* ---- The phase stepper ---- */
  .stepper { display: flex; align-items: flex-start; margin: .5rem 0 .3rem; }
  .step { display: flex; flex-direction: column; align-items: center; gap: 3px;
          flex: 0 0 auto; font-size: .7rem; color: #6a6455; min-width: 58px; }
  .step .dot {
      width: 34px; height: 34px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      background: #eeece7; border: 2px solid #ddd6c6; font-size: .95rem;
  }
  .step.done .dot    { background: #e6f4ea; border-color: #137333; }
  .step.current .dot { background: #f5edda; border-color: #c9a961;
                       box-shadow: 0 0 0 4px rgba(201,169,97,.2); }
  .step.current { color: #2f2a1d; font-weight: 700; }
  .step-bar { flex: 1 1 auto; height: 3px; background: #e4ddcb;
              margin: 16px 2px 0; border-radius: 2px; min-width: 10px; }
  .step-bar.done { background: #137333; }

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
    """Clear the session. Under Google auth, also end the OIDC session."""
    for key in ("role", "user_name", "student_id", "search_result",
                "verify_name", "verify_cache", "nav", "chat_open",
                "chat_history", "chat_loaded_for", "chat_mishmar"):
        st.session_state.pop(key, None)
    if auth_configured() and getattr(st.user, "is_logged_in", False):
        st.logout()


def auth_configured() -> bool:
    """True when Google sign-in is set up in .streamlit/secrets.toml.

    Deployment needs real auth; local development should not. When [auth] is
    present we use Google and the name box is switched OFF entirely — leaving
    it available would mean anyone could still bypass sign-in by typing "Uri".
    """
    try:
        return "auth" in st.secrets and hasattr(st, "login")
    except Exception:
        return False


def _admin_emails() -> set[str]:
    try:
        raw = st.secrets.get("admin_emails", [])
    except Exception:
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    return {e.strip().lower() for e in raw if e and e.strip()}


def show_google_login() -> None:
    st.title("🕯️ ניהול משמרים")
    st.caption('שנה ב׳ · תשפ״ז · מדרשת עין פרת')

    if not getattr(st.user, "is_logged_in", False):
        st.write("היכנסו עם חשבון הגוגל שלכם.")
        st.button("כניסה עם Google", on_click=st.login, width="stretch")
        return

    email = (getattr(st.user, "email", "") or "").strip()
    if email.lower() in _admin_emails():
        st.session_state.role = "admin"
        st.session_state.user_name = getattr(st.user, "name", None) or "Uri"
        st.rerun()

    match = dm.get_student_by_email(email)
    if match:
        st.session_state.role = "student"
        st.session_state.user_name = match["name"]
        st.session_state.student_id = match["id"]
        st.rerun()

    # Signed in with Google, but nobody has linked this address to a trainee.
    st.warning(
        f"התחברת בתור **{_clean(email)}**, אבל הכתובת הזו עדיין לא משויכת "
        "לאף חניך במערכת."
    )
    st.caption("בקשו מהמדריך לשייך את הכתובת בלוח הבקרה, תחת «שיוך חשבונות».")
    st.button("התנתק", on_click=st.logout)


def show_login() -> None:
    if auth_configured():
        show_google_login()
        return

    st.title("🕯️ ניהול משמרים")
    st.caption('שנה ב׳ · תשפ״ז · מדרשת עין פרת')

    st.warning(
        "**מצב פיתוח — ללא אימות.** ההזדהות היא בשם בלבד, בלי סיסמה. "
        "מי שמקליד «Uri» מקבל גישה מלאה לכל המשימות ולפרטי הקשר במאגר. "
        "להרצה מקומית בלבד. לפריסה חיצונית — הגדירו `[auth]` "
        "ב-`.streamlit/secrets.toml` (ראו `secrets.toml.example`), "
        "וההתחברות תעבור אוטומטית ל-Google."
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
    st.title("🎛️ לוח הבקרה")
    st.caption('כל 21 המשמרים · שנה ב׳ תשפ״ז · מבט מדריך')

    mishmarim = dm.get_all_mishmarim()
    budget = dm.get_budget_summary()

    if not mishmarim:
        st.info("אין עדיין נתונים במסד. ודא שההגירה מ-`students_tasks.md` רצה.")
        return

    with_topic = [m for m in mishmarim if m.get("topic")]
    totals = dm.get_task_totals()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🕯️ משמרים", len(mishmarim))
    c2.metric("🎯 עם נושא סגור", f"{len(with_topic)} / {len(mishmarim)}")
    c3.metric("💰 סה״כ הוצאות", _fmt_nis(budget["total_spent"]))
    c4.metric("📊 אינדיקציה למשמר", _fmt_nis(budget["nominal_per_mishmar"]))

    if totals["total"]:
        st.progress(totals["done"] / totals["total"],
                    text=f"התקדמות העונה: {totals['done']}/{totals['total']} משימות הושלמו")

    st.divider()
    st.subheader("🔴 עבר את התאריך המומלץ")
    overdue = dm.get_overdue_tasks()
    if not overdue:
        st.success("שום משימה לא עברה את התאריך המומלץ שלה.")
    else:
        st.caption(
            f"{len(overdue)} משימות פתוחות עברו את התאריך המומלץ. "
            "לחניכים זה מוצג כתזכורת רכה — כאן זה מוצג כדי שתדע איפה להתערב."
        )
        cards = []
        for t in overdue:
            a = dm.annotate_deadline(t)
            a["category"] = a.get("category") or ""
            cards.append(a)
        for i in range(0, len(cards), 2):
            cols = st.columns(2)
            for col, t in zip(cols, cards[i:i + 2]):
                with col:
                    with st.container(border=True):
                        chips = [_chip("באיחור", "red"),
                                 _chip(f"משמר #{t['mishmar_id']:02d}", "gray")]
                        if t.get("category"):
                            chips.append(_chip(t["category"], "gold"))
                        st.markdown(
                            f"<div class='task-desc'>{_clean(t['task_description'])[:80]}</div>"
                            f"<div>{''.join(chips)}</div>"
                            f"<div class='card-meta'>{_clean(t.get('owners') or 'צוות')} · "
                            f"{t['gregorian_date']} · {_clean(t.get('nudge') or '')}</div>",
                            unsafe_allow_html=True,
                        )
                        # The instructor can advance a trainee's task directly,
                        # for the common case where the work happened but
                        # nobody updated the board.
                        b1, b2 = st.columns(2)
                        if b1.button("✓ הושלם", key=f"ov-dn-{t['id']}", type="primary"):
                            dm.update_task_status(t["id"], "DONE"); st.rerun()
                        if b2.button("▶ בתהליך", key=f"ov-ip-{t['id']}"):
                            dm.update_task_status(t["id"], "IN PROGRESS"); st.rerun()

    st.divider()
    st.subheader("👥 התקדמות החניכים")
    progress = dm.get_student_progress()
    prow = []
    for r in progress:
        total = r["tasks_total"] or 0
        done = r["tasks_done"] or 0
        # st.dataframe does NOT mirror under RTL — columns lay out left-to-right
        # in insertion order, so the dict is written in reverse to put the name
        # on the RIGHT, where a Hebrew reader starts.
        prow.append({
            "באיחור": r["overdue"] or 0,
            "התקדמות": round(100 * done / total) if total else 0,
            "משימות": f"{done}/{total}",
            "משמרים": r["mishmarim"] or 0,
            "חניך": r["name"],
        })
    st.dataframe(
        prow, width="stretch", hide_index=True,
        column_config={
            "התקדמות": st.column_config.ProgressColumn(
                "התקדמות", min_value=0, max_value=100, format="%d%%"),
        },
    )
    behind = [r for r in progress if (r["overdue"] or 0) > 0]
    if behind:
        st.info(
            "חניכים עם משימות שעברו את התאריך: "
            + " · ".join(f"{r['name']} ({r['overdue']})" for r in behind)
        )

    st.divider()
    st.subheader("📅 כל המשמרים")
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
    missing = [m for m in mishmarim if not m.get("topic")]
    if missing:
        st.caption("ממתין לנושא: " + " · ".join(
            f"#{m['id']:02d} ({m['gregorian_date']})" for m in missing))

    with st.expander("💰 תקציב"):
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
            st.success("אף משמר לא חרג מהאינדיקציה של "
                       + _fmt_nis(budget["nominal_per_mishmar"]) + ".")

    if auth_configured():
        with st.expander("🔗 שיוך חשבונות"):
            st.caption(
                "כל חניך נכנס עם חשבון הגוגל שלו. שייכו כאן כתובת לכל שם — "
                "בלי שיוך, החניך יתחבר אבל לא ייכנס לשום משמר."
            )
            with st.form("emails"):
                students = [x for x in dm.get_students() if x["role"] == "student"]
                entered = {}
                for stu in students:
                    entered[stu["id"]] = st.text_input(
                        stu["name"], value=stu.get("email") or "",
                        key=f"em-{stu['id']}", placeholder="name@gmail.com")
                if st.form_submit_button("שמור שיוכים"):
                    n = 0
                    for sid, addr in entered.items():
                        dm.set_student_email(sid, addr); n += 1
                    st.toast(f"נשמרו {n} שיוכים"); st.rerun()


# --------------------------------------------------------------------------
# Card primitives — the visual grammar of the redesigned dashboards
# --------------------------------------------------------------------------

from datetime import date as _date_cls


def _parse_date(value) -> Optional[_date_cls]:
    try:
        return _date_cls.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _fmt_date(value) -> str:
    """ISO out of Postgres, day.month.year in the UI — the repo's convention."""
    d = _parse_date(value)
    return f"{d.day}.{d.month}.{d.year}" if d else str(value or "")


def _chip(text: str, kind: str) -> str:
    return f"<span class='chip chip-{kind}'>{_clean(text)}</span>"


_STATUS_CHIP = {"TO DO": ("לעשות", "gray"),
                "IN PROGRESS": ("בתהליך", "blue"),
                "DONE": ("הושלם", "green")}


def _urgency(t: dict) -> str:
    """red = past the recommended date · yellow = within the week · green = open.
    The deck calls the dates a recommendation, so red is a nudge, not an alarm."""
    if t.get("status") == "DONE":
        return "done"
    if t.get("overdue"):
        return "red"
    days = t.get("days_left")
    if days is not None and days <= 7:
        return "yellow"
    return "green"


def _task_card(t: dict, key_prefix: str, show_mishmar: bool = True) -> None:
    """One task as a bordered card: description, chips, soft nudge, actions."""
    urgency = _urgency(t)
    with st.container(border=True):
        chips = []
        label, kind = _STATUS_CHIP.get(t.get("status"), ("", "gray"))
        if label:
            chips.append(_chip(label, kind))
        if t.get("category"):
            chips.append(_chip(t["category"], "gold"))
        if show_mishmar and t.get("mishmar_id"):
            chips.append(_chip(f"משמר #{t['mishmar_id']:02d}", "gray"))
        if urgency == "red":
            chips.append(_chip("באיחור", "red"))
        elif urgency == "yellow":
            chips.append(_chip("השבוע", "yellow"))

        st.markdown(
            f"<div class='task-desc'>{_clean(t['task_description'])}</div>"
            f"<div>{''.join(chips)}</div>",
            unsafe_allow_html=True,
        )
        meta = t.get("nudge") or (
            f"מומלץ עד {_fmt_date(t['due_date'])}" if t.get("due_date") else "")
        if meta:
            st.markdown(f"<div class='card-meta'>🕒 {_clean(meta)}</div>",
                        unsafe_allow_html=True)

        status = t.get("status")
        b1, b2 = st.columns(2)
        if status == "DONE":
            if b1.button("↩ החזר לתהליך", key=f"{key_prefix}-{t['id']}-re"):
                dm.update_task_status(t["id"], "IN PROGRESS"); st.rerun()
        else:
            if b1.button("✓ הושלם", key=f"{key_prefix}-{t['id']}-dn", type="primary"):
                dm.update_task_status(t["id"], "DONE")
                st.toast(f"«{_clean(t['task_description'])[:40]}» הושלם 🎉")
                st.rerun()
            other = ("↩ לעשות", "TO DO") if status == "IN PROGRESS" else ("▶ התחל", "IN PROGRESS")
            if b2.button(other[0], key=f"{key_prefix}-{t['id']}-mv"):
                dm.update_task_status(t["id"], other[1]); st.rerun()


def _card_grid(items: list[dict], key_prefix: str, per_row: int = 2,
               show_mishmar: bool = True) -> None:
    # st.columns mirrors under RTL, so the first card of each row lands on the
    # RIGHT — Hebrew reading order — with no extra work here.
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, t in zip(cols, items[i:i + per_row]):
            with col:
                _task_card(t, key_prefix, show_mishmar=show_mishmar)


def _mishmar_card(m: dict, tasks: list[dict]) -> None:
    """The trainee's Mishmar at a glance: dates, topic, progress, countdown."""
    mine = [t for t in tasks if t.get("mishmar_id") == m["id"]]
    done = sum(1 for t in mine if t.get("status") == "DONE")
    total = len(mine)
    with st.container(border=True):
        chips = []
        if m.get("mishmar_type"):
            chips.append(_chip(m["mishmar_type"], "gold"))
        d = _parse_date(m.get("gregorian_date"))
        days = (d - _date_cls.today()).days if d else None
        if days is not None:
            if days < 0:
                chips.append(_chip("התקיים", "gray"))
            elif days <= 14:
                chips.append(_chip(f"בעוד {days} ימים", "yellow" if days > 7 else "red"))
            else:
                chips.append(_chip(f"בעוד {days} ימים", "green"))
        st.markdown(
            f"<div class='task-desc'>🕯️ משמר #{m['id']:02d} · {m['gregorian_date']} · "
            f"{m['hebrew_date']}</div><div>{''.join(chips)}</div>",
            unsafe_allow_html=True,
        )
        if m.get("topic"):
            st.markdown(f"**הנושא:** {_clean(m['topic'])}")
        else:
            st.markdown("**הנושא:** ❗ עדיין לא נסגר — זה הצעד הראשון")
        if total:
            st.progress(done / total, text=f"{done}/{total} משימות הושלמו")
        else:
            st.caption("אין עדיין משימות למשמר הזה.")


def show_student_view(student_name: str) -> None:
    student_id = st.session_state.student_id
    st.title(f"🏠 שלום, {student_name}")
    st.caption("המשמרים שלך, המשימות שלך — לפי מה שדחוף באמת.")

    mine = dm.get_mishmarim_for_student(student_id)
    tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_student(student_id)]

    if not mine:
        st.info("עוד לא משובצים לך משמרים.")
        return

    st.subheader("🕯️ המשמרים שלי")
    for i in range(0, len(mine), 2):
        cols = st.columns(2)
        for col, m in zip(cols, mine[i:i + 2]):
            with col:
                _mishmar_card(m, tasks)

    if not tasks:
        st.info("אין משימות פתוחות כרגע.")
        return

    st.divider()
    buckets: dict[str, list[dict]] = {"red": [], "yellow": [], "green": [], "done": []}
    for t in tasks:
        buckets[_urgency(t)].append(t)
    by_due = lambda x: x.get("due_date") or "9999"

    if buckets["red"]:
        st.subheader(f"🔴 עבר התאריך המומלץ ({len(buckets['red'])})")
        st.caption("המלצה — לא חוק. אבל אלה הדברים ששווה לסגור קודם.")
        _card_grid(sorted(buckets["red"], key=by_due), "red")

    if buckets["yellow"]:
        st.subheader(f"🟡 מומלץ השבוע ({len(buckets['yellow'])})")
        _card_grid(sorted(buckets["yellow"], key=by_due), "yel")

    if buckets["green"]:
        # A season is ~40 open tasks per trainee. The urgent buckets stay flat
        # on the page; the far-future bulk folds, or the grid becomes exactly
        # the endless list the redesign is replacing.
        urgent_exists = bool(buckets["red"] or buckets["yellow"])
        with st.expander(f"🟢 פתוח — בהמשך ({len(buckets['green'])})",
                         expanded=not urgent_exists):
            _card_grid(sorted(buckets["green"], key=by_due), "grn")

    if buckets["done"]:
        with st.expander(f"✅ הושלמו ({len(buckets['done'])})"):
            _card_grid(buckets["done"], "done")


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
    st.title("🔍 חיפוש מרצים")
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


def show_speaker_index() -> None:
    """The shared board. This is what the opening deck's slide 11 points at:
    check here before approaching anyone, so two pairs never contact the same
    person a week apart without knowing."""
    st.title("👥 מאגר המרצים")
    st.caption(
        "המאגר המשותף לכל הצוותים. **לפני שפונים למישהו — בדקו כאן.** "
        "כל עדכון סטטוס נרשם ביומן ונראה מיד לכל שאר הזוגות."
    )

    c1, c2 = st.columns([2, 1])
    query = c1.text_input("חיפוש לפי שם או תחום", placeholder="למשל: תשובה · קולנוע · תמר")
    only_contacted = c2.checkbox("רק מי שכבר פנינו אליו")

    rows = dm.get_speakers_with_status(only_contacted=only_contacted)
    if query.strip():
        q = dm.normalize_name(query).lower()
        rows = [
            r for r in rows
            if q in dm.normalize_name(r["name"]).lower()
            or q in (r.get("expertise_topics") or "").lower()
            or q in (r.get("notes") or "").lower()
        ]

    contacted = [r for r in rows if r.get("has_outreach")]
    m1, m2, m3 = st.columns(3)
    m1.metric("במאגר", len(rows))
    m2.metric("פנינו אליהם", len(contacted))
    m3.metric("סה״כ במאגר", len(dm.get_speakers_with_status()))

    if not rows:
        st.info("אין התאמות.")
        return

    # Names carried by more than one row are the ה7 situation: several
    # different people share a name and must NOT be merged on our judgment.
    seen: dict[str, int] = {}
    for r in rows:
        seen[r["name"]] = seen.get(r["name"], 0) + 1

    st.divider()
    for r in rows[:60]:
        header = f"{r['name']} — {r.get('current_status') or 'ללא סטטוס'}"
        if seen[r["name"]] > 1:
            header += f"  ⚠️ ({r.get('source_type')})"
        with st.expander(header):
            if seen[r["name"]] > 1:
                st.warning(
                    f"יש {seen[r['name']]} רשומות בשם «{r['name']}» — ככל הנראה "
                    "אנשים שונים. לא מאחדים אותם על דעתנו; ודאו שזה האדם הנכון."
                )
            st.caption(
                f"תחום: {_clean(r.get('expertise_topics') or 'TBD')} · "
                f"שיעור: {r.get('lesson_fit') or 'TBD'} · "
                f"אזור: {r.get('region') or '⚪ לא ידוע'} · "
                f"קשר: {r.get('contact') or 'TBD'}"
            )
            if r.get("notes"):
                st.caption(f"היסטוריה: {_clean(r['notes'])[:220]}")

            history = dm.get_outreach_for_speaker(r["speaker_id"])
            if history:
                st.markdown("**יומן הפניות:**")
                for o in history[:6]:
                    who = o.get("student_name") or "צוות"
                    where = f"משמר #{o['mishmar_id']:02d}" if o.get("mishmar_id") else "—"
                    st.markdown(
                        f"- {o['status']} · {where} · {who} · {(o.get('created_at') or '')[:10]}"
                        + (f" — {_clean(o['note'])}" if o.get("note") else "")
                    )
                if any("לא יכול" in (o["status"] or "") for o in history):
                    st.caption(
                        "↩️ סירוב הוא כמעט תמיד לתאריך מסוים — שווה לנסות שוב בתקופה אחרת."
                    )
            else:
                st.caption("עוד לא פנינו אליו/ה השנה.")

            with st.form(f"outreach-{r['speaker_id']}"):
                cc1, cc2 = st.columns([1, 1])
                new_status = cc1.selectbox("עדכון סטטוס", dm.SPEAKER_STATUSES,
                                           key=f"st-{r['speaker_id']}")
                mine = _my_mishmarim()
                labels = {m["id"]: f"#{m['id']:02d} · {m['gregorian_date']}" for m in mine}
                for_mishmar = cc2.selectbox(
                    "לאיזה משמר?", [None, *labels],
                    format_func=lambda i: "ללא משמר" if i is None else labels[i],
                    key=f"mm-{r['speaker_id']}")
                note = st.text_input("הערה", key=f"nt-{r['speaker_id']}")
                if st.form_submit_button("רשום פנייה"):
                    dm.record_outreach(
                        new_status, speaker_id=r["speaker_id"],
                        mishmar_id=for_mishmar,
                        student_id=st.session_state.student_id,
                        note=note or None)
                    st.toast(f"«{r['name']}» → {new_status}")
                    st.rerun()


LESSON_ROLES = ["יסודות", "ערעור", "טוויסט", "נחיתה", "טקס", "מעגל שירה", "חבורות", "אחר"]
LESSON_FORMATS = ["הרצאה", "חבורות", "דיבייט", "כתיבה", "טד", "ניגון", "טקס", "אחר"]


def _mishmar_picker(key: str) -> Optional[int]:
    mine = _my_mishmarim()
    if not mine:
        st.info("לא משובצים לך משמרים.")
        return None
    labels = {
        m["id"]: f"#{m['id']:02d} · {m['gregorian_date']} · {m.get('topic') or 'ללא נושא'}"
        for m in mine
    }
    return st.selectbox("משמר", list(labels), format_func=lambda i: labels[i], key=key)


def _topic_and_structure(mid: int) -> None:
    m = dm.get_mishmar(mid)
    st.subheader("נושא")
    if m.get("topic"):
        st.success(f"**{_clean(m['topic'])}**")
    else:
        st.caption("הנושא הוא הצעד הראשון — מומלץ לסגור אותו כשלושה שבועות לפני.")
    with st.form(f"topic-{mid}"):
        new_topic = st.text_input("שם הנושא", value=m.get("topic") or "",
                                  placeholder="למשל: כרוניקה של שינוי — האם אדם יכול לשכתב את העבר?")
        if st.form_submit_button("שמור נושא") and new_topic.strip():
            dm.set_mishmar_topic(mid, new_topic.strip())
            # Closing the topic closes its task too, so the board cannot show a
            # topic that is set and a "close the topic" card still open.
            for t in dm.get_tasks_for_mishmar(mid):
                if t.get("category") == "נושא" and t["status"] != "DONE":
                    dm.update_task_status(t["id"], "DONE")
            st.toast(f"הנושא נשמר: {new_topic.strip()}")
            st.rerun()

    st.divider()
    st.subheader("מבנה הערב")
    st.caption(
        "ארבעת השיעורים הם ברירת מחדל מצוינת — לא חוק. טקס, מעגל שירה או "
        "שלושה מקטעים הם מבנים לגיטימיים לגמרי."
    )
    lessons = dm.get_lessons(mid)
    for l in lessons:
        # Surface prior outreach beside the slot, so a pair sees "someone
        # already contacted them" at the moment they are choosing.
        prior = []
        if l.get("speaker_name"):
            for row in dm.get_speaker_status(l["speaker_name"]):
                if row.get("has_outreach"):
                    for o in dm.get_outreach_for_speaker(row["speaker_id"])[:2]:
                        if o.get("mishmar_id") and o["mishmar_id"] != mid:
                            prior.append(
                                f"‼️ פנייה קודמת — משמר #{o['mishmar_id']:02d} · {o['status']}")
        with st.expander(
            f"{l['slot_order']}. {l.get('start_time') or '--:--'} · "
            f"{l.get('title') or 'ללא כותרת'}"
            + (f" · {l['speaker_name']}" if l.get("speaker_name") else "")
            + (f"  {l['speaker_status']}" if l.get("speaker_status") else ""),
        ):
            for line in prior:
                st.warning(line)
            with st.form(f"lesson-{l['id']}"):
                c1, c2 = st.columns(2)
                title = c1.text_input("כותרת", value=l.get("title") or "")
                start = c2.text_input("שעה", value=l.get("start_time") or "")
                c3, c4 = st.columns(2)
                role = c3.selectbox(
                    "תפקיד בערב", LESSON_ROLES,
                    index=LESSON_ROLES.index(l["lesson_role"]) if l.get("lesson_role") in LESSON_ROLES else len(LESSON_ROLES) - 1)
                fmt = c4.selectbox(
                    "פורמט", LESSON_FORMATS,
                    index=LESSON_FORMATS.index(l["format"]) if l.get("format") in LESSON_FORMATS else len(LESSON_FORMATS) - 1)
                c5, c6 = st.columns(2)
                speaker = c5.text_input("מרצה", value=l.get("speaker_name") or "")
                cur = l.get("speaker_status") or dm.SPEAKER_STATUSES[0]
                status = c6.selectbox(
                    "סטטוס פנייה", dm.SPEAKER_STATUSES,
                    index=dm.SPEAKER_STATUSES.index(cur) if cur in dm.SPEAKER_STATUSES else 0,
                    help="נרשם ביומן הפניות המשותף — כל זוג אחר יראה שפניתם.",
                )
                desc = st.text_area("תיאור", value=l.get("description") or "")
                cc1, cc2 = st.columns([1, 1])
                if cc1.form_submit_button("שמור"):
                    try:
                        dm.upsert_lesson(
                            mid, l["slot_order"], title=title, start_time=start,
                            description=desc, lesson_role=role,
                            speaker_name=speaker, speaker_status=status, fmt=fmt,
                            student_id=st.session_state.student_id)
                        st.toast("המקטע נשמר · הסטטוס נרשם במאגר המשותף")
                    except dm.AmbiguousSpeaker as exc:
                        st.warning(
                            f"יש {len(exc.candidates)} אנשים בשם «{exc.name}» במאגר. "
                            "בחרו את הנכון במסך «מאגר המרצים» — לא נאחד אותם אוטומטית."
                        )
                    st.rerun()
                if cc2.form_submit_button("מחק מקטע"):
                    dm.delete_lesson(l["id"]); st.toast("נמחק"); st.rerun()

    if st.button("➕ הוסף מקטע"):
        dm.upsert_lesson(mid, len(lessons) + 1, title="מקטע חדש")
        st.rerun()
    if not lessons and st.button("התחל מארבעת השיעורים"):
        for i, (t, hh, role) in enumerate(
            [("היסודות", "20:30", "יסודות"), ("העומק והערעור", "22:00", "ערעור"),
             ("הזווית המפתיעה", "23:30", "טוויסט"), ("נחיתה אל הלב", "01:00", "נחיתה")], 1):
            dm.upsert_lesson(mid, i, title=t, start_time=hh, lesson_role=role)
        st.rerun()


def _tasks_tab(mid: int) -> None:
    tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_mishmar(mid)]
    titles = {"TO DO": "לעשות", "IN PROGRESS": "בתהליך", "DONE": "הושלם"}
    cols = st.columns(len(dm.TASK_STATUSES))
    for col, status in zip(cols, dm.TASK_STATUSES):
        bucket = [t for t in tasks if t["status"] == status]
        with col:
            st.subheader(f"{titles[status]} ({len(bucket)})")
            for t in sorted(bucket, key=lambda x: x.get("due_date") or "9999"):
                badge = ""
                if t.get("nudge"):
                    badge = f"<div class='meta'>{'❗' if t['overdue'] else '🕒'} {t['nudge']}</div>"
                elif t.get("due_date"):
                    badge = f"<div class='meta'>מומלץ עד {t['due_date']}</div>"
                st.markdown(
                    f"<div class='kanban-card'>{_clean(t['task_description'])}"
                    f"<div class='meta'>{t.get('category') or ''}</div>{badge}</div>",
                    unsafe_allow_html=True)
                targets = [x for x in dm.TASK_STATUSES if x != status]
                bc = st.columns(len(targets))
                for b, target in zip(bc, targets):
                    if b.button(f"→ {titles[target]}", key=f"m{mid}-{t['id']}-{target}"):
                        dm.update_task_status(t["id"], target); st.rerun()

    st.divider()
    with st.form(f"addtask-{mid}"):
        c1, c2 = st.columns([3, 1])
        desc = c1.text_input("משימה חדשה")
        cat = c2.selectbox("קטגוריה", ["(אוטומטי)"] + list(dm.TASK_CATEGORIES))
        if st.form_submit_button("הוסף") and desc.strip():
            dm.add_task(mid, desc.strip(),
                        category=None if cat == "(אוטומטי)" else cat)
            st.toast("נוספה משימה"); st.rerun()


def _after_tab(mid: int) -> None:
    m = dm.get_mishmar(mid)
    lessons = dm.get_lessons(mid)
    speakers = [l["speaker_name"] for l in lessons if l.get("speaker_name")]

    # A speaker recorded only on a budget line — someone who came but was never
    # added to the running order — must still be reviewable, or their feedback
    # is unreachable and never reaches the index.
    for name in dm.get_budget_speaker_names(mid):
        if name not in speakers:
            speakers.append(name)

    st.subheader("סיכום תקציב")
    st.caption(
        f"האינדיקציה היא {dm.PER_MISHMAR_BUDGET_NIS} ₪ למשמר — ממוצע שכולל מרצים "
        "וכיבוד יחד. חריגה במשמר בודד אינה שגיאה: היא נמשכת מהסעיף העונתי."
    )
    with st.form(f"budget-{mid}"):
        st.markdown("**מרצים שהגיעו ומה שולם להם** *(0 = הגיע בהתנדבות)*")
        paid = {}
        for i, name in enumerate(speakers):
            paid[name] = st.number_input(f"{name} (₪)", min_value=0.0, step=50.0, key=f"pay-{mid}-{i}")
        if not speakers:
            st.caption("לא רשומים מרצים במבנה הערב — אפשר להוסיף אותם בלשונית «נושא ומבנה».")
        extra_name = st.text_input("מרצה נוסף שלא מופיע למעלה")
        extra_amt = st.number_input("תשלום למרצה הנוסף (₪)", min_value=0.0, step=50.0)
        refreshments = st.number_input("כיבוד (₪)", min_value=0.0, step=10.0)
        other = st.number_input("הוצאות אחרות (₪)", min_value=0.0, step=10.0)
        if st.form_submit_button("שמור סיכום תקציב"):
            n = 0
            for name, amt in paid.items():
                dm.add_budget_entry(mid, "מרצה", actual_cost=amt, description=name); n += 1
            if extra_name.strip():
                dm.add_budget_entry(mid, "מרצה", actual_cost=extra_amt, description=extra_name.strip()); n += 1
            if refreshments:
                dm.add_budget_entry(mid, "כיבוד", actual_cost=refreshments, description="כיבוד"); n += 1
            if other:
                dm.add_budget_entry(mid, "אחר", actual_cost=other, description="אחר"); n += 1
            st.toast(f"נשמרו {n} שורות תקציב"); st.rerun()

    spent = (m or {}).get("budget_used") or 0
    st.metric("סה״כ הוצאות למשמר הזה", _fmt_nis(spent))
    if spent > dm.PER_MISHMAR_BUDGET_NIS:
        st.info("מעל האינדיקציה — לידיעה, לא לדאגה.")

    st.divider()
    st.subheader("משוב")
    st.caption(
        "המשוב הוא מה שהופך את מאגר המרצים מרשימת שמות לזיכרון מוסדי — "
        "החניך של השנה הבאה יראה לא רק שמישהו לימד כאן, אלא איך זה הלך."
    )
    with st.form(f"feedback-{mid}"):
        # Explicit parens: "a + b if c else d" parses as "(a+b) if c else d",
        # which happens to be right here but reads as if it is not.
        target = st.selectbox("על מה המשוב?", [*speakers, "המשמר בכללותו"])
        rating = st.slider("דירוג", 1, 5, 4)
        worked = st.text_area("מה עבד")
        didnt = st.text_area("מה פחות עבד")
        if st.form_submit_button("שמור משוב"):
            dm.add_feedback(
                mid, rating=rating,
                speaker_name=None if target == "המשמר בכללותו" else target,
                student_id=st.session_state.student_id,
                what_worked=worked or None, what_didnt=didnt or None)
            st.toast("המשוב נשמר"); st.rerun()

    existing = dm.get_feedback_for_mishmar(mid)
    if existing:
        st.markdown("**משוב שנרשם:**")
        for f in existing:
            who = f.get("speaker_name") or "המשמר בכללותו"
            st.markdown(f"- **{_clean(who)}** — {'⭐' * (f.get('rating') or 0)}")
            if f.get("what_worked"):
                st.caption(f"עבד: {_clean(f['what_worked'])}")
            if f.get("what_didnt"):
                st.caption(f"פחות: {_clean(f['what_didnt'])}")


def show_mishmar_page() -> None:
    st.title("📋 ניהול המשמר")
    mid = _mishmar_picker("workfile_mishmar")
    if not mid:
        return
    m = dm.get_mishmar(mid)
    st.caption(
        f"#{m['id']:02d} · {m['gregorian_date']} · {m['hebrew_date']} · "
        f"{m.get('mishmar_type') or 'סוג לא נקבע'}"
        + (f" · {m['note']}" if m.get("note") else "")
    )
    t1, t2, t3 = st.tabs(["נושא ומבנה", "משימות", "אחרי המשמר"])
    with t1:
        _topic_and_structure(mid)
    with t2:
        _tasks_tab(mid)
    with t3:
        _after_tab(mid)


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


def _message_text(content) -> str:
    """Readable text for one chat turn.

    The live history holds what the API needs, not what a person reads: an
    assistant turn is a LIST of content blocks (text, thinking, tool_use), and
    a tool-result turn is a list of result blocks. Rendering only `str` content
    silently dropped every assistant reply the moment the page reran — the
    trainee watched the answer stream in and then vanish.
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = getattr(block, "type", None)
        if kind is None and isinstance(block, dict):
            kind = block.get("type")
        if kind != "text":
            continue          # thinking and tool plumbing are not shown
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def render_chat_panel() -> None:
    """The global assistant — a persistent panel beside EVERY page.

    This is the redesign's core move: the chat is no longer a page you visit,
    it is a companion to whatever screen is open. A trainee can stand in the
    speaker index, say "סגרתי עם X", and watch the index update — the turn
    ends with st.rerun(), so the main column re-renders from fresh rows.

    The panel is drawn AFTER the main column in code, which keeps the page
    visible while the answer streams in.
    """
    head, close = st.columns([6, 1])
    head.markdown(
        "<div class='chat-head'>💬 שותף הבנייה"
        "<small>מחובר ללוח החי</small></div>",
        unsafe_allow_html=True,
    )
    if close.button("✕", key="chat_close", help="קפל את הצ׳אט"):
        st.session_state["chat_open"] = False
        st.rerun()

    mine = _my_mishmarim()
    if not mine:
        st.caption("לא משובצים לך משמרים עדיין — אין על מה לשוחח.")
        return

    labels = {
        m["id"]: f"#{m['id']:02d} · {m['gregorian_date']} · "
                 f"{(m.get('topic') or 'ללא נושא')[:24]}"
        for m in mine
    }
    chosen = st.selectbox(
        "על איזה משמר עובדים?", options=list(labels),
        format_func=lambda i: labels[i], key="chat_mishmar",
        label_visibility="collapsed",
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

    history = st.session_state.setdefault("chat_history", [])

    # Fixed height => the panel scrolls internally instead of stretching the page.
    box = st.container(height=460)
    with box:
        if not history:
            st.caption(
                "אני מחובר ללוח: מה שתספרו לי — אני מעדכן, ותראו את זה מיד במסך.\n\n"
                "אפשר להתחיל ב:\n"
                "- «עזור לי לבחור נושא»\n"
                "- «מצא מרצה לשיעור הראשון»\n"
                "- «סגרתי עם תמר כהן — תרשום»"
            )
        for msg in history:
            text = _message_text(msg["content"])
            if not text:
                continue   # tool-result turns carry no prose to show
            with st.chat_message(msg["role"]):
                st.markdown(text)

    prompt = st.chat_input("ספרו לי מה קורה — אני אעדכן את הלוח", key="global_chat")
    if not prompt:
        return

    ctx = ca.build_context(st.session_state.student_id, chosen)
    history.append({"role": "user", "content": prompt})
    dm.add_chat_message("user", prompt, mishmar_id=chosen,
                        student_id=st.session_state.student_id)

    with box:
        with st.chat_message("user"):
            st.markdown(prompt)
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
    # THE point of the global panel: re-render the page the trainee is looking
    # at, so a change the chat wrote (task closed, outreach logged) is visible
    # on the main column immediately.
    st.rerun()


# --------------------------------------------------------------------------
# 5. Sidebar + routing
# --------------------------------------------------------------------------


NAV_WORKFILE = "📋 ניהול המשמר"
NAV_INDEX = "👥 מאגר המרצים"
NAV_SEARCH = "🔍 חיפוש מרצים"


def show_sidebar() -> None:
    with st.sidebar:
        name = st.session_state.user_name or ""
        st.markdown(
            f"<div class='side-avatar'>{_clean(name[:1]) or '·'}</div>"
            f"<div style='font-weight:800;font-size:1.05rem'>{_clean(name)}</div>"
            f"<div style='opacity:.6;font-size:.8rem'>"
            f"{'מדריך · אדמין' if st.session_state.role == 'admin' else 'חניך · שנה ב׳'}"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        home = "🎛️ לוח הבקרה" if st.session_state.role == "admin" else "🏠 מסך הבית שלי"
        st.radio("ניווט", [home, NAV_WORKFILE, NAV_INDEX, NAV_SEARCH],
                 key="nav", label_visibility="collapsed")
        st.divider()
        st.caption('🕯️ שנה ב׳ · תשפ״ז · 5787')
        if st.button("התנתק", width="stretch"):
            logout()
            st.rerun()


def _route_main() -> None:
    nav = st.session_state.get("nav") or ""
    if nav == NAV_WORKFILE:
        show_mishmar_page()
    elif nav == NAV_INDEX:
        show_speaker_index()
    elif nav == NAV_SEARCH:
        show_speaker_search()
    elif st.session_state.role == "admin":
        show_admin_dashboard()
    else:
        show_student_view(st.session_state.user_name)


def main() -> None:
    inject_rtl()
    _init_session()

    info = bootstrap()
    if not info.get("storage_ok"):
        st.title("🕯️ ניהול משמרים")
        # The probe already identified WHICH of the failure modes this is, so
        # it leads. The general checklist folds away underneath — printing
        # "run the schema" first sends people to the SQL Editor for a problem
        # that is usually the URL or the key.
        st.error(info.get("reason") or "אין חיבור לאחסון.")
        with st.expander("הרשימה המלאה — כל מה שצריך להיות מוגדר"):
            st.markdown(
                "1. `SUPABASE_URL` — **כתובת הפרויקט בלבד**, "
                "`https://<project-ref>.supabase.co`, בלי `/rest/v1`.\n"
                "2. `SUPABASE_KEY` — מפתח ה-**service_role** (לא anon; "
                "RLS מופעל ולכן anon ייחסם).\n"
                "3. `supabase_schema.sql` הורץ ב-Supabase → SQL Editor.\n\n"
                "שלושתם ב-Secrets של Streamlit. ההוראות המלאות ב-`DEPLOY.md`."
            )
        return
    if info.get("seeded"):
        st.toast(
            f"הועברו למסד: {info['tasks']} משימות · {info['mishmarim']} משמרים. "
            f"הקובץ נגנז."
        )

    if st.session_state.role is None:
        show_login()
        return

    show_sidebar()

    # The global layout. Under RTL st.columns mirrors, so declaring
    # [main, chat] renders the MAIN column on the right — Hebrew reading
    # order — and the chat as the fixed LEFT panel. Collapsed, the panel
    # shrinks to a slim column holding only the reopen bubble, so the
    # assistant is never more than one click away on any screen.
    chat_open = st.session_state.setdefault("chat_open", True)
    if chat_open:
        main_col, chat_col = st.columns([2.4, 1.1], gap="medium")
    else:
        main_col, chat_col = st.columns([14, 1], gap="small")

    with main_col:
        _route_main()
    with chat_col:
        if chat_open:
            render_chat_panel()
        elif st.button("💬", key="chat_reopen", help="פתח את שותף הבנייה"):
            st.session_state["chat_open"] = True
            st.rerun()


if __name__ == "__main__":
    main()
