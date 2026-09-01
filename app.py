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
import os
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
def build_stamp() -> str:
    """The deployed commit, visible in the sidebar — so "did the app update?"
    is answered by looking, not guessing. Streamlit Cloud clones the repo, so
    git is present; anything failing falls back quietly."""
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5,
                             cwd=os.path.dirname(os.path.abspath(__file__))
                             ).stdout.strip()
        when = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format:%d.%m %H:%M"],
                              capture_output=True, text=True, timeout=5,
                              cwd=os.path.dirname(os.path.abspath(__file__))
                              ).stdout.strip()
        if sha:
            return f"{sha} · {when}"
    except Exception:
        pass
    return "לא ידוע"


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
  /* st.caption renders stCaptionContainer INSTEAD of stMarkdownContainer, so
     for a long time no caption in the app was ever told it is Hebrew — every
     one of them hugged the left edge. */
  [data-testid="stCaptionContainer"],
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
  /* Collapse under RTL. Streamlit 1.62 styles the panel with
       transform: isCollapsed ? translateX(-<width>px) : none
     — correct for its native LEFT sidebar, wrong for ours, which RTL holds on
     the RIGHT: the panel slides ACROSS the content instead of off the near
     edge. Kill the slide outright and let the width transition (which
     Streamlit already animates over the same 300ms) do the collapsing. The
     content keeps a min-width so it is clipped rather than reflowed into a
     column of stacked letters mid-animation. */
  section[data-testid="stSidebar"] {
      transform: none !important;
      overflow: hidden !important;
  }
  [data-testid="stSidebarContent"] { min-width: 244px; }
  section[data-testid="stSidebar"][aria-expanded="false"] {
      width: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      border: none !important;
  }
  section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] {
      opacity: 0;
      transition: opacity 120ms ease;
  }
  /* every control in the sidebar tracks its full width, and its label sits in
     the middle of it — a 100%-wide button with a right-hugging label reads as
     a bug, not as Hebrew. */
  /* The nav radiogroup and its labels are flex items inside flex COLUMNS whose
     align-items is flex-start — so `width: 100%` alone still shrank each card
     to its own text. `align-self: stretch` is the rule that actually makes
     them span the panel. */
  [data-testid="stSidebar"] .stButton,
  [data-testid="stSidebar"] .stButton button,
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
      width: 100%;
      box-sizing: border-box;
  }
  /* Streamlit sizes the radio's own element container to its CONTENT
     (measured: 137px inside a 239px block), so the cards stopped short of the
     panel edge no matter what the label said. The container is the thing that
     has to stretch. */
  [data-testid="stSidebar"] [data-testid="stElementContainer"],
  [data-testid="stSidebar"] [data-testid="stRadio"],
  [data-testid="stSidebar"] div[role="radiogroup"] {
      width: 100% !important;
      align-self: stretch;
      align-items: stretch;
      box-sizing: border-box;
  }
  [data-testid="stSidebar"] .stButton button {
      justify-content: center;
      text-align: center;
  }
  /* The label's inner wrappers are flex rows; under RTL their content packs
     to the RIGHT, so centring the <p> alone centred it inside a 97px box that
     was itself right-aligned in a 208px row. The ROWS have to centre. */
  [data-testid="stSidebar"] div[role="radiogroup"] > label > div,
  [data-testid="stSidebar"] div[role="radiogroup"] > label > div > div {
      width: 100%;
      justify-content: center;
      text-align: center;
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label [data-testid="stMarkdownContainer"] {
      text-align: center;
  }
  [data-testid="stSidebar"] div[role="radiogroup"] > label p { text-align: center; }
  [data-testid="stSidebar"] div[role="radiogroup"] > label {
      align-self: stretch;
      box-sizing: border-box;
      display: flex; align-items: center; justify-content: center;
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

  /* ---- Rhythm: one 4/8px spacing scale for the whole app ---- */
  :root {
      --sp-1: 4px; --sp-2: 8px; --sp-3: 12px;
      --sp-4: 16px; --sp-5: 24px; --sp-6: 32px;
      --line: #e3ddcc;
  }
  h1 { margin-bottom: var(--sp-2) !important; }
  h3, h4 { margin: var(--sp-5) 0 var(--sp-2) !important; }
  /* a quiet navy accent instead of an emoji per heading. A physical RIGHT
     border, not a ::before — Streamlit headings are flex containers and an
     inline pseudo-box drifts to the line's END under RTL. */
  .stMarkdown h4 {
      border-right: 4px solid #1d3e7d;
      padding-right: var(--sp-2);
  }
  [data-testid="stDivider"] hr, hr {
      border-color: var(--line) !important;
      opacity: .6;
      margin: var(--sp-4) 0 !important;
  }
  [data-testid="stCaptionContainer"] { line-height: 1.5; }

  /* ---- Cards: depth from a hairline, not a shadow ---- */
  [data-testid="stVerticalBlockBorderWrapper"] {
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 1px 2px rgba(29, 62, 125, 0.05);
  }
  [data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"] {
      gap: var(--sp-2);
  }

  /* ---- Expanders: hairline, not a boxed box ---- */
  [data-testid="stExpander"] details {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: transparent;
  }
  [data-testid="stExpander"] summary { font-weight: 600; }

  /* ---- Buttons: ghost secondaries, one height ---- */
  .stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondary"] {
      background: transparent;
      border: 1px solid var(--line);
      color: #1d3e7d;
  }
  .stButton button[kind="secondary"]:hover {
      border-color: #1d3e7d;
      background: #f7f9fd;
  }

  /* ---- Metrics: quieter numbers ---- */
  [data-testid="stMetricValue"] { font-size: 1.45rem !important; font-weight: 700; }
  [data-testid="stMetricLabel"] { opacity: .65; }

  /* ---- Chat: bubbles, not a white box ---- */
  .chat-head {
      background: linear-gradient(135deg, #16305f, #1d3e7d);
      color: #eef2fb;
      border-radius: 10px;
      padding: .4rem .8rem;
      font-weight: 700;
      font-size: .92rem;
      margin-bottom: var(--sp-2);
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
  .chip-yellow { background: #fdf1d8; color: #8f5f00; }   /* pending */
  .chip-green  { background: #e6f4ea; color: #137333; }   /* closed/done */
  .chip-gray   { background: #edeae1; color: #5a564c; }   /* neutral */
  .chip-gold   { background: #e7edf9; color: #1d3e7d; }   /* legacy alias → info */
  .chip-blue   { background: #e7edf9; color: #1d3e7d; }   /* info */

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
  /* when each phase is recommended to close — the axis answers «by when», not
     just «where are we» */
  .step-due { font-size: .66rem; opacity: .6; direction: ltr; }
  .step-due.late { color: #b3261e; opacity: 1; font-weight: 700; }
  .stepper-mini .step { min-width: 46px; font-size: .62rem; }
  .stepper-mini .step .dot { width: 24px; height: 24px; font-size: .72rem;
                             border-width: 2px; }
  .stepper-mini .step-bar { margin-top: 11px; height: 2px; }
  .stepper-mini .step-due { font-size: .6rem; }

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


def _pipeline_row(m: dict, progress: dict, overdue_count: int,
                  owners: Optional[list[str]] = None) -> None:
    """One Mishmar in the instructor's pipeline: who owns it, which phase it is
    in, and by when each phase should close."""
    over_chip = _chip(f"{overdue_count} באיחור", "red") if overdue_count else ""
    topic = _clean(m.get("topic") or "") or "<span style='opacity:.5'>ללא נושא</span>"
    with st.container(border=True):
        c1, c2 = st.columns([2.2, 1.8])
        c1.markdown(
            f"<div class='task-desc'>#{m['id']:02d} · {_fmt_date(m['gregorian_date'])} · "
            f"{topic}</div>"
            f"<div>{_countdown_chip(m)}"
            f"{_owners_chip([] if m.get('is_staff_built') else (owners or []))}"
            f"{over_chip}</div>",
            unsafe_allow_html=True,
        )
        c2.markdown(_phase_axis_html(progress, m, mini=True), unsafe_allow_html=True)


def _needs_attention(mishmarim: list[dict], upcoming: list[dict],
                     owners: dict[int, list[str]]) -> None:
    """The four things that actually stall an evening, none of them visible on
    a task board: an evening with no topic and a date approaching, slots with
    no speaker days before the night, the SAME person being courted by two
    pairs at once, and an approach that was sent and never answered."""
    today = _date_cls.today()
    soon = {m["id"]: (_parse_date(m["gregorian_date"]) - today).days
            for m in upcoming if _parse_date(m["gregorian_date"])}

    no_topic = [m for m in upcoming
                if not m.get("topic") and 0 <= soon.get(m["id"], 999) <= 21]

    # one query for every slot in the season, grouped here
    all_lessons = dm.get_all_lessons()
    by_mid: dict[int, list[dict]] = {}
    for l in all_lessons:
        by_mid.setdefault(l["mishmar_id"], []).append(l)
    open_slots = []
    for m in upcoming:
        if not (0 <= soon.get(m["id"], 999) <= 14):
            continue
        missing = [l for l in by_mid.get(m["id"], [])
                   if not l.get("is_break") and not l.get("speaker_name")
                   and (l.get("lesson_role") or "") != "חבורות"]
        if missing:
            open_slots.append((m, len(missing)))

    # the same name courted by two different pairs — the documented hazard of
    # ten trainees searching in parallel
    seen: dict[str, set[int]] = {}
    for l in all_lessons:
        name = (l.get("speaker_name") or "").strip()
        if name:
            seen.setdefault(name, set()).add(l["mishmar_id"])
    outreach = dm.get_all_outreach()
    for o in outreach:
        if o.get("mishmar_id") and o.get("name"):
            seen.setdefault(o["name"].strip(), set()).add(o["mishmar_id"])
    collisions = {n: sorted(ids) for n, ids in seen.items() if len(ids) > 1}

    # 📩 sent and quiet for more than ten days
    latest: dict[int, dict] = {}
    for o in outreach:          # newest first
        latest.setdefault(o["speaker_id"], o)
    waiting = []
    for o in latest.values():
        if "📩" not in (o.get("status") or ""):
            continue
        when = _parse_date((o.get("created_at") or "")[:10])
        if when and (today - when).days >= 10:
            waiting.append((o, (today - when).days))

    total = len(no_topic) + len(open_slots) + len(collisions) + len(waiting)
    if not total:
        return
    st.markdown(f"#### מה דורש התערבות ({total})")
    st.caption("ארבעה דברים שמעכבים ערב ואף לוח משימות לא מראה.")
    with st.container(border=True):
        for m in no_topic:
            st.markdown(
                f"🎯 **#{m['id']:02d}** בעוד {soon[m['id']]} ימים ועדיין ללא נושא — "
                f"{' · '.join(owners.get(m['id'], [])) or 'צוות'}")
        for m, n in open_slots:
            st.markdown(
                f"🎤 **#{m['id']:02d}** בעוד {soon[m['id']]} ימים · {n} מקטעים בלי מרצה — "
                f"{' · '.join(owners.get(m['id'], [])) or 'צוות'}")
        for name, ids in list(collisions.items())[:6]:
            st.markdown(
                f"⚠️ **{_clean(name)}** מופיע/ה בשני משמרים: "
                + ", ".join(f"#{i:02d}" for i in ids)
                + " — ודאו שזה מכוון, ושלא שני זוגות פונים לאותו אדם.")
        for o, days in waiting[:6]:
            st.markdown(
                f"📩 **{_clean(o.get('name') or '')}** — נשלחה פנייה לפני {days} ימים "
                f"ואין תשובה.")


def show_admin_dashboard() -> None:
    st.title("לוח הבקרה")
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
    c1.metric("משמרים", len(mishmarim))
    c2.metric("עם נושא סגור", f"{len(with_topic)} / {len(mishmarim)}")
    c3.metric("סה״כ הוצאות", _fmt_nis(budget["total_spent"]))
    # What a Mishmar that ALREADY HAPPENED cost, on average. The old tile here
    # showed the ₪500 indication — a constant, which tells nobody anything.
    # Dividing by all 21 would read as a collapsing average all season, so the
    # denominator is the evenings behind us, and it says which those are.
    avg = budget["avg_per_past"]
    with c4:
        if avg is None:
            st.metric("ממוצע הוצאות למשמר", "—")
            st.caption("עוד לא התקיים משמר")
        else:
            st.metric("ממוצע הוצאות למשמר", _fmt_nis(avg),
                      delta=_fmt_nis(avg - budget["nominal_per_mishmar"]),
                      delta_color="off")
            st.caption(f"על פני {budget['past_count']} משמרים שהתקיימו · "
                       f"מול אינדיקציה של {_fmt_nis(budget['nominal_per_mishmar'])}")
    if total_all:
        st.progress(done_all / total_all,
                    text=f"התקדמות העונה: {done_all}/{total_all} משימות הושלמו")

    st.divider()
    st.markdown("#### עבר את התאריך המומלץ")
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
                        # A door first. Until now this card could only flip a
                        # status — the instructor could see that a task was
                        # late and had no way to reach the Mishmar it belongs
                        # to, which is exactly how «the overdue tasks don't
                        # appear in the Mishmar» happens: they do, one screen
                        # and three clicks away, in a folded phase.
                        b1, b2, b3 = st.columns([1.1, 1, 1])
                        if b1.button("פתח ↗", key=f"ov-go-{t['id']}",
                                     help="פותח את המשמר הזה, במקום שבו סוגרים את המשימה"):
                            _goto(NAV_WORKFILE, t["mishmar_id"],
                                  _section_for_category(t.get("category")),
                                  task_focus=t["id"])
                        b2.button("✓ הושלם", key=f"ov-dn-{t['id']}", type="primary",
                                  on_click=_set_status, args=(t["id"], "DONE"))
                        b3.button("▶ בתהליך", key=f"ov-ip-{t['id']}",
                                  on_click=_set_status, args=(t["id"], "IN PROGRESS"))

    # ---- The pipeline: what the flat table never told anyone ----
    st.divider()
    st.markdown("#### צינור המשמרים")
    st.caption("כל משמר, איפה הוא עומד בבנייה, ומי מחזיק אותו. לפי סדר הערבים.")
    today = _date_cls.today()
    upcoming = [m for m in mishmarim
                if (_parse_date(m.get("gregorian_date")) or today) >= today]
    past = [m for m in mishmarim if m not in upcoming]
    owners = dm.get_owners_by_mishmar()
    for m in upcoming:
        _pipeline_row(m, progress[m["id"]], over_by_mid.get(m["id"], 0),
                      owners.get(m["id"], []))
    if past:
        with st.expander(f"🌙 משמרים שהתקיימו ({len(past)})"):
            for m in reversed(past):
                _pipeline_row(m, progress[m["id"]], over_by_mid.get(m["id"], 0),
                              owners.get(m["id"], []))

    _needs_attention(mishmarim, upcoming, owners)

    with st.expander("💰 תקציב — מה עלו המשמרים שכבר התקיימו"):
        st.caption(
            "אין תקרה עונתית — זהו מעקב הוצאות מצטבר. חריגה במשמר בודד **אינה שגיאה**: "
            "היא נמשכת מהסעיף התקציבי הכולל, ומשמרים זולים מאזנים אותה."
        )
        rows_by_mid = dm.get_budget_rows()
        spent_rows = []
        for r in budget["per_mishmar"]:
            if not r["past"]:
                continue
            lines = rows_by_mid.get(r["id"], [])
            who = " · ".join(
                f"{(b.get('description') or b['expense_type'])}: {_fmt_nis(float(b.get('actual_cost') or 0))}"
                for b in lines) or "לא נרשמו שורות"
            spent_rows.append({
                "פירוט": who,
                "הוצאה": _fmt_nis(r["spent"]),
                "נושא": r["topic"] or "—",
                "תאריך": _fmt_date(r["gregorian_date"]),
                "משמר": f"#{r['id']:02d}",
            })
        if spent_rows:
            st.dataframe(spent_rows, width="stretch", hide_index=True)
            st.caption(
                f"סה״כ {_fmt_nis(budget['past_spent'])} על פני "
                f"{budget['past_count']} משמרים · ממוצע "
                f"{_fmt_nis(budget['avg_per_past'] or 0)} מול אינדיקציה של "
                f"{_fmt_nis(budget['nominal_per_mishmar'])}."
            )
        else:
            st.info("עוד לא התקיים משמר — הטבלה תתמלא אחרי הערב הראשון.")

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

from datetime import date as _date_cls, timedelta as _timedelta


# The workfile is two columns now — the evening on the right, the tasks on the
# left — so a «section» is no longer a tab you switch to but a panel that opens.
WF_STRUCTURE, WF_LOGISTICS, WF_AFTER = "structure", "logistics", "after"
WF_PANELS = (WF_STRUCTURE, WF_LOGISTICS, WF_AFTER)
WF_PANEL_LABELS = {
    WF_STRUCTURE: "🎯 מבנה הערב",
    WF_LOGISTICS: "📦 לוגיסטיקה",
    WF_AFTER: "🌙 משוב וסיכום",
}


def _goto(nav: str, mishmar_id: Optional[int] = None,
          section: Optional[str] = None, lesson_focus=None,
          task_focus: Optional[int] = None) -> None:
    """Deep-link navigation. STAGED, not direct: Streamlit forbids writing a
    widget's session key after that widget was drawn in the current run, and
    the nav radio always draws before any button that calls this. So the
    request is parked under one key and applied at the very top of main(),
    before a single widget exists. This is what turns «התחל» from a status
    button into a door to the right place.

    `lesson_focus` is a lesson id or the sentinel «first_open_speaker».
    `task_focus` is a task id: the landing page resolves it to a slot — its
    explicit `lesson_id`, else `suggest_lesson_for_task` — which is how the
    instructor's overdue card can open the right slot without the dashboard
    loading a timeline for all 21 Mishmarim."""
    st.session_state["_goto_req"] = {
        "nav": nav, "workfile_mishmar": mishmar_id,
        "wf_section": section, "wf_focus_lesson": lesson_focus,
        "wf_focus_task": task_focus,
    }
    # scope="app": a door pressed inside a fragment must restart the whole
    # page, not just the fragment it was pressed in.
    st.rerun(scope="app")


def _set_status(task_id: int, status: str, toast: Optional[str] = None) -> None:
    """on_click handler: the write happens BEFORE the run that follows the
    click, so that single run already shows it — no st.rerun(), no second run.
    This is the difference between one round-trip and two full page builds."""
    dm.update_task_status(task_id, status)
    if toast:
        st.toast(toast)


def _toggle(key: str, value) -> None:
    """on_click handler for the editors: open if closed, close if open."""
    st.session_state[key] = None if st.session_state.get(key) == value else value


def _set_state(key: str, value) -> None:
    st.session_state[key] = value


def _apply_goto() -> None:
    """First thing in main(): land any staged deep link while no widget exists."""
    req = st.session_state.pop("_goto_req", None)
    if not req:
        return
    st.session_state["nav"] = req["nav"]
    if req.get("workfile_mishmar") is not None:
        st.session_state["workfile_mishmar"] = req["workfile_mishmar"]
    if req.get("wf_section") is not None:
        # Panels are expanders, and an expander remembers its open state in the
        # browser — so `expanded=True` alone is ignored on a second visit.
        # Bumping the nonce remounts all three, which makes the requested one
        # genuinely open.
        st.session_state["wf_panel"] = req["wf_section"]
        st.session_state["wf_panel_nonce"] = st.session_state.get("wf_panel_nonce", 0) + 1
    st.session_state["wf_focus_lesson"] = req.get("wf_focus_lesson")
    st.session_state["wf_focus_task"] = req.get("wf_focus_task")


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
        return WF_STRUCTURE
    if category == "אחרי":
        return WF_AFTER
    return WF_LOGISTICS


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
            b1.button("↩ החזר לתהליך", key=f"{key_prefix}-{t['id']}-re",
                      on_click=_set_status, args=(t["id"], "IN PROGRESS"))
        else:
            b1.button("✓ הושלם", key=f"{key_prefix}-{t['id']}-dn", type="primary",
                      on_click=_set_status,
                      args=(t["id"], "DONE", f"«{_clean(t['task_description'])[:40]}» הושלם 🎉"))
            if link:
                # «התחל» is a DOOR, not a status flip: it lands on the section
                # of the workfile where this task is actually done.
                if b2.button("פתח ↗", key=f"{key_prefix}-{t['id']}-go",
                             help="פותח את המקום שבו סוגרים את המשימה"):
                    _goto(NAV_WORKFILE, t.get("mishmar_id"),
                          _section_for_category(t.get("category")))
            else:
                other = ("↩ לעשות", "TO DO") if status == "IN PROGRESS" else ("▶ התחל", "IN PROGRESS")
                b2.button(other[0], key=f"{key_prefix}-{t['id']}-mv",
                          on_click=_set_status, args=(t["id"], other[1]))


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


def _phase_due(ph: dict, m: dict) -> Optional[_date_cls]:
    """When this phase is recommended to be closed.

    The tasks already carry derived due dates, so the earliest open one IS the
    phase's deadline. Only when a phase has no dated task do we fall back to
    the offset table — that keeps the axis honest for a Mishmar whose tasks
    were edited by hand.
    """
    dates = [_parse_date(t.get("due_date")) for t in ph["tasks"] if t.get("due_date")]
    dates = [d for d in dates if d]
    if dates:
        return min(dates)
    base = _parse_date(m.get("gregorian_date"))
    offsets = [dm.DEADLINE_OFFSETS_DAYS[c] for c in ph["categories"]
               if c in dm.DEADLINE_OFFSETS_DAYS]
    if base and offsets:
        return base - _timedelta(days=max(offsets))
    return None


def _phase_axis_html(progress: dict, m: dict, mini: bool = False) -> str:
    """The four phases as an axis, with WHEN each one is due underneath.

    This replaces «7 משימות» on the pipeline row: a count says how much is
    left, the axis says where the evening stands and whether it is late.
    """
    today = _date_cls.today()
    parts = [f"<div class='stepper{' stepper-mini' if mini else ''}'>"]
    for i, ph in enumerate(progress["phases"]):
        cls = "done" if ph["complete"] else ("current" if i == progress["current"] else "")
        due = _phase_due(ph, m)
        late = bool(due and not ph["complete"] and due < today)
        label = f"{due.day}.{due.month}" if due else "—"
        parts.append(
            f"<div class='step {cls}'><div class='dot'>"
            f"{'✓' if ph['complete'] else ph['icon']}</div>"
            f"<div>{ph['label']}</div>"
            f"<div class='step-due{' late' if late else ''}'>{label}</div></div>"
        )
        if i < len(progress["phases"]) - 1:
            parts.append(f"<div class='step-bar {'done' if ph['complete'] else ''}'></div>")
    parts.append("</div>")
    return "".join(parts)


def _owners_chip(owners: list[str]) -> str:
    """The pair, by name. «זוג חניכים» told the instructor nothing."""
    return _chip("👥 " + " · ".join(owners), "blue") if owners else _chip("צוות", "gray")


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


def _mini_mishmar_card(m: dict, progress: dict,
                       owners: Optional[list[str]] = None) -> None:
    """Same grammar as the instructor's pipeline row — partner names and the
    dated phase axis — so a trainee reads their own queue the same way."""
    with st.container(border=True):
        st.markdown(
            f"<div class='task-desc'>#{m['id']:02d} · {_fmt_date(m['gregorian_date'])}</div>"
            f"<div>{_countdown_chip(m)}{_owners_chip(owners or [])}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(_phase_axis_html(progress, m, mini=True), unsafe_allow_html=True)


def show_student_view(student_name: str) -> None:
    student_id = st.session_state.student_id
    st.title(f"שלום, {student_name}")

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
        st.markdown(f"#### עבר התאריך המומלץ במשמרים אחרים ({len(overdue)})")
        st.caption("המלצה — לא חוק. אבל אלה קודמים לכל השאר.")
        _card_grid(sorted(overdue, key=lambda t: t.get("due_date") or "9999"),
                   "ovd", link=True)

    st.markdown("#### המשמר הבא שלי")
    _next_mishmar_hero(hero, progress[hero["id"]])

    others = [m for m in mine if m["id"] != hero["id"]]
    if others:
        st.markdown("#### שאר המשמרים שלי")
        st.caption("הם מחכים בתור — כל אחד ייפתח כשיגיע זמנו. קובץ העבודה פתוח לכולם תמיד.")
        owners = dm.get_owners_by_mishmar()
        cols = st.columns(min(3, max(1, len(others))))
        for i, m in enumerate(others):
            with cols[i % len(cols)]:
                _mini_mishmar_card(m, progress[m["id"]], owners.get(m["id"], []))

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


CONFIDENCE_CHIP = {
    "high": ("🟢 ודאות גבוהה", "green"),
    "medium": ("🟡 ודאות בינונית", "yellow"),
    "low": ("🟠 ודאות נמוכה", "gold"),
}
REGION_HELP = {
    "🟢": "עד ~40 דקות מהמדרשה",
    "🟡": "כשעה–שעה וחצי",
    "🔴": "שעתיים ומעלה — צריך הסדר הסעה",
    "⚪": "מיקום לא ידוע מהתוצאות",
}


def _scout_card(c: dict, mid: Optional[int], lesson: str, idx: int) -> None:
    """One researched candidate: who they are, where they are, why they fit,
    and the evidence. Everything here is grounded in what the search returned —
    a field the scout could not support comes back empty, and contact details
    are never carried at all."""
    name = c["name"]
    display = f"{c['title']} {name}" if c.get("title") else name
    with st.container(border=True):
        label, kind = CONFIDENCE_CHIP.get(c.get("confidence") or "low",
                                          CONFIDENCE_CHIP["low"])
        chips = [_chip(label, kind)]
        flag = c.get("region_flag") or "⚪"
        chips.append(_chip(f"{flag} {c.get('region_hint') or 'מיקום לא ידוע'}",
                           "green" if flag == "🟢" else
                           "yellow" if flag == "🟡" else
                           "red" if flag == "🔴" else "gray"))
        for f in c.get("flags", []):
            chips.append(_chip(f, "yellow"))
        st.markdown(
            f"<div class='task-desc'>{_clean(display)}</div><div>{''.join(chips)}</div>",
            unsafe_allow_html=True,
        )
        st.caption(REGION_HELP.get(flag, "") + (
            " · הוודאות הועלתה על סמך עמוד מוסדי ופעילות עדכנית"
            if c.get("promoted") else ""))
        if c.get("affiliation"):
            st.markdown(f"🏛️ {_clean(c['affiliation'])}")
        if c.get("bio"):
            st.markdown(_clean(c["bio"]))
        if c.get("rationale"):
            st.caption("למה מתאים: " + _clean(c["rationale"]))
        if c.get("recent_years"):
            st.caption("פעיל/ה לפי התוצאות בשנים: " + ", ".join(c["recent_years"][:4]))
        if c.get("already_approached"):
            st.warning("‼️ כבר פנו לאדם הזה השנה — בדקו את היומן במאגר לפני פנייה נוספת.")
        if c.get("history"):
            st.caption(f"🕓 אצלנו: {c['history']}")
        if c.get("link"):
            st.markdown(f"📄 [מאמר / ראיון בנושא]({c['link']})")
        for ev in (c.get("evidence") or [])[:3]:
            if ev.get("href"):
                st.caption(f"[{_clean(ev.get('title') or ev['href'])[:80]}]({ev['href']})")
        st.caption("☎️ פרטי קשר לא נשלפים מהרשת — מצאו אותם דרך העמוד המוסדי.")

        ac1, ac2, ac3 = st.columns([1.6, 1.2, 0.7])
        if mid:
            lessons = dm.get_lessons(mid)
            slots = [l for l in lessons if not l.get("is_break")]
            labels = {l["id"]: f"{l.get('start_time') or ''} · {l.get('title') or ''}".strip(" ·")
                      or f"מקטע {l['slot_order']}" for l in slots}
            if labels:
                lid = ac1.selectbox("מקטע", list(labels), format_func=lambda i: labels[i],
                                    key=f"slot-{idx}-{name}", label_visibility="collapsed")
                # A candidate, NOT the speaker: you gather three and close one
                # later, in the workfile. Assigning straight from a search made
                # the first plausible name the decision.
                if ac2.button("➕ הוסף כמועמד", key=f"cand-{idx}-{name}", type="primary",
                              help="מוסיף לרשימת המועמדים של המקטע — ולמאגר המשותף"):
                    href = c.get("link") or next(
                        (e.get("href") for e in c.get("evidence") or [] if e.get("href")), None)
                    dm.add_new_speaker(
                        name=display, expertise_topics=c.get("bio") or None,
                        verification_url=href, source_type="web_search",
                        lesson_fit=lesson or None,
                        notes=" · ".join(x for x in [
                            c.get("affiliation"), c.get("region_hint"),
                            "נמצא בסריקת מרצים · ⚠️ לאמת לפני פנייה"] if x))
                    dm.add_lesson_speaker(lid, name,
                                          student_id=st.session_state.student_id)
                    st.toast(f"«{name}» נוסף כמועמד ל{labels[lid]} — ולמאגר")
                    st.rerun()
            else:
                ac1.caption("אין עדיין מקטעים במשמר — צרו את שלד הערב קודם")
        else:
            ac1.caption("בחרו משמר למעלה כדי להוסיף כמועמד")
        if ac3.button("אמת", key=f"scv-{idx}-{name}"):
            st.session_state["verify_name"] = name


LESSON_ANGLES = {
    "— בלי המלצה, לחפש בכל הזוויות —": "",
    "יסודות — היסטוריון, חוקר, איש אקדמיה": "1",
    "ערעור / טוויסט — פילוסוף, הוגה, מחשבת ישראל": "2",
    "זווית מפתיעה — אמנות, קולנוע, פסיכולוגיה, סוציולוגיה": "3",
}


def show_speaker_search() -> None:
    st.title("חיפוש מרצים")
    st.caption(
        "סריקה של הרשת — לא של המאגר — וחמישה שמות שנבדקו. "
        "כל שם הוא ⚠️ לאמת עד שבדקתם, ופרטי קשר לעולם לא נשלפים אוטומטית."
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
        hero = (min(upcoming, key=lambda m: _parse_date(m["gregorian_date"]) or today)
                if upcoming else mine[-1])
        default_mid = hero["id"]
        default_topic = hero.get("topic") or ""

    with st.form("speaker_search"):
        f1, f2 = st.columns(2)
        topic = f1.text_input("נושא המשמר", value=default_topic,
                              placeholder="למשל: תשובה")
        lesson_topic = f2.text_input("נושא השיעור", placeholder="למשל: חרטה ואחריות")
        g1, g2 = st.columns([1.4, 1.2])
        lesson = LESSON_ANGLES[g1.selectbox(
            "המלצה: איזו זווית? (רשות)", options=list(LESSON_ANGLES))]
        labels = {m["id"]: f"#{m['id']:02d} · {m['gregorian_date']}" for m in mine}
        mid = g2.selectbox(
            "לאיזה משמר משבצים?", [None, *labels],
            format_func=lambda i: "— בלי שיבוץ —" if i is None else labels[i],
            index=(list(labels).index(default_mid) + 1) if default_mid in labels else 0,
        ) if mine else None
        go = st.form_submit_button("🔎 סרוק את הרשת", type="primary")

    st.caption(
        "סריקה יסודית מרחיבה את החיפוש עד שיש ארבעה שמות בוודאות גבוהה, "
        "ומעמיקה על כל אחד מהם — זה לוקח דקה או שתיים, פעם אחת. "
        "התוצאה נשמרת, ואפשר לפתוח אותה שוב בלי לשלם עליה."
    )

    # The scout fires ONLY here (rerun trap). Its result is saved, so returning
    # to the screen — or a partner opening it — costs nothing.
    if go and (topic.strip() or lesson_topic.strip()):
        with st.spinner("סורק את הרשת · מעמיק על המועמדים · מסנן…"):
            res = ca.scout_speakers(topic.strip(), lesson, lesson_topic.strip())
        st.session_state["scout_result"] = res
        st.session_state.pop("verify_name", None)
        st.session_state.pop("verify_cache", None)
        if not res.get("fallback"):
            dm.save_search(topic.strip(), res, mishmar_id=mid,
                           lesson_topic=lesson_topic.strip(), angle=lesson,
                           student_id=st.session_state.student_id)

    # Previous scans of this Mishmar — what the pair (or the partner) already tried.
    saved = dm.get_searches(mid) if mid else dm.get_searches()
    if saved:
        with st.expander(f"🕘 חיפושים קודמים ({len(saved)})"):
            for row in saved:
                r1, r2 = st.columns([4, 1])
                r1.markdown(
                    f"**{_clean(row['topic'])}**"
                    + (f" · {_clean(row['lesson_topic'])}" if row.get("lesson_topic") else "")
                    + f" <span class='card-meta'>{(row.get('created_at') or '')[:10]} · "
                    + f"{len((row.get('results_json') or {}).get('candidates') or [])} מועמדים</span>",
                    unsafe_allow_html=True)
                if r2.button("פתח", key=f"reopen-{row['id']}"):
                    st.session_state["scout_result"] = row["results_json"]
                    st.rerun()

    result = st.session_state.get("scout_result")
    if not result:
        st.info("הזינו נושא — של המשמר, של השיעור, או שניהם — ולחצו סרוק.")
        return

    raw = result.get("raw") or {}
    if raw.get("skipped"):
        st.info(raw.get("reason") or "החיפוש דולג.")
        return

    if not result.get("fallback"):
        st.divider()
        cands = result["candidates"]
        strong = result.get("strong", 0)
        target = result.get("target", 4)
        st.markdown(f"#### המועמדים שנבדקו ({len(cands)})")
        # Say plainly what was found. Padding four weak names into a list that
        # LOOKS like it hit the target is the one thing this screen must not do.
        if strong >= target:
            st.success(f"✅ {strong} מועמדים בוודאות גבוהה — כפי שביקשנו.")
        else:
            st.info(
                f"נמצאו **{strong}** בוודאות גבוהה מתוך {target} שביקשנו "
                f"(אחרי {raw.get('rounds_used', 1)} סבבי חיפוש ו-{len(raw.get('queries') or [])} שאילתות). "
                "השאר מוצגים עם דרגת הוודאות שלהם — אפשר לחדד את נושא השיעור ולסרוק שוב."
            )
        for i in range(0, len(cands), 2):
            cols = st.columns(2)
            for col, c in zip(cols, cands[i:i + 2]):
                with col:
                    _scout_card(c, mid, lesson, i)
        if result.get("rejected"):
            with st.expander(f"🚫 נשקלו ונפסלו ({len(result['rejected'])})"):
                st.caption("כדי שלא תחפשו שוב את אותם שמות.")
                for r in result["rejected"]:
                    st.markdown(f"- **{_clean(r.get('name') or '')}** — {_clean(r.get('why') or '')}")
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
        st.markdown(f"#### אימות — {name}")
        # Cache per name. Without this the verification re-ran on every rerun —
        # i.e. on every unrelated button click on this page — which is exactly
        # the burst pattern the throttle exists to prevent.
        vcache = st.session_state.setdefault("verify_cache", {})
        if name not in vcache:
            with st.spinner("מאמת…"):
                vcache[name] = ss.verify_speaker(name, topic=raw.get("subject") or "")
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


def _raw_search_results(result: dict) -> None:
    """The pre-synthesis listing — also the whole page when there is no API key."""
    st.markdown(f"##### 🌐 שמות חדשים מהרשת ({len(result.get('web_names') or [])})")
    st.caption(
        "כל שם כאן הוא ⚠️ **לאמת** — הוא חולץ מתוצאות חיפוש, לא מהמאגר. "
        "פרטי קשר לעולם לא ממולאים אוטומטית."
    )
    for i, entry in enumerate((result.get("web_names") or [])[:20]):
        _speaker_card(entry, result.get("topic") or "", result.get("lesson") or "1", i)

    if result.get("errors"):
        st.markdown("##### שאילתות שלא רצו — הריצו ידנית")
        for err in result["errors"]:
            st.markdown(
                f"`{err['query']}` — [DuckDuckGo]({err['manual']['duckduckgo']}) · "
                f"[Google]({err['manual']['google']})"
            )


def _speaker_index_card(r: dict, history: list[dict], dup_count: int,
                        teaching: Optional[dict] = None) -> None:
    """A person in the shared memory. The face of the card is who they are and
    what they bring; opening it gives what you actually need before calling —
    where they are, how to reach them, whether they have taught here, and how
    it landed. Outreach status is NOT on this screen: the index is memory, and
    a booking state told nobody anything while browsing."""
    teaching = teaching or {}
    with st.container(border=True):
        warn = " ⚠️" if dup_count > 1 else ""
        domains = [d.strip() for d in (r.get("domains") or "").split(",") if d.strip()]
        chips = "".join(_chip(d, "blue") for d in domains[:3])
        taught = teaching.get("taught") or []
        if taught:
            chips += _chip(f"לימד/ה {len(taught)}×", "green")
        st.markdown(
            f"<div class='task-desc'>{_clean(dm.display_name(r))}{warn}</div>"
            f"<div>{chips}</div>",
            unsafe_allow_html=True,
        )
        topics = (r.get("expertise_topics") or "").strip()
        if topics and topics != "TBD":
            st.caption(_clean(topics)[:80])
        elif r.get("notes"):
            st.caption("📝 " + _clean(r["notes"])[:80])

        with st.expander("פרטים"):
            if dup_count > 1:
                st.warning(
                    f"יש {dup_count} רשומות בשם הזה — ככל הנראה אנשים שונים. "
                    "לא מאחדים אותם על דעתנו; ודאו שזה האדם הנכון."
                )
            st.markdown(
                f"**תואר:** {_clean(r.get('title') or '—')}  \n"
                f"**תחומים:** {_clean(', '.join(domains) or 'לא סווג')}  \n"
                f"**נושאים כפי שנרשמו:** {_clean(topics or 'TBD')}  \n"
                f"**אזור:** {_clean(r.get('region') or '⚪ לא ידוע')}  \n"
                f"**מתאים לשיעור:** {_clean(r.get('lesson_fit') or 'TBD')}"
            )
            st.markdown(f"**פרטי קשר:** {_clean(r.get('contact') or 'TBD')}")
            if r.get("verification_url"):
                st.markdown(f"🔗 [עמוד מוסדי / אימות]({r['verification_url']})")
            if r.get("notes"):
                st.caption("📝 " + _clean(r["notes"]))

            if taught:
                st.markdown("**לימד/ה אצלנו:**")
                for l in taught[:6]:
                    st.markdown(
                        f"- משמר #{l['mishmar_id']:02d}"
                        + (f" · {_clean(l['title'])}" if l.get("title") else ""))
            else:
                st.caption("עוד לא לימד/ה אצלנו — לפי מה שרשום במערכת.")

            fbs = teaching.get("feedback") or []
            if fbs:
                st.markdown("**משוב שנרשם:**")
                for f in fbs[:5]:
                    stars = "⭐" * (f.get("rating") or 0)
                    st.markdown(f"- {stars} {_clean(f.get('lesson_title') or '')}")
                    if f.get("what_worked"):
                        st.caption(_clean(f["what_worked"])[:160])
                    if f.get("what_didnt"):
                        st.caption("פחות: " + _clean(f["what_didnt"])[:160])

            if history:
                with st.expander(f"יומן פניות ({len(history)})"):
                    for o in history[:8]:
                        who = o.get("student_name") or "צוות"
                        where = f"משמר #{o['mishmar_id']:02d}" if o.get("mishmar_id") else "—"
                        st.markdown(
                            f"- {o['status']} · {where} · {who} · {(o.get('created_at') or '')[:10]}"
                            + (f" — {_clean(o['note'])}" if o.get("note") else ""))


def show_speaker_index() -> None:
    """Institutional memory. The workfile and the search screen WRITE here;
    this page is where you come to remember."""
    st.title("מאגר המרצים")
    st.caption(
        "הזיכרון המשותף של כל הצוותים: מי קיים, מה הם מביאים, ומה קרה איתם. "
        "שיבוץ ופניות נעשים בבניית הערב — כאן נזכרים."
    )

    # THREE queries for the whole page — nothing per-card.
    rows = dm.get_speakers_with_status()
    outreach_by_speaker: dict[int, list[dict]] = {}
    for o in dm.get_all_outreach():
        outreach_by_speaker.setdefault(o["speaker_id"], []).append(o)
    teaching = dm.get_teaching_history()

    query = st.text_input("חיפוש", placeholder="שם · תחום · הערה — למשל: תשובה",
                          label_visibility="collapsed")

    # Broad domains, with counts. The old chips were the raw free-text tags:
    # 33 of them across 46 people, almost all used once, so every filter
    # matched exactly one person.
    counts: dict[str, int] = {}
    for r in rows:
        for d in (r.get("domains") or "").split(","):
            d = d.strip()
            if d:
                counts[d] = counts.get(d, 0) + 1
    unclassified = sum(1 for r in rows if not (r.get("domains") or "").strip())
    NO_DOMAIN = "ללא תחום"
    options = [f"{d} ({n})" for d, n in
               sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    if unclassified:
        options.append(f"{NO_DOMAIN} ({unclassified})")
    picked_label = st.pills("תחומים", options, key="speaker_domain_filter",
                            label_visibility="collapsed") if options else None
    picked = picked_label.rsplit(" (", 1)[0] if picked_label else None

    if query.strip():
        q = dm.normalize_name(query).lower()
        rows = [
            r for r in rows
            if q in dm.normalize_name(r["name"]).lower()
            or q in (r.get("expertise_topics") or "").lower()
            or q in (r.get("domains") or "").lower()
            or q in (r.get("notes") or "").lower()
        ]
    if picked == NO_DOMAIN:
        rows = [r for r in rows if not (r.get("domains") or "").strip()]
    elif picked:
        rows = [r for r in rows if picked in (r.get("domains") or "")]

    st.caption(
        f"{len(rows)} במאגר"
        + (f" · {unclassified} עדיין בלי תחום רשום — נסווגו רק כשיש מה לסווג לפיו"
           if unclassified and not picked else "")
    )
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
                    r, outreach_by_speaker.get(r["speaker_id"], []), seen[r["name"]],
                    teaching.get(r["name"]))
    if len(rows) > shown:
        st.button(f"הצג עוד ({len(rows) - shown} נוספים)", width="stretch",
                  on_click=_set_state, args=("speaker_page_size", shown + 24))


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


def _close_candidate(lesson_id: int, name: str, mid: int) -> None:
    res = dm.close_lesson_speaker(lesson_id, name, mishmar_id=mid,
                                  student_id=st.session_state.student_id)
    st.toast(f"«{res['closed']}» נסגר לשיעור"
             + (f" · הוסרו: {', '.join(res['removed'])}" if res["removed"] else ""))


def _candidate_rows(mid: int, l: dict, cands: list[dict]) -> None:
    """The lesson's optional-speakers list: name · phone · status · actions.
    Once one is closed, the list collapses to that single row."""
    closed = l.get("speaker_name")
    if closed:
        sc1, sc2 = st.columns([3.4, 1])
        sc1.markdown(f"🎤 **{_clean(closed)}** {_chip('✅ סגור', 'green')}",
                     unsafe_allow_html=True)
        # Closing used to be one-way. People change their minds, and the
        # journal keeps the history either way.
        sc2.button("🔄 החלף", key=f"reopen-{l['id']}",
                   help="משחרר את המקטע וממשיך לרשימת המועמדים",
                   on_click=dm.reopen_lesson_speaker, args=(l["id"],))
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
        skey = f"cst-{cand['id']}"
        c2.selectbox(
            "סטטוס", dm.SPEAKER_STATUSES,
            index=dm.SPEAKER_STATUSES.index(cur) if cur in dm.SPEAKER_STATUSES else 0,
            key=skey, label_visibility="collapsed",
            on_change=lambda cid=cand["id"], k=skey: dm.update_lesson_speaker_status(
                cid, st.session_state[k], mishmar_id=mid,
                student_id=st.session_state.student_id))
        c3.button("✅ סגרנו", key=f"close-{cand['id']}",
                  help="הופך למרצה של השיעור; שאר המועמדים יוסרו",
                  on_click=_close_candidate, args=(l["id"], cand["name"], mid))
        c4.button("🗑", key=f"rmc-{cand['id']}",
                  on_click=dm.delete_lesson_candidate, args=(cand["id"],))

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
        dm.set_lesson_duration(mid, l["id"], int(duration))
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


def _topic_and_structure(mid: int, tasks: list[dict],
                         lessons: Optional[list[dict]] = None) -> None:
    m = dm.get_mishmar(mid)

    # --- the topic: a hero form until it exists, a quiet line after ---
    if not m.get("topic"):
        with st.container(border=True):
            st.markdown("#### הצעד הראשון: לסגור נושא")
            st.caption(
                "הנושא הוא מנוע הערב כולו — מומלץ לסגור אותו כשלושה שבועות לפני. "
                "אין רעיון? בדקו בארכיון אם היה משמר דומה, ודברו עם המדריך."
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
    st.markdown("#### מבנה הערב")
    st.caption(
        "השעות נגזרות מהמשכים — שינוי משך של משבצת מזרים את כל הערב. "
        "שלושה שיעורים ושעת חבורות הם ברירת המחדל; אפשר לשנות הכל."
    )
    if lessons is None:
        lessons = dm.get_lessons(mid)
    if not lessons:
        if st.button("✨ צור את שלד הערב (20:00, שלושה שיעורים + חבורות)",
                     type="primary", width="stretch"):
            dm.create_default_timeline(mid)
            st.rerun()
        return

    candidates = dm.get_lesson_speakers(mid, lessons=lessons)
    linked = dm.get_tasks_for_lesson(tasks=tasks)
    editing = st.session_state.get("editing_lesson")
    focus = st.session_state.pop("wf_focus_lesson", None)

    # A task that arrived through a «פתח» door resolves to ONE slot here: its
    # explicit lesson_id if a human tied it, otherwise the wording-based guess.
    # A guess that lands nowhere is a legitimate outcome — the section still
    # opens, just without a slot singled out.
    focus_task_id = st.session_state.pop("wf_focus_task", None)
    focus_task = next((t for t in tasks if t["id"] == focus_task_id), None) \
        if focus_task_id else None
    if focus_task and focus in (None, "first_open_speaker"):
        focus = focus_task.get("lesson_id") or dm.suggest_lesson_for_task(focus_task, lessons)

    highlight = focus if isinstance(focus, int) else None
    if focus == "first_open_speaker":
        for l in lessons:
            if not l.get("is_break") and not l.get("speaker_name") \
                    and (l.get("lesson_role") or "") != "חבורות":
                st.session_state["editing_lesson"] = editing = l["id"]
                break
    if focus_task:
        where = "" if highlight else " — לא זוהה מקטע ספציפי, בחרו למטה"
        st.info(f"⤴ הגעתם מהמשימה «{_clean(focus_task['task_description'])}»{where}")

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
            bc2.number_input(
                "דק'", min_value=5, max_value=90, step=5,
                value=int(l.get("duration_minutes") or 30),
                key=f"brk-{l['id']}", label_visibility="collapsed",
                on_change=lambda mid=mid, lid=l["id"], k=f"brk-{l['id']}":
                    dm.set_lesson_duration(mid, lid, int(st.session_state[k])))
            continue

        lesson_no += 1
        cands = candidates.get(l["id"], [])
        is_chavurot = (l.get("lesson_role") or "") == "חבורות"
        my_tasks = linked.get(l["id"], [])
        with st.container(border=True):
            head = _clean(l.get("title") or "") or f"שיעור {lesson_no} — ללא כותרת"
            if is_chavurot and not l.get("title"):
                head = "חבורות"
            chips = []
            if l.get("lesson_role"):
                chips.append(_chip(l["lesson_role"], "gold"))
            if l.get("format"):
                chips.append(_chip(l["format"], "gray"))
            if not l.get("speaker_name") and cands:
                chips.append(_chip(f"{len(cands)} מועמדים", "blue"))
            open_here = [t for t in my_tasks if t["status"] != "DONE"]
            if open_here:
                kind = "red" if any(t.get("overdue") for t in open_here) else "gray"
                chips.append(_chip(f"{len(open_here)} משימות", kind))
            st.markdown(
                f"<div class='task-desc'>"
                f"<span class='chip chip-blue' dir='ltr'>{_slot_times(l)}</span> {head}</div>"
                f"<div>{''.join(chips)}</div>",
                unsafe_allow_html=True,
            )
            if highlight == l["id"]:
                st.markdown(
                    "<div style='background:#e7edf9;border-right:4px solid #1d3e7d;"
                    "border-radius:8px;padding:.4rem .7rem;margin:.3rem 0'>"
                    "⤴ <b>כאן סוגרים את המשימה שהגעתם ממנה.</b></div>",
                    unsafe_allow_html=True,
                )
            if l.get("description"):
                st.caption(_clean(l["description"])[:180])
            if l.get("source_url"):
                st.caption(f"📎 [דף מקורות]({l['source_url']})")

            _candidate_rows(mid, l, cands)

            # The tasks that belong to THIS slot, closable where the work is.
            # This is the half that was missing: the board could point at the
            # evening, and the evening could not point back.
            for t in open_here:
                tc1, tc2 = st.columns([5, 1])
                tc1.markdown(
                    f"<div class='card-meta' style='opacity:.9'>📌 "
                    f"{_clean(t['task_description'])}"
                    + (_chip("באיחור", "red") if t.get("overdue") else "")
                    + "</div>", unsafe_allow_html=True)
                tc2.button("✓", key=f"lt-{t['id']}", help="סמן שבוצע",
                           on_click=_set_status, args=(t["id"], "DONE", "בוצע 🎉"))

            # The slot's open work. Each button either OPENS the task that
            # already covers it or CREATES one tied to this slot — no longer a
            # dead-end that merely opens the board and leaves you to search.
            todo = []
            if not l.get("speaker_name"):
                if is_chavurot:
                    todo.append(("👥 מי מעביר", "תוכן",
                                 f"לסגור מי מעביר {head}"))
                else:
                    todo.append(("🎤 סגירת מרצה", "מרצים",
                                 f"סגירת מרצה — {head}"))
            if not l.get("source_url"):
                todo.append(("📎 דף מקורות", "תוכן", f"דף מקורות — {head}"))
            tc = st.columns([1.1, 1.1, 0.9, 0.9])
            for i, (label, category, text) in enumerate(todo[:2]):
                if tc[i].button(label, key=f"td-{l['id']}-{i}",
                                help="פותח את המשימה — או פותח אותה אם עוד אין"):
                    existing = next((t for t in open_here
                                     if t.get("category") == category), None)
                    if existing is None:
                        dm.add_task(mid, text, category=category, lesson_id=l["id"])
                        st.toast(f"נפתחה משימה «{text}» וקושרה למקטע")
                    _goto(NAV_WORKFILE, mid, WF_STRUCTURE)
            tc[3].button("✏️ עריכה", key=f"ed-{l['id']}",
                         on_click=_toggle, args=("editing_lesson", l["id"]))

            if editing == l["id"]:
                _lesson_form(mid, l)

    ac1, ac2 = st.columns(2)
    ac1.button("➕ הוסף מקטע", on_click=dm.add_lesson_slot, args=(mid, 60))
    ac2.button("➕ הוסף הפסקה", on_click=dm.add_break, args=(mid, 15))


def _slot_label(l: dict, index: int) -> str:
    """How a slot is named in a task's «שייך למקטע» line."""
    title = (l.get("title") or "").strip()
    if not title and (l.get("lesson_role") or "") == "חבורות":
        title = "חבורות"
    return f"{l.get('start_time') or '--:--'} · {title or f'מקטע {index}'}"


def _wf_panel(key: str, count: str = "") -> "st.delta_generator.DeltaGenerator":
    """One collapsible panel of the evening column.

    `key` on the expander plus a nonce is what makes a deep link work: an
    expander remembers its open state client-side, so remounting is the only
    reliable way to force one open.
    """
    nonce = st.session_state.get("wf_panel_nonce", 0)
    label = WF_PANEL_LABELS[key] + (f" · {count}" if count else "")
    return st.expander(label, expanded=(st.session_state.get("wf_panel", WF_STRUCTURE) == key),
                       key=f"wfp-{key}-{nonce}")


def _logistics_list(mid: int, kind: str, items: list[dict],
                    title: str, hint: str, placeholder: str,
                    detail_placeholder: Optional[str] = None) -> None:
    """The refreshments list and the חבורות room allocation are one widget:
    rows with a label, an optional detail, and a done box."""
    st.markdown(f"**{title}**")
    st.caption(hint)
    for it in items:
        c1, c2, c3 = st.columns([0.5, 4.5, 0.6])
        c1.checkbox("בוצע", value=bool(it.get("done")), key=f"lg-{it['id']}",
                    label_visibility="collapsed",
                    on_change=lambda i=it["id"], k=f"lg-{it['id']}":
                        dm.toggle_logistics_item(i, st.session_state[k]))
        style = "opacity:.5;text-decoration:line-through" if it.get("done") else ""
        c2.markdown(
            f"<div style='{style}'>{_clean(it['label'])}"
            + (f" <span class='card-meta'>{_clean(it['detail'])}</span>"
               if it.get("detail") else "")
            + "</div>", unsafe_allow_html=True)
        c3.button("🗑", key=f"lgx-{it['id']}",
                  on_click=dm.delete_logistics_item, args=(it["id"],))
    if not items:
        st.caption("עוד לא נוספו שורות.")
    with st.form(f"lgadd-{mid}-{kind}", border=False):
        f1, f2, f3 = st.columns([2.2, 2, 0.9])
        label = f1.text_input("פריט", key=f"lgl-{mid}-{kind}",
                              label_visibility="collapsed", placeholder=placeholder)
        detail = f2.text_input("פירוט", key=f"lgd-{mid}-{kind}",
                               label_visibility="collapsed",
                               placeholder=detail_placeholder or "פירוט (רשות)")
        if f3.form_submit_button("➕ הוסף") and label.strip():
            dm.add_logistics_item(mid, kind, label.strip(), detail)
            st.rerun()


def _logistics_panel(mid: int, m: dict) -> None:
    """Everything the evening needs that is not a lesson: what to buy, which
    room each חבורה sits in, and the invitation that goes out."""
    items = dm.get_logistics(mid)
    if items.get("_missing"):
        st.warning(
            "טבלת הלוגיסטיקה עוד לא קיימת במסד. הריצו את `supabase_schema.sql` "
            "ב-Supabase → SQL Editor, ורשימת הכיבוד, חלוקת החללים וההזמנה ייפתחו כאן."
        )
        return
    _logistics_list(
        mid, "כיבוד", items.get("כיבוד", []), "🍎 רשימת הכיבוד",
        "מה קונים לערב. סימון ✓ = נקנה.",
        "למשל: עוגות · פיצוחים · שתייה חמה", "כמות · מי קונה")
    st.divider()
    _logistics_list(
        mid, "חלל", items.get("חלל", []), "🚪 חלוקת החללים לחבורות",
        "איזו חבורה יושבת איפה, ומי מוביל אותה.",
        "למשל: בית המדרש · כיתה 2 · המרפסת", "מי מוביל · כמה משתתפים")
    st.divider()
    st.markdown("**✉️ ההזמנה למשמר**")
    st.caption("הטקסט שנשלח בוואטסאפ, וקישור לפוסטר אם יש.")
    with st.form(f"inv-{mid}", border=False):
        text = st.text_area("נוסח ההזמנה", value=m.get("invitation_text") or "",
                            height=120,
                            placeholder="מי · מה · מתי · איפה — ולמה כדאי לבוא")
        url = st.text_input("קישור לפוסטר", value=m.get("invitation_url") or "",
                            placeholder="https://…")
        if st.form_submit_button("💾 שמור הזמנה", type="primary"):
            dm.set_invitation(mid, text=text, url=url)
            st.toast("ההזמנה נשמרה"); st.rerun()
    if m.get("invitation_url"):
        st.caption(f"📎 [הפוסטר]({m['invitation_url']})")


def _reset_panel(mid: int, m: dict) -> None:
    """Start the evening over. Deliberately two steps and deliberately loud —
    it deletes a season's worth of a pair's work."""
    with st.expander("⚠️ איפוס המשמר"):
        st.caption(
            "מוחק את **כל** מה שנבנה כאן — מבנה הערב והמרצים, המשימות, הלוגיסטיקה, "
            "התקציב והמשוב — ומחזיר את המשמר לנקודת ההתחלה: בחירת נושא, "
            "עם רשימת המשימות המקורית. "
            "**יומן הפניות למרצים לא נמחק** — הוא הזיכרון המשותף של כל הזוגות, "
            "ומחיקה שלו הייתה מוחקת מידע של אחרים."
        )
        ok = st.checkbox(f"אני מבין/ה — לאפס את משמר #{mid:02d}", key=f"rst-ok-{mid}")
        if st.button("🗑 אפס את המשמר", key=f"rst-{mid}", disabled=not ok):
            res = dm.reset_mishmar(mid)
            st.session_state["editing_lesson"] = None
            st.session_state["editing_task"] = None
            st.toast(
                f"המשמר אופס · נמחקו {res['lessons']} מקטעים, {res['tasks']} משימות · "
                f"הוחזרו {res['tasks_restored']} משימות מקוריות")
            st.rerun()


def _safe(fn, *args, **kwargs) -> None:
    """Render one panel; if it fails, say so IN that panel and let the rest of
    the page live.

    Not a blanket try/except: it wraps exactly the three evening panels. A
    missing `logistics_items` used to raise inside the right column, which
    aborted the whole render — so the tasks column and the reset button
    vanished too, and the reported symptom was «the two columns are gone».
    """
    try:
        fn(*args, **kwargs)
    except Exception as exc:                      # noqa: BLE001 — deliberate
        st.error(
            "החלק הזה לא נטען. אם הרצתם לאחרונה גרסה חדשה — "
            "הריצו שוב את `supabase_schema.sql` ב-Supabase."
        )
        st.caption(f"{type(exc).__name__}: {exc}"[:300])


def _workfile_columns(mid: int, tasks: list[dict], progress: dict) -> None:
    """The workfile: the EVENING on the right, the TASKS on the left.

    Under RTL st.columns mirrors, so declaring [evening, tasks] puts the
    evening on the right — where a Hebrew reader starts. On a phone Streamlit
    stacks them, evening first.
    """
    m = dm.get_mishmar(mid)
    # No topic yet: there is exactly one thing to do, and two columns of empty
    # panels would only hide it.
    if not m.get("topic"):
        _topic_and_structure(mid, tasks)
        _reset_panel(mid, m)
        return

    lessons = dm.get_lessons(mid)
    right, left = st.columns([1.15, 1], gap="medium")
    with right:
        with _wf_panel(WF_STRUCTURE, f"{len([l for l in lessons if not l.get('is_break')])} מקטעים"):
            _safe(_topic_and_structure, mid, tasks, lessons=lessons)
        with _wf_panel(WF_LOGISTICS):
            _safe(_logistics_panel, mid, m)
        with _wf_panel(WF_AFTER):
            _safe(_after_tab, mid)
        _reset_panel(mid, m)
    with left:
        st.markdown("#### ✅ המשימות")
        _tasks_tab(mid, progress, lessons)


def _wf_task_card(t: dict, mid: int, key_prefix: str,
                  lessons: Optional[list[dict]] = None) -> None:
    """A workfile task card: the task is the point, the controls are small.
    «פתח» is a door to where the task is done; edit/delete live behind tiny
    icons; completion is one small check.

    When the Mishmar has a timeline, the card also says WHICH slot the task
    belongs to — the explicit link if one was made, otherwise the guess, shown
    as a guess."""
    lessons = lessons or []
    slots = [l for l in lessons if not l.get("is_break")]
    slot_id = t.get("lesson_id")
    guessed = False
    if not slot_id and slots:
        slot_id = dm.suggest_lesson_for_task(t, lessons)
        guessed = bool(slot_id)
    slot = next((l for l in slots if l["id"] == slot_id), None)

    with st.container(border=True):
        chips = []
        if t.get("category"):
            chips.append(_chip(t["category"], "gold"))
        if t.get("overdue"):
            chips.append(_chip("באיחור", "red"))
        if slot:
            idx = slots.index(slot) + 1
            chips.append(_chip(("≈ " if guessed else "🔗 ") + _slot_label(slot, idx),
                               "blue"))
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
        c1, c2, c3, c4 = st.columns([1.5, 0.7, 0.6, 0.6])
        if t["status"] != "DONE":
            if c1.button("פתח ↗", key=f"{k}-go", help="למקום שבו סוגרים את זה"):
                if t.get("category") == "אחרי":
                    _goto(NAV_WORKFILE, mid, WF_AFTER)
                elif slot or t.get("category") in ("מרצים", "תוכן", "נושא"):
                    # the evening builder resolves the exact slot from the task
                    _goto(NAV_WORKFILE, mid, WF_STRUCTURE, task_focus=t["id"])
                else:
                    _goto(NAV_WORKFILE, mid, WF_LOGISTICS)
            c2.button("✓", key=f"{k}-dn", help="סמן שבוצע",
                      on_click=_set_status, args=(t["id"], "DONE", "בוצע 🎉"))
        else:
            c1.button("↩ החזר", key=f"{k}-re",
                      on_click=_set_status, args=(t["id"], "TO DO"))
        c3.button("✏️", key=f"{k}-ed", help="עריכה",
                  on_click=_toggle, args=("editing_task", t["id"]))
        c4.button("🗑", key=f"{k}-rm", help="מחיקה",
                  on_click=dm.delete_task, args=(t["id"],))

        if st.session_state.get("editing_task") == t["id"]:
            with st.form(f"edit-{k}", border=False):
                desc = st.text_input("כותרת", value=t["task_description"])
                details = st.text_area("תיאור", value=t.get("details") or "",
                                       height=68)
                due = st.text_input("מומלץ עד (dd.mm.yyyy)",
                                    value=_fmt_date(t["due_date"]) if t.get("due_date") else "")
                # Tying a task to a slot by hand — this is what turns the guess
                # above into a fact. «לא שייך למקטע» is the honest default:
                # כיבוד, קישוט and הזמנה belong to the evening, not to a slot.
                choices = [None] + [l["id"] for l in slots]
                labels = {l["id"]: _slot_label(l, i + 1)
                          for i, l in enumerate(slots)}
                new_slot = st.selectbox(
                    "שייך למקטע בערב", choices,
                    index=choices.index(t["lesson_id"])
                    if t.get("lesson_id") in choices else 0,
                    format_func=lambda i: labels.get(i, "— לא שייך למקטע —"),
                    key=f"{k}-slot") if slots else None
                if st.form_submit_button("💾 שמור", type="primary"):
                    iso = None
                    d = _parse_date(due)
                    if d:
                        iso = d.isoformat()
                    dm.edit_task(t["id"], description=desc, details=details,
                                 due_date=iso if due.strip() else None)
                    if slots and new_slot != t.get("lesson_id"):
                        dm.link_task_to_lesson(t["id"], new_slot)
                    st.session_state["editing_task"] = None
                    st.toast("נשמר"); st.rerun()


def _wf_task_grid(items: list[dict], mid: int, prefix: str,
                  lessons: Optional[list[dict]] = None, per_row: int = 1) -> None:
    """One card per row by default — the task board is a column beside the
    evening now, not a full-width page, and two cards across would wrap."""
    if per_row <= 1:
        for t in items:
            _wf_task_card(t, mid, prefix, lessons=lessons)
        return
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, t in zip(cols, items[i:i + per_row]):
            with col:
                _wf_task_card(t, mid, prefix, lessons=lessons)


def _tasks_tab(mid: int, progress: dict, lessons: Optional[list[dict]] = None) -> None:
    """Phase accordion of OPEN tasks; day-of work as its own group; the
    after-work lives in the after-Mishmar section; done tasks sink to the
    bottom, out of the way entirely."""
    by_due = lambda t: t.get("due_date") or "9999"
    all_tasks = [t for ph in progress["phases"] for t in ph["tasks"]]
    done = [t for t in all_tasks if t["status"] == "DONE"]

    # Overdue first, pinned open, spanning EVERY phase — including אחרי and
    # יום המשמר, which the phase accordion below deliberately routes elsewhere.
    # Without this a task the instructor's dashboard is shouting about sits
    # folded inside a shut phase, and the board looks like it lost it.
    late = sorted([t for t in all_tasks
                   if t["status"] != "DONE" and t.get("overdue")], key=by_due)
    if late:
        st.markdown(f"#### ⏰ עברו את התאריך המומלץ ({len(late)})")
        st.caption("התאריכים הם המלצה, לא חוק — אבל אלה המשימות שמחזיקות את הערב.")
        _wf_task_grid(late, mid, f"wf{mid}-late", lessons)
        st.divider()

    for i, ph in enumerate(progress["phases"]):
        # every phase, «אחרי» included: the tasks column is the ONLY task board
        # now, so a phase routed elsewhere would simply disappear.
        open_ts = [t for t in ph["tasks"]
                   if t["status"] != "DONE" and t.get("category") != "יום המשמר"]
        if not open_ts:
            continue
        state = "▸" if i == progress["current"] else ("✓" if ph["complete"] else "🔒")
        # a folded phase must still declare its lateness
        n_late = sum(1 for t in open_ts if t.get("overdue"))
        badge = f" · {n_late} באיחור" if n_late else ""
        with st.expander(f"{state} {ph['icon']} {ph['label']} ({len(open_ts)}{badge})",
                         expanded=(i == progress["current"] or bool(n_late))):
            _wf_task_grid(sorted(open_ts, key=by_due), mid, f"wf{mid}-{ph['key']}",
                           lessons)

    day_of = [t for t in all_tasks
              if t.get("category") == "יום המשמר" and t["status"] != "DONE"]
    if day_of:
        with st.expander(f"🕯️ יום המשמר עצמו ({len(day_of)})"):
            st.caption("הדברים שנעשים בערב עצמו — לא לוגיסטיקה מוקדמת.")
            _wf_task_grid(sorted(day_of, key=by_due), mid, f"wf{mid}-day", lessons)

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
            _wf_task_grid(done, mid, f"wf{mid}-done", lessons)


def _after_tab(mid: int) -> None:
    m = dm.get_mishmar(mid)
    lessons = [l for l in dm.get_lessons(mid) if not l.get("is_break")]
    tasks = [dm.annotate_deadline(t) for t in dm.get_tasks_for_mishmar(mid)]

    # --- feedback, per evening slot ---
    st.markdown("#### משוב על הערב — לפי מקטעים")
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
    st.title("ניהול המשמר")
    mid = _mishmar_picker("workfile_mishmar")
    if not mid:
        return

    _workfile_body(mid)


@st.fragment
def _workfile_body(mid: int) -> None:
    """Everything under the Mishmar picker, as ONE fragment: a click inside it
    (✓ on a task, an editor toggle, a candidate status) reruns this body only —
    the sidebar, the header and the chat panel are not re-executed. Its reads
    are cached, so the rerun is the write plus a few dict lookups."""
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

    st.divider()
    _workfile_columns(mid, tasks, progress)


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


@st.fragment
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
    close.button("✕", key="chat_close", help="קפל את הצ׳אט",
                 on_click=_set_state, args=("chat_open", False))

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
    # on the main column immediately. scope="app" because the panel is a
    # fragment — a plain rerun would refresh only the chat.
    st.rerun(scope="app")


# --------------------------------------------------------------------------
# 5. Sidebar + routing
# --------------------------------------------------------------------------


# The conversational assistant is OFF. Everything it needs is still here —
# render_chat_panel, chat_agent's tool loop, the chat_messages rows — so this
# single flag brings it back. The scout that powers «חיפוש מרצים» lives in the
# same module and is unaffected: it is one model call on an explicit button,
# not a conversation.
CHAT_ENABLED = False

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
        st.caption(f"גרסה: {build_stamp()}")
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
    # The database can be a version behind the code — the SQL file has stamped
    # its own version since v2, and until now nobody read it. The result was a
    # redacted APIError three screens deep instead of one sentence here.
    if info.get("schema_stale"):
        have = info.get("schema_version")
        st.error(
            f"⚠️ **המסד מפגר אחרי הקוד.** גרסת הסכימה במסד: "
            f"**{have if have is not None else 'לא מסומנת'}**, "
            f"והקוד דורש **{info.get('required_version')}**.\n\n"
            "פתחו את Supabase → SQL Editor, הדביקו את `supabase_schema.sql` "
            "מהריפו והריצו. הקובץ אידמפוטנטי — הרצה חוזרת בטוחה. "
            "עד אז חלקים מהמסכים יופיעו ריקים."
        )

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
    if not CHAT_ENABLED:
        _route_main()
        return

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
        else:
            st.button("💬", key="chat_reopen", help="פתח את שותף הבנייה",
                      on_click=_set_state, args=("chat_open", True))


if __name__ == "__main__":
    main()
