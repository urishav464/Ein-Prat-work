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
    page_title='משמרים · המדרשה הגבוהה · תשפ"ז',
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
  @import url('https://fonts.googleapis.com/css2?family=Rubik:wght@500;700;800&family=Assistant:wght@400;600;700&display=swap');
  html, body, .stApp, [class^="st-"], button, input, textarea, select {
      font-family: 'Assistant', 'Segoe UI', system-ui, -apple-system, sans-serif !important;
  }
  /* The override above must NOT reach Streamlit's icon glyphs — they are
     ligature text ("keyboard_arrow_down") that renders literally without
     the Material font. */
  [data-testid="stIconMaterial"], span[class*="material-symbols"] {
      font-family: 'Material Symbols Rounded' !important;
  }
  h1, h2, h3, h4 {
      font-family: 'Rubik', 'Assistant', sans-serif !important;
      font-weight: 800 !important;
      letter-spacing: -0.01em;
      color: #1d3e7d !important;
  }

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
      background: #ebe4d3;
      border-inline-end: 1px solid #d9cfb8;
  }
  /* Collapse under RTL: Streamlit's collapse animation translates the panel
     toward the LEFT while our layout holds it on the RIGHT, leaving a broken
     1px strip of letter-stacked nav in mid-screen. Kill the remnants: hide
     the content the moment the sidebar reports collapsed, and give the
     content a minimum width so mid-animation text never letter-wraps. */
  [data-testid="stSidebarContent"] { min-width: 244px; }
  section[data-testid="stSidebar"][aria-expanded="false"] {
      width: 0 !important;
      min-width: 0 !important;
      overflow: hidden !important;
      border: none !important;
  }
  section[data-testid="stSidebar"][aria-expanded="false"] * { display: none !important; }
  /* every control in the sidebar tracks its full width */
  [data-testid="stSidebar"] .stButton button,
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { width: 100%; }
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
      border-color: #1d3e7d;
      transform: translateX(-2px);
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
      background: linear-gradient(135deg, #e7edf9, #dbe5f6);
      border-color: #1d3e7d;
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
      background: linear-gradient(135deg, #1d3e7d, #2c56a4);
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
      background: linear-gradient(135deg, #16305f, #1d3e7d);
      color: #eef2fb;
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
      background: #e7edf9;
      border-color: #ccd9f0;
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
      border: 1px solid #1d3e7d;
      background: #e7edf9;
      box-shadow: 0 2px 8px rgba(20,40,80,.18);
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
  .chip-blue   { background: #e7edf9; color: #1d3e7d; }

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
  .step.current .dot { background: #e7edf9; border-color: #1d3e7d;
                       box-shadow: 0 0 0 4px rgba(29,62,125,.18); }
  .step.current { color: #2f2a1d; font-weight: 700; }
  .step-bar { flex: 1 1 auto; height: 3px; background: #e4ddcb;
              margin: 16px 2px 0; border-radius: 2px; min-width: 10px; }
  .step-bar.done { background: #137333; }

  /* ---- Mobile: Streamlit stacks columns by itself below ~640px; these
     rules keep OUR custom pieces usable on a phone. The chat column stacks
     under the content (flex order), the stepper compresses, chips wrap. ---- */
  @media (max-width: 740px) {
      .stepper { flex-wrap: nowrap; overflow-x: auto; }
      .step { min-width: 48px; font-size: .62rem; }
      .step .dot { width: 26px; height: 26px; font-size: .78rem; }
      .chip { font-size: .66rem; padding: 1px 7px; }
      .chat-head small { display: none; }
      h1 { font-size: 1.5rem !important; }
      [data-testid="stChatMessage"] { padding: .5rem .7rem; }
      .block-container { padding-left: .8rem; padding-right: .8rem; }
  }

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


APP_TITLE = 'משמרים · המדרשה הגבוהה · תשפ"ז'


def _login_frame():
    """A centered, card-shaped login — not a form stuck to one side."""
    _, mid, _ = st.columns([1, 1.15, 1])
    box = mid.container(border=True)
    with box:
        st.markdown(
            f"<div style='text-align:center;padding:.6rem 0 .1rem'>"
            f"<div style='font-size:2.2rem'>🕯️</div>"
            f"<div style='font-family:Rubik,Assistant,sans-serif;font-weight:800;"
            f"font-size:1.45rem;color:#1d3e7d'>{APP_TITLE}</div>"
            f"<div style='opacity:.6;font-size:.85rem'>מדרשת עין פרת</div></div>",
            unsafe_allow_html=True,
        )
    return box


def show_google_login() -> None:
    box = _login_frame()
    if not getattr(st.user, "is_logged_in", False):
        with box:
            st.button("כניסה עם Google", on_click=st.login,
                      width="stretch", type="primary")
            st.caption("היכנסו עם חשבון הגוגל שאיתו נרשמתם אצל המדריך.")
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

    box = _login_frame()
    students = dm.get_students()
    student_names = [s["name"] for s in students if s["role"] == "student"]

    with box:
        with st.form("login", border=False):
            name = st.text_input("השם שלך", placeholder="למשל: חניך 3",
                                 label_visibility="collapsed")
            submitted = st.form_submit_button("כניסה", width="stretch",
                                              type="primary")
        with st.expander("מצב פיתוח — פרטים"):
            st.caption(
                "**ללא אימות**: ההזדהות היא בשם בלבד. מי שמקליד «Uri» מקבל "
                "גישה מלאה. להרצה מקומית בלבד — לפריסה הגדירו `[auth]` "
                "ב-Secrets וההתחברות תעבור ל-Google."
            )
            if student_names:
                st.caption("שמות רשומים: " + " · ".join(student_names))

    if not submitted:
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

    _, mid2, _ = st.columns([1, 1.15, 1])
    with mid2:
        st.error(f"לא מצאתי את «{typed}» ברשימת החניכים.")
        if student_names:
            st.caption("השמות התקפים: " + " · ".join(student_names))


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


def _pipeline_row(m: dict, progress: dict, overdue_count: int) -> None:
    """One Mishmar in the instructor's pipeline: identity · phase · progress."""
    cur = progress["phases"][progress["current"]]
    phase_chip = _chip(f"{cur['icon']} {cur['label']}", "gold")
    owners_chip = _chip("צוות" if m.get("is_staff_built") else "זוג חניכים", "gray")
    over_chip = _chip(f"{overdue_count} באיחור", "red") if overdue_count else ""
    topic = _clean(m.get("topic") or "") or "<span style='opacity:.5'>ללא נושא</span>"
    with st.container(border=True):
        c1, c2 = st.columns([2.6, 1.4])
        c1.markdown(
            f"<div class='task-desc'>#{m['id']:02d} · {_fmt_date(m['gregorian_date'])} · "
            f"{topic}</div>"
            f"<div>{_countdown_chip(m)}{phase_chip}{owners_chip}{over_chip}</div>",
            unsafe_allow_html=True,
        )
        with c2:
            if progress["total"]:
                st.progress(progress["pct"],
                            text=f"{progress['done']}/{progress['total']}")
            else:
                st.caption("ללא משימות")


def show_admin_dashboard() -> None:
    st.title("🎛️ לוח הבקרה")
    st.caption('כל 21 המשמרים · שנה ב׳ תשפ״ז · מבט מדריך')

    mishmarim = dm.get_all_mishmarim()
    budget = dm.get_budget_summary()
    if not mishmarim:
        st.info("אין עדיין נתונים במסד. ודא שההגירה מ-`students_tasks.md` רצה.")
        return

    # One query for every task; everything below derives from it in Python.
    all_tasks = dm.get_all_tasks()
    by_mid: dict[int, list[dict]] = {}
    for t in all_tasks:
        by_mid.setdefault(t["mishmar_id"], []).append(t)
    progress = {m["id"]: dm.mishmar_progress(mishmar=m, tasks=by_mid.get(m["id"], []))
                for m in mishmarim}

    with_topic = [m for m in mishmarim if m.get("topic")]
    done_all = sum(p["done"] for p in progress.values())
    total_all = sum(p["total"] for p in progress.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🕯️ משמרים", len(mishmarim))
    c2.metric("🎯 עם נושא סגור", f"{len(with_topic)} / {len(mishmarim)}")
    c3.metric("💰 סה״כ הוצאות", _fmt_nis(budget["total_spent"]))
    c4.metric("📊 אינדיקציה למשמר", _fmt_nis(budget["nominal_per_mishmar"]))
    if total_all:
        st.progress(done_all / total_all,
                    text=f"התקדמות העונה: {done_all}/{total_all} משימות הושלמו")

    st.divider()
    st.subheader("🔴 עבר את התאריך המומלץ")
    overdue = dm.get_overdue_tasks()
    over_by_mid: dict[int, int] = {}
    for t in overdue:
        over_by_mid[t["mishmar_id"]] = over_by_mid.get(t["mishmar_id"], 0) + 1
    if not overdue:
        st.success("שום משימה לא עברה את התאריך המומלץ שלה.")
    else:
        st.caption(
            f"{len(overdue)} משימות פתוחות עברו את התאריך המומלץ. "
            "לחניכים זה מוצג כתזכורת רכה — כאן זה מוצג כדי שתדע איפה להתערב."
        )
        cards = [dm.annotate_deadline(t) for t in overdue]
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
                            f"{_fmt_date(t['gregorian_date'])} · {_clean(t.get('nudge') or '')}</div>",
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

    # ---- The pipeline: what the flat table never told anyone ----
    st.divider()
    st.subheader("📅 צינור המשמרים")
    st.caption("כל משמר, איפה הוא עומד בבנייה, ומי מחזיק אותו. לפי סדר הערבים.")
    today = _date_cls.today()
    upcoming = [m for m in mishmarim
                if (_parse_date(m.get("gregorian_date")) or today) >= today]
    past = [m for m in mishmarim if m not in upcoming]
    for m in upcoming:
        _pipeline_row(m, progress[m["id"]], over_by_mid.get(m["id"], 0))
    if past:
        with st.expander(f"🌙 משמרים שהתקיימו ({len(past)})"):
            for m in reversed(past):
                _pipeline_row(m, progress[m["id"]], over_by_mid.get(m["id"], 0))

    with st.expander("📊 התקדמות לפי חניך"):
        st.caption("משימה של זוג נספרת לשני החניכים — במכוון. זה מבט אחריות, לא חשבונאות.")
        prow = []
        for r in dm.get_student_progress():
            total = r["tasks_total"] or 0
            done = r["tasks_done"] or 0
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


WF_SECTIONS = ["🎯 בניית הערב", "✅ משימות", "🌙 אחרי המשמר"]


def _goto(nav: str, mishmar_id: Optional[int] = None,
          section: Optional[str] = None, lesson_focus: Optional[int] = None) -> None:
    """Deep-link navigation. STAGED, not direct: Streamlit forbids writing a
    widget's session key after that widget was drawn in the current run, and
    the nav radio always draws before any button that calls this. So the
    request is parked under one key and applied at the very top of main(),
    before a single widget exists. This is what turns «התחל» from a status
    button into a door to the right place."""
    st.session_state["_goto_req"] = {
        "nav": nav, "workfile_mishmar": mishmar_id,
        "wf_section": section, "wf_focus_lesson": lesson_focus,
    }
    st.rerun()


def _apply_goto() -> None:
    """First thing in main(): land any staged deep link while no widget exists."""
    req = st.session_state.pop("_goto_req", None)
    if not req:
        return
    st.session_state["nav"] = req["nav"]
    if req.get("workfile_mishmar") is not None:
        st.session_state["workfile_mishmar"] = req["workfile_mishmar"]
    if req.get("wf_section") is not None:
        st.session_state["wf_section"] = req["wf_section"]
    st.session_state["wf_focus_lesson"] = req.get("wf_focus_lesson")


def _parse_date(value) -> Optional[_date_cls]:
    """Both date shapes that live in this schema: tasks.due_date is a real DATE
    (ISO out of PostgREST), but mishmarim.gregorian_date is TEXT in the repo's
    d.m.Y convention ('15.10.2026') — an ISO-only parse silently returned None
    for every Mishmar date and every countdown chip vanished."""
    raw = str(value or "").strip()
    try:
        return _date_cls.fromisoformat(raw[:10])
    except ValueError:
        pass
    try:
        d, m, y = raw.split(".")
        return _date_cls(int(y), int(m), int(d))
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


def _section_for_category(category: Optional[str]) -> str:
    if category in ("נושא", "מרצים", "תוכן"):
        return WF_SECTIONS[0]      # בניית הערב
    if category == "אחרי":
        return WF_SECTIONS[2]      # אחרי המשמר
    return WF_SECTIONS[1]          # משימות


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


def _task_card(t: dict, key_prefix: str, show_mishmar: bool = True,
               link: bool = False) -> None:
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
            if link:
                # «התחל» is a DOOR, not a status flip: it lands on the section
                # of the workfile where this task is actually done.
                if b2.button("פתח ↗", key=f"{key_prefix}-{t['id']}-go",
                             help="פותח את המקום שבו סוגרים את המשימה"):
                    _goto(NAV_WORKFILE, t.get("mishmar_id"),
                          _section_for_category(t.get("category")))
            else:
                other = ("↩ לעשות", "TO DO") if status == "IN PROGRESS" else ("▶ התחל", "IN PROGRESS")
                if b2.button(other[0], key=f"{key_prefix}-{t['id']}-mv"):
                    dm.update_task_status(t["id"], other[1]); st.rerun()


def _card_grid(items: list[dict], key_prefix: str, per_row: int = 2,
               show_mishmar: bool = True, link: bool = False) -> None:
    # st.columns mirrors under RTL, so the first card of each row lands on the
    # RIGHT — Hebrew reading order — with no extra work here.
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, t in zip(cols, items[i:i + per_row]):
            with col:
                _task_card(t, key_prefix, show_mishmar=show_mishmar, link=link)


def _stepper_html(progress: dict) -> str:
    """The four phases as a horizontal stepper. RTL flex puts phase 1 on the
    right, where a Hebrew reader starts — no reversal needed here."""
    parts = ["<div class='stepper'>"]
    for i, ph in enumerate(progress["phases"]):
        cls = "done" if ph["complete"] else ("current" if i == progress["current"] else "")
        count = f"{ph['done']}/{ph['total']}" if ph["total"] else "—"
        parts.append(
            f"<div class='step {cls}'><div class='dot'>"
            f"{'✓' if ph['complete'] else ph['icon']}</div>"
            f"<div>{ph['label']}</div><div style='opacity:.55'>{count}</div></div>"
        )
        if i < len(progress["phases"]) - 1:
            parts.append(f"<div class='step-bar {'done' if ph['complete'] else ''}'></div>")
    parts.append("</div>")
    return "".join(parts)


def _countdown_chip(m: dict) -> str:
    d = _parse_date(m.get("gregorian_date"))
    if not d:
        return ""
    days = (d - _date_cls.today()).days
    if days < 0:
        return _chip("התקיים", "gray")
    if days == 0:
        return _chip("הערב!", "red")
    kind = "red" if days <= 7 else ("yellow" if days <= 14 else "green")
    return _chip(f"בעוד {days} ימים", kind)


def _next_mishmar_hero(m: dict, progress: dict) -> None:
    """The trainee's ONE place to answer "what now?" — Mishmar identity,
    the phase stepper, and only the current phase's open tasks."""
    cur = progress["phases"][progress["current"]]
    with st.container(border=True):
        chips = [_countdown_chip(m)]
        if m.get("mishmar_type"):
            chips.append(_chip(m["mishmar_type"], "gold"))
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap'>"
            f"<span style='font-size:1.25rem;font-weight:800'>🕯️ משמר #{m['id']:02d}</span>"
            f"<span style='opacity:.7'>{m['gregorian_date']} · {m['hebrew_date']}</span>"
            f"<span>{''.join(c for c in chips if c)}</span></div>",
            unsafe_allow_html=True,
        )
        if m.get("topic"):
            st.markdown(f"**הנושא:** {_clean(m['topic'])}")

        st.markdown(_stepper_html(progress), unsafe_allow_html=True)
        if progress["total"]:
            st.progress(progress["pct"],
                        text=f"{progress['done']}/{progress['total']} משימות הושלמו")

        nxt = progress.get("next_task")
        if nxt:
            nc1, nc2 = st.columns([4.2, 1])
            nc1.markdown(
                f"<div style='background:#e7edf9;border-radius:10px;"
                f"padding:.55rem .9rem;margin:.3rem 0 .5rem'>"
                f"⭐ <b>הצעד הבא:</b> {_clean(nxt['task_description'])}"
                + (f" <span class='card-meta'>מומלץ עד {_fmt_date(nxt['due_date'])}</span>"
                   if nxt.get("due_date") else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            if nc2.button("פתח ↗", key=f"next-{m['id']}", type="primary"):
                _goto(NAV_WORKFILE, m["id"],
                      _section_for_category(nxt.get("category")))

        open_cur = [t for t in cur["tasks"] if t["status"] != "DONE"]
        if open_cur:
            st.markdown(f"**המשימות של שלב «{cur['label']}» ({len(open_cur)}):**")
            _card_grid(sorted(open_cur, key=lambda t: t.get("due_date") or "9999"),
                       f"hero-{m['id']}", show_mishmar=False, link=True)
            # A teaser, not a list: the next phase exists, and it can wait.
            ni = progress["current"] + 1
            if ni < len(progress["phases"]):
                np = progress["phases"][ni]
                if np["total"]:
                    st.caption(
                        f"🔒 אחרי שלב «{cur['label']}» ייפתח שלב "
                        f"«{np['label']}» — {np['total']} משימות מחכות שם בשקט."
                    )
        elif progress["total"]:
            st.success("כל המשימות של השלב הנוכחי סגורות. 🎉")


def _mini_mishmar_card(m: dict, progress: dict) -> None:
    cur = progress["phases"][progress["current"]]
    phase_chip = _chip(f"{cur['icon']} {cur['label']}", "gold")
    with st.container(border=True):
        st.markdown(
            f"<div class='task-desc'>#{m['id']:02d} · {_fmt_date(m['gregorian_date'])}</div>"
            f"<div>{_countdown_chip(m)}{phase_chip}</div>",
            unsafe_allow_html=True,
        )
        if progress["total"]:
            st.progress(progress["pct"],
                        text=f"{progress['done']}/{progress['total']}")


def show_student_view(student_name: str) -> None:
    student_id = st.session_state.student_id
    st.title(f"🏠 שלום, {student_name}")

    mine = dm.get_mishmarim_for_student(student_id)
    if not mine:
        st.info("עוד לא משובצים לך משמרים.")
        return

    all_tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_student(student_id)]
    by_mid: dict[int, list[dict]] = {}
    for t in all_tasks:
        by_mid.setdefault(t["mishmar_id"], []).append(t)
    progress = {m["id"]: dm.mishmar_progress(mishmar=m, tasks=by_mid.get(m["id"], []))
                for m in mine}

    # The hero is the next Mishmar on the calendar; past ones fall to the strip.
    today = _date_cls.today()
    upcoming = [m for m in mine
                if (_parse_date(m.get("gregorian_date")) or today) >= today]
    # Sort by the PARSED date. gregorian_date is d.m.Y text, and a string min()
    # puts 15.10 before 8.10 — the "wrong next Mishmar" bug.
    hero = (min(upcoming, key=lambda m: _parse_date(m["gregorian_date"]) or today)
            if upcoming else mine[-1])

    # Overdue anywhere is the one thing allowed to jump the phase queue.
    overdue = [t for t in all_tasks
               if t.get("overdue") and t["mishmar_id"] != hero["id"]]
    if overdue:
        st.markdown(f"#### 🔴 עבר התאריך המומלץ במשמרים אחרים ({len(overdue)})")
        st.caption("המלצה — לא חוק. אבל אלה קודמים לכל השאר.")
        _card_grid(sorted(overdue, key=lambda t: t.get("due_date") or "9999"),
                   "ovd", link=True)

    st.markdown("#### ⭐ המשמר הבא שלי")
    _next_mishmar_hero(hero, progress[hero["id"]])

    others = [m for m in mine if m["id"] != hero["id"]]
    if others:
        st.markdown("#### 🕯️ שאר המשמרים שלי")
        st.caption("הם מחכים בתור — כל אחד ייפתח כשיגיע זמנו. הצ׳אט וקובץ העבודה פתוחים לכולם תמיד.")
        cols = st.columns(min(3, max(1, len(others))))
        for i, m in enumerate(others):
            with cols[i % len(cols)]:
                _mini_mishmar_card(m, progress[m["id"]])

    done = [t for t in all_tasks if t["status"] == "DONE"]
    if done:
        with st.expander(f"✅ הושלמו ({len(done)})"):
            _card_grid(done, "done")


def _speaker_card(entry: dict, topic: str, lesson: str, idx: int) -> None:
    """One raw mined name (pre-synthesis / fallback view): confidence, flags,
    evidence, and the explicit add-to-index action. Restored — it was dropped
    by mistake in the dashboard rewrite, unnoticed because sandbox tests never
    have web names to render."""
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


def _scout_card(c: dict, mid: Optional[int], lesson: str, idx: int) -> None:
    """One curated candidate: identity, provenance, warnings, and the write."""
    name = c["name"]
    display = f"{c['title']} {name}" if c.get("title") else name
    with st.container(border=True):
        chips = []
        chips.append(_chip("📗 מהמאגר", "green") if c.get("source") == "index"
                     else _chip("🌐 מהרשת", "blue"))
        if c.get("index_status"):
            chips.append(_speaker_status_chip(c["index_status"]))
        for f in c.get("flags", []):
            chips.append(_chip(f, "yellow"))
        st.markdown(
            f"<div class='task-desc'>{_clean(display)}</div><div>{''.join(chips)}</div>",
            unsafe_allow_html=True,
        )
        if c.get("already_approached"):
            st.warning("‼️ כבר פנו לאדם הזה השנה — בדקו את היומן במאגר לפני פנייה נוספת.")
        if c.get("rationale"):
            st.caption(_clean(c["rationale"]))
        if c.get("history"):
            st.caption(f"🕓 אצלנו: {c['history']}")
        for ev in (c.get("evidence") or [])[:2]:
            if ev.get("href"):
                st.caption(f"[{_clean(ev.get('title') or ev['href'])[:80]}]({ev['href']})")

        ac1, ac2, ac3 = st.columns([1.6, 1.1, 0.7])
        if mid:
            lessons = dm.get_lessons(mid)
            if lessons:
                labels = {l["slot_order"]: f"{l['slot_order']}. {l.get('title') or ''}"
                          for l in lessons}
            else:
                labels = {i: f"שיעור {i}" for i in (1, 2, 3, 4)}
            default = int(lesson) if lesson.isdigit() and int(lesson) in labels else list(labels)[0]
            slot = ac1.selectbox(
                "מקטע", list(labels), format_func=lambda i: labels[i],
                index=list(labels).index(default), key=f"slot-{idx}-{name}",
                label_visibility="collapsed")
            if ac2.button("➕ שבץ", key=f"attach-{idx}-{name}", type="primary",
                          help="מוסיף למאגר אם חדש, ומשבץ למקטע הנבחר"):
                wrote = []
                if c.get("source") == "web":
                    href = next((e.get("href") for e in c.get("evidence") or [] if e.get("href")), None)
                    dm.add_new_speaker(
                        name=display, expertise_topics=None,
                        verification_url=href, source_type="web_search",
                        lesson_fit=lesson,
                        notes="נמצא בסריקת מרצים · ⚠️ לאמת לפני פנייה")
                    wrote.append("נוסף למאגר")
                # Attaching is not approaching: the name goes on the slot, the
                # journal stays quiet until the pair actually reaches out.
                dm.upsert_lesson(mid, int(slot), speaker_name=name,
                                 student_id=st.session_state.student_id)
                wrote.append(f"שובץ למקטע {slot}")
                st.toast(f"«{name}» — " + " · ".join(wrote))
                st.rerun()
        else:
            ac1.caption("בחרו משמר למעלה כדי לשבץ")
        if ac3.button("אמת", key=f"scv-{idx}-{name}"):
            st.session_state["verify_name"] = name


def show_speaker_search() -> None:
    st.title("🔍 חיפוש מרצים")
    st.caption(
        "סריקה אחת — המאגר המשותף וגם הרשת — וקבלת 3–4 מועמדים מסוננים. "
        "כל שם מהרשת הוא ⚠️ לאמת עד שבדקתם."
    )

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

    mine = _my_mishmarim()
    default_topic = ""
    default_mid = None
    if mine:
        today = _date_cls.today()
        upcoming = [m for m in mine
                    if (_parse_date(m.get("gregorian_date")) or today) >= today]
        hero = min(upcoming, key=lambda m: m["gregorian_date"]) if upcoming else mine[-1]
        default_mid = hero["id"]
        default_topic = hero.get("topic") or ""

    with st.form("speaker_search"):
        f1, f2 = st.columns([2.5, 1.5])
        topic = f1.text_input("נושא", value=default_topic, placeholder="למשל: תשובה")
        lesson = f2.selectbox(
            "לאיזה שיעור?",
            options=["1", "2", "3", "4"],
            format_func=lambda k: (
                f"{k} · {ss.LESSON_PROFILES[k]['label']}" if k in ss.LESSON_PROFILES
                else "4 · נחיתה אל הלב (ללא מרצה חיצוני)"
            ),
        )
        labels = {m["id"]: f"#{m['id']:02d} · {m['gregorian_date']}" for m in mine}
        mid = st.selectbox(
            "לאיזה משמר משבצים?", [None, *labels],
            format_func=lambda i: "— בלי שיבוץ —" if i is None else labels[i],
            index=(list(labels).index(default_mid) + 1) if default_mid in labels else 0,
        ) if mine else None
        go = st.form_submit_button("🔎 סרוק מאגר + רשת", type="primary")

    # The scout fires ONLY here (rerun trap), and is cached per (topic, lesson)
    # so switching pages and returning does not re-spend the model call.
    if go and topic.strip():
        key = (topic.strip(), lesson)
        with st.spinner("סורק את המאגר ואת הרשת, ומסנן… (עד חצי דקה)"):
            st.session_state["scout_result"] = ca.scout_speakers(topic.strip(), lesson)
            st.session_state["scout_key"] = key
        st.session_state.pop("verify_name", None)
        st.session_state.pop("verify_cache", None)

    result = st.session_state.get("scout_result")
    if not result:
        st.info("הזינו נושא, בחרו שיעור ומשמר — ולחצו סרוק.")
        return

    raw = result.get("raw") or {}
    if raw.get("skipped"):
        st.info(raw.get("reason") or "החיפוש דולג.")
        return

    if not result.get("fallback"):
        st.divider()
        st.subheader(f"⭐ המועמדים המומלצים ({len(result['candidates'])})")
        cands = result["candidates"]
        for i in range(0, len(cands), 2):
            cols = st.columns(2)
            for col, c in zip(cols, cands[i:i + 2]):
                with col:
                    _scout_card(c, mid, lesson, i)
        with st.expander("🌐 כל מה שהחיפוש הגולמי העלה"):
            _raw_search_results(raw)
    else:
        if result.get("error"):
            st.caption(f"⚠️ הסינון החכם לא רץ ({result['error'][:80]}) — מציגים את התוצאות הגולמיות.")
        st.divider()
        _raw_search_results(raw)

    if st.session_state.get("verify_name"):
        st.divider()
        name = st.session_state["verify_name"]
        st.subheader(f"אימות — {name}")
        # Cache per name. Without this the verification re-ran on every rerun —
        # i.e. on every unrelated button click on this page — which is exactly
        # the burst pattern the throttle exists to prevent.
        vcache = st.session_state.setdefault("verify_cache", {})
        if name not in vcache:
            with st.spinner("מאמת…"):
                vcache[name] = ss.verify_speaker(name, topic=raw.get("topic") or "")
        v = vcache[name]
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
        st.code(ss.format_for_chat(raw), language="markdown")


def _raw_search_results(result: dict) -> None:
    """The pre-synthesis listing — also the whole page when there is no API key."""
    st.subheader(f"📗 מהמאגר ({len(result.get('index_hits') or [])})")
    if result.get("index_hits"):
        for r in result["index_hits"]:
            st.markdown(
                f"**{_clean(r['name'])}** — {_clean(r.get('expertise_topics') or 'תחום לא רשום')} · "
                f"סטטוס: {r.get('status') or '—'}"
            )
            if "סירב" in (r.get("status") or "") or "לא יכול" in (r.get("status") or ""):
                st.caption("↩️ סירוב הוא כמעט תמיד לתאריך מסוים — שווה לנסות שוב בתקופה אחרת")
    else:
        st.caption("אין התאמות במאגר לנושא הזה.")

    st.subheader(f"🌐 שמות חדשים מהרשת ({len(result.get('web_names') or [])})")
    st.caption(
        "כל שם כאן הוא ⚠️ **לאמת** — הוא חולץ מתוצאות חיפוש, לא מהמאגר. "
        "פרטי קשר לעולם לא ממולאים אוטומטית."
    )
    for i, entry in enumerate((result.get("web_names") or [])[:20]):
        _speaker_card(entry, result.get("topic") or "", result.get("lesson") or "1", i)

    if result.get("errors"):
        st.subheader("⚠️ שאילתות שלא רצו — הריצו ידנית")
        for err in result["errors"]:
            st.markdown(
                f"`{err['query']}` — [DuckDuckGo]({err['manual']['duckduckgo']}) · "
                f"[Google]({err['manual']['google']})"
            )


def _topic_chips_from(rows: list[dict]) -> list[str]:
    """Distinct topic tags across the index, most common first — the filter row."""
    counts: dict[str, int] = {}
    for r in rows:
        for part in (r.get("expertise_topics") or "").split(","):
            tag = part.strip()
            if tag and tag != "TBD":
                counts[tag] = counts.get(tag, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def _speaker_index_card(r: dict, history: list[dict], dup_count: int) -> None:
    """A person in the shared memory: name and what they bring. The journal,
    contact and status all fold away — the face of the card is who they are,
    not where some outreach stands."""
    with st.container(border=True):
        warn = " ⚠️" if dup_count > 1 else ""
        topics = [t.strip() for t in (r.get("expertise_topics") or "").split(",")
                  if t.strip() and t.strip() != "TBD"]
        chips = "".join(_chip(t, "blue") for t in topics[:3])
        st.markdown(
            f"<div class='task-desc'>{_clean(dm.display_name(r))}{warn}</div>"
            f"<div>{chips}</div>",
            unsafe_allow_html=True,
        )
        if r.get("notes"):
            st.caption("📝 " + _clean(r["notes"])[:90])

        with st.expander("פרטים ויומן"):
            if dup_count > 1:
                st.warning(
                    f"יש {dup_count} רשומות בשם הזה — ככל הנראה אנשים שונים. "
                    "לא מאחדים אותם על דעתנו; ודאו שזה האדם הנכון."
                )
            st.caption(
                f"סטטוס: {r.get('current_status') or '⬜ לא פנינו'} · "
                f"אזור: {r.get('region') or '⚪ לא ידוע'} · "
                f"קשר: {r.get('contact') or 'TBD'} · "
                f"שיעור: {r.get('lesson_fit') or 'TBD'}"
            )
            if history:
                for o in history[:6]:
                    who = o.get("student_name") or "צוות"
                    where = f"משמר #{o['mishmar_id']:02d}" if o.get("mishmar_id") else "—"
                    st.markdown(
                        f"- {o['status']} · {where} · {who} · {(o.get('created_at') or '')[:10]}"
                        + (f" — {_clean(o['note'])}" if o.get("note") else "")
                    )
                if any("לא יכול" in (o["status"] or "") for o in history):
                    st.caption("↩️ סירוב הוא כמעט תמיד לתאריך מסוים — שווה לנסות שוב.")
            else:
                st.caption("עוד לא פנינו אליו/ה השנה.")

            # A status note only. Attaching to a Mishmar happens where the
            # evening is built — the index is memory, not a booking screen.
            with st.form(f"outreach-{r['speaker_id']}", border=False):
                cc1, cc2 = st.columns([1.2, 1])
                new_status = cc1.selectbox("עדכון", dm.SPEAKER_STATUSES,
                                           key=f"st-{r['speaker_id']}",
                                           label_visibility="collapsed")
                note = cc2.text_input("הערה", key=f"nt-{r['speaker_id']}",
                                      label_visibility="collapsed",
                                      placeholder="הערה")
                if st.form_submit_button("רשום ביומן"):
                    dm.record_outreach(
                        new_status, speaker_id=r["speaker_id"],
                        student_id=st.session_state.student_id,
                        note=note or None)
                    st.toast(f"«{r['name']}» → {new_status}")
                    st.rerun()


def show_speaker_index() -> None:
    """Institutional memory. The workfile and the search screen WRITE here;
    this page is where you come to remember."""
    st.title("👥 מאגר המרצים")
    st.caption(
        "הזיכרון המשותף של כל הצוותים: מי קיים, מה הם מביאים, ומה קרה איתם. "
        "שיבוץ למשמר נעשה בבניית הערב ובחיפוש — כאן נזכרים."
    )

    # TWO queries for the whole page — nothing per-card.
    rows = dm.get_speakers_with_status()
    outreach_by_speaker: dict[int, list[dict]] = {}
    for o in dm.get_all_outreach():
        outreach_by_speaker.setdefault(o["speaker_id"], []).append(o)

    query = st.text_input("חיפוש", placeholder="שם · תחום · הערה — למשל: תשובה",
                          label_visibility="collapsed")

    # topic filter chips — pills toggle a single active tag
    tags = _topic_chips_from(rows)[:12]
    picked = st.session_state.get("speaker_topic_filter")
    if tags:
        chosen = st.pills("תחומים", tags, key="speaker_topic_filter",
                          label_visibility="collapsed")
        picked = chosen

    if query.strip():
        q = dm.normalize_name(query).lower()
        rows = [
            r for r in rows
            if q in dm.normalize_name(r["name"]).lower()
            or q in (r.get("expertise_topics") or "").lower()
            or q in (r.get("notes") or "").lower()
        ]
    if picked:
        rows = [r for r in rows if picked in (r.get("expertise_topics") or "")]

    st.caption(f"{len(rows)} במאגר")
    if not rows:
        st.info("אין התאמות.")
        return

    seen: dict[str, int] = {}
    for r in rows:
        seen[r["name"]] = seen.get(r["name"], 0) + 1

    shown = st.session_state.setdefault("speaker_page_size", 24)
    for i in range(0, min(len(rows), shown), 3):
        cols = st.columns(3)
        for col, r in zip(cols, rows[i:i + 3]):
            with col:
                _speaker_index_card(
                    r, outreach_by_speaker.get(r["speaker_id"], []), seen[r["name"]])
    if len(rows) > shown:
        if st.button(f"הצג עוד ({len(rows) - shown} נוספים)", width="stretch"):
            st.session_state["speaker_page_size"] = shown + 24
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


DURATION_OPTIONS = {60: "שעה", 75: "שעה ורבע", 90: "שעה וחצי"}


def _slot_times(l: dict) -> str:
    start = l.get("start_time") or "--:--"
    dur = l.get("duration_minutes")
    if not dur or ":" not in start:
        return start
    h, m = (int(x) for x in start.split(":"))
    end = (h * 60 + m + int(dur)) % (24 * 60)
    return f"{start}–{end // 60:02d}:{end % 60:02d}"


def _candidate_rows(mid: int, l: dict, cands: list[dict]) -> None:
    """The lesson's optional-speakers list: name · phone · status · actions.
    Once one is closed, the list collapses to that single row."""
    closed = l.get("speaker_name")
    if closed:
        st.markdown(f"🎤 **{_clean(closed)}** {_chip('✅ סגור', 'green')}",
                    unsafe_allow_html=True)
        return
    if cands:
        st.markdown("**מרצים אופציונליים:**")
    for cand in cands:
        c1, c2, c3, c4 = st.columns([1.7, 1.4, 0.6, 0.6])
        c1.markdown(f"{_clean(cand['name'])}"
                    + (f" <span class='card-meta'>{_clean(cand['phone'])}</span>"
                       if cand.get("phone") else ""),
                    unsafe_allow_html=True)
        cur = cand.get("status") or dm.SPEAKER_STATUSES[0]
        new_status = c2.selectbox(
            "סטטוס", dm.SPEAKER_STATUSES,
            index=dm.SPEAKER_STATUSES.index(cur) if cur in dm.SPEAKER_STATUSES else 0,
            key=f"cst-{cand['id']}", label_visibility="collapsed")
        if new_status != cur:
            dm.update_lesson_speaker_status(
                cand["id"], new_status, mishmar_id=mid,
                student_id=st.session_state.student_id)
            st.rerun()
        if c3.button("✅ סגרנו", key=f"close-{cand['id']}",
                     help="הופך למרצה של השיעור; שאר המועמדים יוסרו"):
            res = dm.close_lesson_speaker(
                l["id"], cand["name"], mishmar_id=mid,
                student_id=st.session_state.student_id)
            st.toast(f"«{res['closed']}» נסגר לשיעור"
                     + (f" · הוסרו: {', '.join(res['removed'])}" if res["removed"] else ""))
            st.rerun()
        if c4.button("🗑", key=f"rmc-{cand['id']}"):
            dm._t("lesson_speakers").delete().eq("id", cand["id"]).execute()
            st.rerun()

    with st.form(f"addcand-{l['id']}", border=False):
        f1, f2, f3 = st.columns([1.6, 1.3, 0.8])
        nm = f1.text_input("שם מרצה", key=f"cn-{l['id']}",
                           label_visibility="collapsed", placeholder="שם מרצה אפשרי")
        ph = f2.text_input("טלפון", key=f"cp-{l['id']}",
                           label_visibility="collapsed", placeholder="טלפון (רשות)")
        if f3.form_submit_button("➕ מועמד") and nm.strip():
            dm.add_lesson_speaker(l["id"], nm.strip(), phone=ph,
                                  student_id=st.session_state.student_id)
            st.toast(f"«{nm.strip()}» נוסף כמועמד — וגם למאגר המשותף")
            st.rerun()


def _lesson_form(mid: int, l: dict) -> None:
    """The slot's editor. Lives behind a session-state toggle, not an
    expander — expanders remember their open state client-side, so the old
    editor never collapsed after saving."""
    with st.form(f"lesson-{l['id']}", border=False):
        c1, c2 = st.columns(2)
        title = c1.text_input("כותרת", value=l.get("title") or "")
        dur_keys = list(DURATION_OPTIONS)
        cur_dur = l.get("duration_minutes") or 75
        if cur_dur not in dur_keys:
            dur_keys = sorted({*dur_keys, cur_dur})
        duration = c2.selectbox(
            "משך", dur_keys,
            index=dur_keys.index(cur_dur),
            format_func=lambda d: DURATION_OPTIONS.get(d, f"{d} דק'"))
        c3, c4 = st.columns(2)
        role = c3.selectbox(
            "תפקיד בערב", ["", *LESSON_ROLES],
            index=(LESSON_ROLES.index(l["lesson_role"]) + 1)
            if l.get("lesson_role") in LESSON_ROLES else 0,
            format_func=lambda r: r or "—")
        fmt = c4.selectbox(
            "פורמט", ["", *LESSON_FORMATS],
            index=(LESSON_FORMATS.index(l["format"]) + 1)
            if l.get("format") in LESSON_FORMATS else 0,
            format_func=lambda r: r or "—")
        desc = st.text_area("תיאור", value=l.get("description") or "")

        st.markdown("**📎 דף מקורות**")
        up = st.file_uploader("העלאת קובץ", key=f"src-{l['id']}",
                              label_visibility="collapsed")
        link = st.text_input("או קישור (Drive וכו')", value=l.get("source_url") or "")

        cc1, cc2, cc3 = st.columns([1, 1, 1])
        saved = cc1.form_submit_button("💾 שמור", type="primary")
        cancel = cc2.form_submit_button("ביטול")
        delete = cc3.form_submit_button("🗑 מחק מקטע")

    if delete:
        dm.delete_lesson(l["id"])
        dm.recompute_lesson_times(mid)
        st.session_state["editing_lesson"] = None
        st.toast("המקטע נמחק"); st.rerun()
    if cancel:
        st.session_state["editing_lesson"] = None
        st.rerun()
    if saved:
        dm.upsert_lesson(mid, l["slot_order"], title=title,
                         description=desc, lesson_role=role or None, fmt=fmt or None,
                         student_id=st.session_state.student_id)
        dm._t("lessons").update({"duration_minutes": int(duration)}).eq(
            "id", l["id"]).execute()
        source = None
        if up is not None:
            with st.spinner("מעלה את דף המקורות…"):
                source = dm.upload_source_sheet(mid, l["id"], up.name, up.getvalue())
            if not source:
                st.warning("ההעלאה נכשלה — הדביקו קישור במקום.")
        if source or link.strip() != (l.get("source_url") or ""):
            dm.set_lesson_source(l["id"], source or link)
        dm.recompute_lesson_times(mid)
        st.session_state["editing_lesson"] = None
        st.toast("המקטע נשמר"); st.rerun()


def _speaker_status_chip(status: Optional[str]) -> str:
    if not status:
        return ""
    kind = ("green" if "✅" in status else
            "red" if "❌" in status else
            "yellow" if ("⏳" in status or "📩" in status) else
            "gold" if "⚠️" in status else "gray")
    return _chip(status, kind)


def _topic_and_structure(mid: int) -> None:
    m = dm.get_mishmar(mid)

    # --- the topic: a hero form until it exists, a quiet line after ---
    if not m.get("topic"):
        with st.container(border=True):
            st.markdown("#### 🎯 הצעד הראשון: לסגור נושא")
            st.caption(
                "הנושא הוא מנוע הערב כולו — מומלץ לסגור אותו כשלושה שבועות לפני. "
                "אין רעיון? שאלו את שותף הבנייה משמאל, או בדקו בארכיון אם היה משמר דומה."
            )
            with st.form(f"topic-{mid}"):
                new_topic = st.text_input(
                    "שם הנושא",
                    placeholder="למשל: כרוניקה של שינוי — האם אדם יכול לשכתב את העבר?")
                if st.form_submit_button("🎯 סגור את הנושא", type="primary") and new_topic.strip():
                    dm.set_mishmar_topic(mid, new_topic.strip())
                    for t in dm.get_tasks_for_mishmar(mid):
                        if t.get("category") == "נושא" and t["status"] != "DONE":
                            dm.update_task_status(t["id"], "DONE")
                    # The structure appears the moment the topic closes.
                    created = dm.create_default_timeline(mid)
                    st.toast(f"הנושא נסגר! נבנה שלד ערב של {created} משבצות מ-20:00")
                    st.rerun()
        return   # no timeline before a topic — one step at a time
    else:
        with st.expander(f"🎯 הנושא: {m['topic']} — לעריכה"):
            with st.form(f"topic-{mid}"):
                new_topic = st.text_input("שם הנושא", value=m["topic"])
                if st.form_submit_button("עדכן נושא") and new_topic.strip():
                    dm.set_mishmar_topic(mid, new_topic.strip())
                    st.toast("הנושא עודכן"); st.rerun()

    # --- the evening as a duration-driven timeline ---
    st.markdown("#### 🌙 מבנה הערב")
    st.caption(
        "השעות נגזרות מהמשכים — שינוי משך של משבצת מזרים את כל הערב. "
        "שלושה שיעורים ושעת חבורות הם ברירת המחדל; אפשר לשנות הכל."
    )
    lessons = dm.get_lessons(mid)
    if not lessons:
        if st.button("✨ צור את שלד הערב (20:00, שלושה שיעורים + חבורות)",
                     type="primary", width="stretch"):
            dm.create_default_timeline(mid)
            st.rerun()
        return

    candidates = dm.get_lesson_speakers(mid)
    editing = st.session_state.get("editing_lesson")
    focus = st.session_state.pop("wf_focus_lesson", None)
    if focus == "first_open_speaker":
        for l in lessons:
            if not l.get("is_break") and not l.get("speaker_name") \
                    and (l.get("lesson_role") or "") != "חבורות":
                st.session_state["editing_lesson"] = editing = l["id"]
                break

    lesson_no = 0
    for l in lessons:
        if l.get("is_break"):
            # a slim break row: the only knob is minutes
            bc1, bc2 = st.columns([4, 1])
            bc1.markdown(
                f"<div style='opacity:.6;padding:.25rem .6rem'>☕ הפסקה · "
                f"{l.get('duration_minutes') or 30} דק' · "
                f"<span dir='ltr'>{_slot_times(l)}</span></div>",
                unsafe_allow_html=True,
            )
            new_min = bc2.number_input(
                "דק'", min_value=5, max_value=90, step=5,
                value=int(l.get("duration_minutes") or 30),
                key=f"brk-{l['id']}", label_visibility="collapsed")
            if int(new_min) != int(l.get("duration_minutes") or 30):
                dm._t("lessons").update({"duration_minutes": int(new_min)}).eq(
                    "id", l["id"]).execute()
                dm.recompute_lesson_times(mid)
                st.rerun()
            continue

        lesson_no += 1
        cands = candidates.get(l["id"], [])
        with st.container(border=True):
            head = _clean(l.get("title") or "") or f"שיעור {lesson_no} — ללא כותרת"
            if (l.get("lesson_role") or "") == "חבורות" and not l.get("title"):
                head = "חבורות"
            chips = []
            if l.get("lesson_role"):
                chips.append(_chip(l["lesson_role"], "gold"))
            if l.get("format"):
                chips.append(_chip(l["format"], "gray"))
            if not l.get("speaker_name") and cands:
                chips.append(_chip(f"{len(cands)} מועמדים", "blue"))
            st.markdown(
                f"<div class='task-desc'>"
                f"<span class='chip chip-blue' dir='ltr'>{_slot_times(l)}</span> {head}</div>"
                f"<div>{''.join(chips)}</div>",
                unsafe_allow_html=True,
            )
            if l.get("description"):
                st.caption(_clean(l["description"])[:180])
            if l.get("source_url"):
                st.caption(f"📎 [דף מקורות]({l['source_url']})")

            _candidate_rows(mid, l, cands)

            # the slot's derived work, as small doors to the tasks board
            todo = []
            if not l.get("speaker_name") and (l.get("lesson_role") or "") != "חבורות":
                todo.append("🎤 סגירת מרצה")
            if not l.get("source_url"):
                todo.append("📎 דף מקורות")
            tc = st.columns([1, 1, 1, 1])
            for i, label in enumerate(todo):
                if tc[i].button(label, key=f"td-{l['id']}-{i}",
                                help="פותח את לוח המשימות"):
                    _goto(NAV_WORKFILE, mid, WF_SECTIONS[1])
            if tc[3].button("✏️ עריכה", key=f"ed-{l['id']}"):
                st.session_state["editing_lesson"] = (
                    None if editing == l["id"] else l["id"])
                st.rerun()

            if editing == l["id"]:
                _lesson_form(mid, l)

    ac1, ac2 = st.columns(2)
    if ac1.button("➕ הוסף מקטע"):
        dm.upsert_lesson(mid, len(lessons) + 1)
        dm._t("lessons").update({"duration_minutes": 60}).eq(
            "mishmar_id", mid).eq("slot_order", len(lessons) + 1).execute()
        dm.recompute_lesson_times(mid)
        st.rerun()
    if ac2.button("➕ הוסף הפסקה"):
        row = dm._t("lessons").insert({
            "mishmar_id": mid, "slot_order": len(lessons) + 1,
            "is_break": True, "duration_minutes": 15}).execute()
        dm.recompute_lesson_times(mid)
        st.rerun()


def _wf_task_card(t: dict, mid: int, key_prefix: str) -> None:
    """A workfile task card: the task is the point, the controls are small.
    «פתח» is a door to where the task is done; edit/delete live behind tiny
    icons; completion is one small check."""
    with st.container(border=True):
        chips = []
        if t.get("category"):
            chips.append(_chip(t["category"], "gold"))
        if t.get("overdue"):
            chips.append(_chip("באיחור", "red"))
        st.markdown(
            f"<div class='task-desc'>{_clean(t['task_description'])}</div>"
            f"<div>{''.join(chips)}</div>",
            unsafe_allow_html=True,
        )
        if t.get("details"):
            st.caption(_clean(t["details"])[:160])
        meta = t.get("nudge") or (f"מומלץ עד {_fmt_date(t['due_date'])}"
                                  if t.get("due_date") else "")
        if meta:
            st.markdown(f"<div class='card-meta'>🕒 {_clean(meta)}</div>",
                        unsafe_allow_html=True)

        k = f"{key_prefix}-{t['id']}"
        c1, c2, c3, c4 = st.columns([1.2, 0.7, 0.55, 0.55])
        if t["status"] != "DONE":
            if c1.button("פתח ↗", key=f"{k}-go", help="למקום שבו סוגרים את זה"):
                if t.get("category") in ("מרצים", "תוכן", "נושא"):
                    _goto(NAV_WORKFILE, mid, WF_SECTIONS[0],
                          lesson_focus="first_open_speaker"
                          if t.get("category") == "מרצים" else None)
                elif t.get("category") == "אחרי":
                    _goto(NAV_WORKFILE, mid, WF_SECTIONS[2])
            if c2.button("✓", key=f"{k}-dn", help="סמן שבוצע"):
                dm.update_task_status(t["id"], "DONE")
                st.toast("בוצע 🎉"); st.rerun()
        else:
            if c1.button("↩ החזר", key=f"{k}-re"):
                dm.update_task_status(t["id"], "TO DO"); st.rerun()
        if c3.button("✏️", key=f"{k}-ed", help="עריכה"):
            st.session_state["editing_task"] = (
                None if st.session_state.get("editing_task") == t["id"] else t["id"])
            st.rerun()
        if c4.button("🗑", key=f"{k}-rm", help="מחיקה"):
            dm.delete_task(t["id"])
            st.toast("המשימה נמחקה"); st.rerun()

        if st.session_state.get("editing_task") == t["id"]:
            with st.form(f"edit-{k}", border=False):
                desc = st.text_input("כותרת", value=t["task_description"])
                details = st.text_area("תיאור", value=t.get("details") or "",
                                       height=68)
                due = st.text_input("מומלץ עד (dd.mm.yyyy)",
                                    value=_fmt_date(t["due_date"]) if t.get("due_date") else "")
                if st.form_submit_button("💾 שמור", type="primary"):
                    iso = None
                    d = _parse_date(due)
                    if d:
                        iso = d.isoformat()
                    dm.edit_task(t["id"], description=desc, details=details,
                                 due_date=iso if due.strip() else None)
                    st.session_state["editing_task"] = None
                    st.toast("נשמר"); st.rerun()


def _wf_task_grid(items: list[dict], mid: int, prefix: str) -> None:
    for i in range(0, len(items), 2):
        cols = st.columns(2)
        for col, t in zip(cols, items[i:i + 2]):
            with col:
                _wf_task_card(t, mid, prefix)


def _tasks_tab(mid: int, progress: dict) -> None:
    """Phase accordion of OPEN tasks; day-of work as its own group; the
    after-work lives in the after-Mishmar section; done tasks sink to the
    bottom, out of the way entirely."""
    by_due = lambda t: t.get("due_date") or "9999"
    all_tasks = [t for ph in progress["phases"] for t in ph["tasks"]]
    done = [t for t in all_tasks if t["status"] == "DONE"]

    for i, ph in enumerate(progress["phases"]):
        if ph["key"] == "after":
            continue   # lives in the אחרי-המשמר section
        open_ts = [t for t in ph["tasks"]
                   if t["status"] != "DONE" and t.get("category") != "יום המשמר"]
        if not open_ts:
            continue
        state = "▸" if i == progress["current"] else ("✓" if ph["complete"] else "🔒")
        with st.expander(f"{state} {ph['icon']} {ph['label']} ({len(open_ts)})",
                         expanded=(i == progress["current"])):
            _wf_task_grid(sorted(open_ts, key=by_due), mid, f"wf{mid}-{ph['key']}")

    day_of = [t for t in all_tasks
              if t.get("category") == "יום המשמר" and t["status"] != "DONE"]
    if day_of:
        with st.expander(f"🕯️ יום המשמר עצמו ({len(day_of)})"):
            st.caption("הדברים שנעשים בערב עצמו — לא לוגיסטיקה מוקדמת.")
            _wf_task_grid(sorted(day_of, key=by_due), mid, f"wf{mid}-day")

    st.divider()
    with st.form(f"addtask-{mid}"):
        c1, c2 = st.columns([3, 1])
        desc = c1.text_input("משימה חדשה")
        cat = c2.selectbox("קטגוריה", ["(אוטומטי)"] + list(dm.TASK_CATEGORIES))
        if st.form_submit_button("➕ הוסף משימה") and desc.strip():
            dm.add_task(mid, desc.strip(),
                        category=None if cat == "(אוטומטי)" else cat)
            st.toast("נוספה משימה — שובצה לשלב לפי הקטגוריה"); st.rerun()

    if done:
        with st.expander(f"✅ בוצעו ({len(done)})"):
            _wf_task_grid(done, mid, f"wf{mid}-done")


def _after_tab(mid: int) -> None:
    m = dm.get_mishmar(mid)
    lessons = [l for l in dm.get_lessons(mid) if not l.get("is_break")]
    tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_mishmar(mid)]
    after_tasks = [t for t in tasks if t.get("category") == "אחרי"]

    # --- feedback, per evening slot ---
    st.markdown("#### 🌙 משוב על הערב — לפי מקטעים")
    st.caption(
        "המשוב נשמר על שמך ועל המשמר הזה, והופך את מאגר המרצים לזיכרון מוסדי. "
        "שליחה גם סוגרת את משימת המשוב שלך."
    )
    existing = dm.get_feedback_for_mishmar(mid)
    my_titles = {f.get("lesson_title") for f in existing
                 if f.get("student_id") == st.session_state.student_id}

    if not lessons:
        st.info("אין עדיין מבנה ערב — המשוב ייפתח כשיהיו מקטעים.")
    else:
        with st.form(f"slot-feedback-{mid}"):
            entries = []
            for i, l in enumerate(lessons, 1):
                name = l.get("title") or (
                    "חבורות" if (l.get("lesson_role") or "") == "חבורות"
                    else f"שיעור {i}")
                st.markdown(
                    f"**{_clean(name)}**"
                    + (f" · 🎤 {_clean(l['speaker_name'])}" if l.get("speaker_name") else "")
                    + (" · ✅ כבר נשלח" if name in my_titles else ""),
                    unsafe_allow_html=True)
                c1, c2 = st.columns([1, 2.6])
                rating = c1.slider("ציון", 1, 5, 4, key=f"fb-r-{l['id']}")
                words = c2.text_input("התייחסות", key=f"fb-w-{l['id']}",
                                      placeholder="מה עבד, מה פחות")
                entries.append((l, name, rating, words))
            if st.form_submit_button("💾 שמור משוב על הערב", type="primary"):
                n = 0
                for l, name, rating, words in entries:
                    if name in my_titles:
                        continue   # one submission per slot per trainee
                    dm.add_feedback(
                        mid, rating=rating, lesson_id=l["id"], lesson_title=name,
                        speaker_name=l.get("speaker_name"),
                        student_id=st.session_state.student_id,
                        what_worked=(words or None))
                    n += 1
                # feedback submitted => the trainee's feedback task closes
                for t in tasks:
                    if "משוב" in t["task_description"] and t["status"] != "DONE":
                        dm.update_task_status(t["id"], "DONE")
                st.toast(f"נשמרו {n} משובים · משימת המשוב נסגרה")
                st.rerun()

    if existing:
        with st.expander(f"משוב שנרשם ({len(existing)})"):
            for f in existing:
                who = f.get("lesson_title") or f.get("speaker_name") or "המשמר בכללותו"
                st.markdown(f"- **{_clean(who)}** — {'⭐' * (f.get('rating') or 0)}")
                if f.get("what_worked"):
                    st.caption(_clean(f["what_worked"]))
                if f.get("what_didnt"):
                    st.caption(f"פחות: {_clean(f['what_didnt'])}")

    # --- the after-work tasks live here, in context ---
    open_after = [t for t in after_tasks if t["status"] != "DONE"]
    if open_after:
        st.markdown("#### 🌙 המשימות של אחרי הערב")
        _wf_task_grid(sorted(open_after, key=lambda t: t.get("due_date") or "9999"),
                      mid, f"aft{mid}")

    # --- budget, unchanged in substance ---
    st.divider()
    speakers = [l["speaker_name"] for l in lessons if l.get("speaker_name")]
    for name in dm.get_budget_speaker_names(mid):
        if name not in speakers:
            speakers.append(name)
    with st.expander("💰 סיכום תקציב"):
        st.caption(
            f"האינדיקציה היא {dm.PER_MISHMAR_BUDGET_NIS} ₪ למשמר — ממוצע שכולל מרצים "
            "וכיבוד יחד. חריגה במשמר בודד אינה שגיאה: היא נמשכת מהסעיף העונתי."
        )
        with st.form(f"budget-{mid}"):
            st.markdown("**מרצים שהגיעו ומה שולם להם** *(0 = הגיע בהתנדבות)*")
            paid = {}
            for i, name in enumerate(speakers):
                paid[name] = st.number_input(f"{name} (₪)", min_value=0.0, step=50.0,
                                             key=f"pay-{mid}-{i}")
            if not speakers:
                st.caption("לא רשומים מרצים במבנה הערב.")
            extra_name = st.text_input("מרצה נוסף שלא מופיע למעלה")
            extra_amt = st.number_input("תשלום למרצה הנוסף (₪)", min_value=0.0, step=50.0)
            refreshments = st.number_input("כיבוד (₪)", min_value=0.0, step=10.0)
            other = st.number_input("הוצאות אחרות (₪)", min_value=0.0, step=10.0)
            if st.form_submit_button("שמור סיכום תקציב"):
                n = 0
                for name, amt in paid.items():
                    dm.add_budget_entry(mid, "מרצה", actual_cost=amt, description=name); n += 1
                if extra_name.strip():
                    dm.add_budget_entry(mid, "מרצה", actual_cost=extra_amt,
                                        description=extra_name.strip()); n += 1
                if refreshments:
                    dm.add_budget_entry(mid, "כיבוד", actual_cost=refreshments, description="כיבוד"); n += 1
                if other:
                    dm.add_budget_entry(mid, "אחר", actual_cost=other, description="אחר"); n += 1
                st.toast(f"נשמרו {n} שורות תקציב"); st.rerun()
        spent = (m or {}).get("budget_used") or 0
        st.metric("סה״כ הוצאות למשמר הזה", _fmt_nis(spent))
        if spent > dm.PER_MISHMAR_BUDGET_NIS:
            st.info("מעל האינדיקציה — לידיעה, לא לדאגה.")


def show_mishmar_page() -> None:
    st.title("📋 ניהול המשמר")
    mid = _mishmar_picker("workfile_mishmar")
    if not mid:
        return

    m = dm.get_mishmar(mid)
    tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_mishmar(mid)]
    progress = dm.mishmar_progress(mishmar=m, tasks=tasks)
    partners = dm.get_partners(mid)

    # --- the Mishmar's identity card: who, when, where it stands ---
    with st.container(border=True):
        chips = [_countdown_chip(m)]
        if m.get("mishmar_type"):
            chips.append(_chip(m["mishmar_type"], "gold"))
        if partners:
            chips.append(_chip("👥 " + " · ".join(p["name"] for p in partners), "blue"))
        title = _clean(m.get("topic") or "") or "<span style='opacity:.5'>עדיין בלי נושא</span>"
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap'>"
            f"<span style='font-size:1.35rem;font-weight:800'>🕯️ {title}</span>"
            f"<span style='opacity:.65'>משמר #{m['id']:02d} · {m['gregorian_date']} · "
            f"{m['hebrew_date']}</span></div>"
            f"<div style='margin-top:.25rem'>{''.join(c for c in chips if c)}</div>",
            unsafe_allow_html=True,
        )
        if m.get("note"):
            st.caption(m["note"])
        st.markdown(_stepper_html(progress), unsafe_allow_html=True)
        if progress["total"]:
            st.progress(progress["pct"],
                        text=f"{progress['done']}/{progress['total']} משימות הושלמו")
        nxt = progress.get("next_task")
        if nxt:
            st.markdown(
                f"<div style='background:#f5edda;border-radius:10px;"
                f"padding:.5rem .9rem'>⭐ <b>הצעד הבא:</b> "
                f"{_clean(nxt['task_description'])}</div>",
                unsafe_allow_html=True,
            )

    # A keyed control instead of st.tabs — tabs cannot be selected
    # programmatically, and deep links from the home page must land on a
    # specific section.
    if st.session_state.get("wf_section") not in WF_SECTIONS:
        st.session_state["wf_section"] = WF_SECTIONS[0]
    section = st.radio("אזור", WF_SECTIONS, key="wf_section",
                       horizontal=True, label_visibility="collapsed")
    st.divider()
    if section == WF_SECTIONS[0]:
        _topic_and_structure(mid)
    elif section == WF_SECTIONS[1]:
        _tasks_tab(mid, progress)
    else:
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
    _apply_goto()

    info = bootstrap()
    if not info.get("storage_ok"):
        st.title(f"🕯️ {APP_TITLE}")
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
