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
    for key in ("role", "user_name", "student_id"):
        st.session_state[key] = None
    st.cache_data.clear()


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
    if st.session_state.role == "admin":
        show_admin_dashboard()
    else:
        show_student_view(st.session_state.user_name)


if __name__ == "__main__":
    main()
