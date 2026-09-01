"""The conversational assistant's panel — dormant.

`app.CHAT_ENABLED` is False: the trainees' app runs without a chat, and this
module is imported only when that flag is on. It was moved out of app.py so
that the 170 lines nobody renders stop costing every reader (and every agent)
the scroll. Nothing here was changed in the move except that the panel now
receives the user's Mishmarim from the caller instead of reaching into app.py.
"""

from __future__ import annotations

import streamlit as st

import chat_agent as ca
import data_manager as dm

CHAT_CSS = """
<style>
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

  @media (max-width: 740px) {
      .chat-head small { display: none; }
      [data-testid="stChatMessage"] { padding: .5rem .7rem; }
  }
</style>
"""


def _set_state(key: str, value) -> None:
    st.session_state[key] = value


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
def render_chat_panel(mine: list[dict]) -> None:
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


