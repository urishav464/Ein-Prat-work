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
  /* Every Material icon is a <span translate="no"> with the icon NAME as its
     text — the bundle sets translate:`no` in exactly two places, both icon
     components — and only some of them carry stIconMaterial: the status
     widget's tick is stExpanderIconCheck, and under the Assistant override it
     painted the literal word "check", clipped to "chec" beside «הסריקה הסתיימה». */
  [data-testid="stIconMaterial"], [data-testid^="stExpanderIcon"], span[translate="no"] {
      font-family: 'Material Symbols Rounded' !important;
      line-height: 1; overflow: visible;
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
  [data-testid="stMetric"],
  /* Streamlit portals these to <body>, OUTSIDE stAppViewContainer — so every
     rule scoped to the app container stops at their edge and they render LTR:
     the dialog's title hugged the left, «כותרת | משך» read left-to-right and
     the button row put «שמור» on the wrong side. Measured: the dialog's parent
     IS <body> and its computed direction was ltr. */
  [data-testid="stDialog"],
  [data-testid="stPopoverBody"],
  [data-testid="stToastContainer"],
  [data-testid="stSelectboxVirtualDropdown"] {
      direction: rtl;
      text-align: right;
  }
  .stTextInput input,
  .stTextArea textarea,
  /* 1.62 renders the select through react-aria, NOT BaseWeb: the old
     `div[data-baseweb="select"]` matched nothing (measured: 0 nodes). */
  [data-testid="stSelectbox"] input {
      direction: rtl;
      text-align: right;
  }
  [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { direction: rtl; }
  h1, h2, h3, h4, h5, h6 { text-align: right; }
  [data-testid="stDataFrame"] { direction: rtl; }
  .stButton button, .stFormSubmitButton button { direction: rtl; }
  [data-testid="stExpander"] summary { direction: rtl; text-align: right; }
  [data-testid="stProgress"] { direction: rtl; }
  /* segmented_control and st.pills label through DynamicButtonLabel, not markdown —
     the markdown RTL rule never reaches them (the stCaptionContainer lesson again).
     stButtonGroup is the WHOLE widget and it is `display: block` — label plus one
     child div that holds the buttons — so `justify-content` on it was always a
     no-op, and the layout rules belong on that child.
     Measured on 1.64 at 1500px: the row is `flex; nowrap; overflow: auto hidden`
     with no gap, the four Hebrew labels add up to 408px inside a 404px row, and
     Streamlit rounds the end corners by DOM order — so under RTL «בלי המלצה» got
     the LEFT corners while sitting at the RIGHT edge, with its box ending 1px
     past the row's own, and at 390px 76px of the group was clipped away outright.
     Wrapping, a gap and a symmetric radius on every button retire the whole
     first/last-child question instead of trying to mirror it. */
  [data-testid="stButtonGroup"] { direction: rtl; }
  [data-testid="stButtonGroup"] > div {
      flex-wrap: wrap;
      gap: var(--sp-1);
      overflow: visible;
      justify-content: flex-start;
  }
  /* and `margin-inline-start: -1px` on every button but the last — Streamlit
     collapsing adjacent borders into one. Under RTL inline-start is the RIGHT,
     so it drags the first button 1px past the row's own edge: precisely the
     «box sitting on the border» in the report. With a real gap between the
     pills there is no shared border left to collapse. */
  [data-testid="stButtonGroup"] > div > button { border-radius: 8px; margin: 0; }
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
  /* ---- The nav cards. The label IS the card; the radio circle is hidden.
     The radio's DOM moved between Streamlit 1.63 and 1.64: a react-aria
     wrapper <div> now sits between the group and each <label>, so every
     `radiogroup > label` rule went dead on Cloud the day 1.64 shipped
     (2026-09-15) — while the local 1.63 harness kept passing. The anchors
     below are the ones BOTH bundles carry: `stRadioGroup`, the <label> that
     carries `stRadioOption`, react-aria's `data-selected` / `data-focus-visible`
     on that label, and the drawn circle by its emotion target class in each
     version PLUS one structural :has() that fits both depths. ---- */
  /* every control in the sidebar tracks its full width. Streamlit sizes the
     radio's own element container to its CONTENT (measured: 137px inside a
     239px block), and the group's align-items is flex-start, so each level
     down to the label has to be told to stretch. */
  [data-testid="stSidebar"] .stButton,
  [data-testid="stSidebar"] .stButton button,
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
      width: 100%;
      box-sizing: border-box;
  }
  [data-testid="stSidebar"] [data-testid="stElementContainer"],
  [data-testid="stSidebar"] [data-testid="stRadio"],
  [data-testid="stSidebar"] [data-testid="stRadioGroup"],
  [data-testid="stSidebar"] [data-testid="stRadioGroup"] > * {
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
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div,
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div {
      width: 100%;
      justify-content: center;
      text-align: center;
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] {
      text-align: center;
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] p { text-align: center; }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] {
      align-self: stretch;
      box-sizing: border-box;
      display: flex; align-items: center; justify-content: center;
      background: #ffffff;
      border: 1px solid #e8e2d4;
      border-radius: 12px;
      padding: 0.6rem 0.9rem;
      margin-bottom: var(--sp-2);
      width: 100%;
      cursor: pointer;
      transition: border-color .15s ease, background .15s ease, transform .1s ease;
      box-shadow: 0 1px 2px rgba(60,50,20,.05);
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {
      border-color: #1d3e7d;
      transform: translateX(-2px);
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected],
  [data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) {
      background: linear-gradient(135deg, #e7edf9, #dbe5f6);
      border-color: #1d3e7d;
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected] p,
  [data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:checked) p {
      font-weight: 700;
  }
  /* the visual radio mark. The hidden input sits in the label's first <span>
     in both versions; the drawn 16px circle is `label > div > div > div` in
     1.63 and `label > div > div` in 1.64 — so it is named by its emotion
     target class per version, and structurally: the one div whose only child
     is an empty div (the inner dot). Hiding them keeps the label clickable —
     it still wraps the real input. */
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] > span:first-child {
      display: none;
  }
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] [class*="eqiohyi4"],
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] [class*="e1mpz0hj4"],
  [data-testid="stSidebar"] label[data-testid="stRadioOption"] div:has(> div:only-child:empty) {
      display: none;
  }

  /* ---- Keyboard: a ring you can see. Streamlit's own focus style is faint on
     tertiary buttons and absent on the nav cards (their radio input is hidden). ---- */
  button:focus-visible, input:focus-visible, textarea:focus-visible,
  [data-testid="stSelectbox"] div[role="group"]:focus-within,
  [data-testid="stSidebar"] label[data-testid="stRadioOption"][data-focus-visible],
  [data-testid="stSidebar"] label[data-testid="stRadioOption"]:has(input:focus-visible) {
      outline: 2px solid #1d3e7d !important;
      outline-offset: 2px;
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
  /* a reading width: wide mode on a 2560px screen stretched the dashboard
     across the whole glass. 1320px keeps four cards and stops there. */
  [data-testid="stMainBlockContainer"] { max-width: 1320px; }
  h1 { margin-bottom: var(--sp-2) !important; }
  h3, h4 { margin: var(--sp-5) 0 var(--sp-2) !important; }
  /* a quiet navy accent instead of an emoji per heading. A physical RIGHT
     border, not a ::before — Streamlit headings are flex containers and an
     inline pseudo-box drifts to the line's END under RTL. */
  .stMarkdown h4 {
      border-right: 4px solid #1d3e7d;
      padding-right: var(--sp-2);
  }
  hr {
      border-color: var(--line) !important;
      opacity: .6;
      margin: var(--sp-4) 0 !important;
  }
  [data-testid="stCaptionContainer"] { line-height: 1.5; color: #5c6577 !important; }

  /* ---- Cards: depth from a hairline, not a shadow.
     Streamlit 1.62 draws st.container(border=True) on the stVerticalBlock
     ITSELF (1px at 20% text colour, 8px radius, 15px padding) — the old
     `stVerticalBlockBorderWrapper` is gone from the bundle, and this rule was
     dead for a whole release. The next anchor tried, data-test-scroll-behavior,
     is ALSO on width-only, keyed and fragment wrappers (measured: the workfile
     wrapper and the metric column turned white). So cards opt in: every
     st.container(border=True) that is a card carries key="card-…", and this
     rule names nothing Streamlit can rename. ---- */
  [class*="st-key-card-"] {
      background: #ffffff;
      border: 1px solid var(--line) !important;
      border-radius: 12px !important;
      padding: var(--sp-4) !important;
      gap: var(--sp-2);
      box-shadow: 0 1px 2px rgba(29, 62, 125, 0.05);
  }

  /* ---- Fields must read as fields on BOTH surfaces. config.toml's
     secondaryBackgroundColor is #fff, so Streamlit draws inputs white with a
     white border — invisible on a white card or in a dialog. ---- */
  [data-testid="stTextInputRootElement"],
  [data-testid="stNumberInputContainer"],
  [data-testid="stTextArea"] textarea,
  /* the select's control in 1.62 is react-aria's `div[role="group"]`; the old
     BaseWeb selector matched nothing, which is why every dropdown stayed
     white-on-white while the text inputs went cream */
  [data-testid="stSelectbox"] div[role="group"],
  [data-testid="stFileUploaderDropzone"] {
      background: #fbfaf6 !important;
      border: 1px solid var(--line) !important;
      border-radius: 8px !important;
  }
  [data-testid="stTextInputRootElement"]:focus-within,
  [data-testid="stNumberInputContainer"]:focus-within,
  [data-testid="stSelectbox"] div[role="group"]:focus-within {
      border-color: #1d3e7d !important;
  }
  /* Streamlit gives stMarkdownContainer `margin-bottom: -16px` to cancel the
     bottom margin of a trailing <p>. Our raw-HTML blocks end in a <div>, so
     the negative margin ate 16px of real content: measured, the action row of
     an overdue card started 11px ABOVE the end of its `.card-meta` line and
     drew on top of it. Give back the space wherever the last child is not a
     paragraph; Streamlit's own text blocks keep the cancellation. */
  [data-testid="stMarkdownContainer"]:has(> div:last-child) {
      margin-bottom: 0 !important;
  }
  /* four metric tiles, one height: the tile carrying a delta chip is 24px
     taller than the plain ones and hung below the row's baseline */
  [class*="st-key-metric-row"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"],
  [class*="st-key-metric-row"] { align-items: stretch; }
  [class*="st-key-metric-row"] [data-testid="stMetric"] { height: 100%; }
  /* the speaker index: three cards to a row, one height, doors at the foot */
  [class*="st-key-sp-row-"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
      align-items: stretch;
  }
  /* the column's block is already stretched to the row's height; the wrapper
     around the card is a flex ITEM in it and stays content-tall unless told */
  [class*="st-key-sp-row-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { height: 100%; }
  [class*="st-key-sp-row-"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] { flex: 1 1 auto; }
  [class*="st-key-card-sp-"] { height: 100%; }
  [class*="st-key-card-sp-"] > [data-testid="stElementContainer"]:last-child,
  [class*="st-key-card-sp-"] > [data-testid="stLayoutWrapper"]:last-child { margin-top: auto; }
  /* rhythm: 8px between a card's rows and between the controls in a row —
     Streamlit's default is 16px for both, which read as "too much air" */
  [data-testid="stHorizontalBlock"] { gap: var(--sp-2); }
  /* icon-only buttons: uniform small squares, one grammar everywhere */
  [class*="st-key-ib-"] button {
      width: 2rem !important; min-width: 2rem; height: 2rem; min-height: 2rem;
      padding: 0 !important; border: 1px solid var(--line); border-radius: 8px;
      background: #ffffff; color: #1d3e7d; line-height: 1; overflow: visible;
  }
  /* the glyph sits in a <p> with the body line-height; inside a 2rem box that
     overflowed and the emoji was clipped top and bottom */
  [class*="st-key-ib-"] button p { margin: 0; line-height: 1; font-size: 1rem; }
  [class*="st-key-ib-"] button:hover { border-color: #1d3e7d; background: #f7f9fd; }
  [class*="st-key-ib-dn-"] button, [class*="st-key-ib-lt-"] button { border-color: #1d3e7d; }
  /* the task editor is a popover under its ✏️: the trigger is the same 2rem
     box, minus the chevron every popover button carries; the body (portaled
     to <body>) would otherwise be as narrow as that box */
  [class*="st-key-ib-"] [data-testid="stPopoverButton"] [data-testid="stIconMaterial"],
  [class*="st-key-ib-"] [data-testid="stPopoverButton"] svg { display: none; }
  [data-testid="stPopoverBody"] { min-width: min(24rem, 92vw); }
  /* pipeline cards (instructor pc-, trainee mc-): the WHOLE card is the door.
     The tertiary title button is the card's first child; it is stretched over
     the card and made invisible — it keeps its label for screen readers and
     stays in the tab order — while the visible title is a markdown line. */
  [class*="st-key-card-pc-"], [class*="st-key-card-mc-"] {
      position: relative; cursor: pointer;
      transition: border-color .15s ease, box-shadow .15s ease;
  }
  [class*="st-key-card-pc-"]:hover, [class*="st-key-card-mc-"]:hover {
      border-color: #1d3e7d !important; box-shadow: 0 2px 6px rgba(29, 62, 125, 0.12);
  }
  [class*="st-key-card-pc-"] > [class*="st-key-pc-"],
  [class*="st-key-card-mc-"] > [class*="st-key-mc-"] {
      position: absolute; inset: 0; margin: 0; z-index: 1;
  }
  /* every wrapper between the container and the button must be full height,
     or the overlay is a 22px strip at the top of a 200px card (measured) */
  [class*="st-key-pc-"] > div, [class*="st-key-mc-"] > div,
  [class*="st-key-pc-"] .stButton, [class*="st-key-mc-"] .stButton { height: 100% !important; }
  [class*="st-key-pc-"] button, [class*="st-key-mc-"] button {
      width: 100% !important; height: 100% !important; min-height: 0;
      opacity: 0; cursor: pointer;
  }
  [class*="st-key-card-pc-"]:has(button:focus-visible),
  [class*="st-key-card-mc-"]:has(button:focus-visible) {
      outline: 2px solid #1d3e7d; outline-offset: 2px;
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

  /* ---- Metrics: tiles, the same grammar as the cards ---- */
  [data-testid="stMetric"] {
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: var(--sp-3) var(--sp-4);
      box-shadow: 0 1px 2px rgba(29, 62, 125, 0.05);
  }
  [data-testid="stMetricValue"] { font-size: 1.45rem !important; font-weight: 700; color: #1d3e7d; }
  /* Streamlit ellipsizes a metric label at the tile's width; Hebrew labels
     are long, so let them wrap instead of cutting «ממוצע הוצאות למשמר». */
  [data-testid="stMetricLabel"] { color: #5c6577; }
  [data-testid="stMetricLabel"] > div, [data-testid="stMetricLabel"] p {
      white-space: normal !important; overflow: visible !important; text-overflow: clip; }

  /* ---- Chips ---- */
  .chip {
      display: inline-block;
      padding: 1px var(--sp-2);
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
  .empty { color: #5c6577; padding: var(--sp-3) var(--sp-4); border: 1px dashed var(--line);
           border-radius: 12px; margin: var(--sp-2) 0; }
  /* solid muted ink, not opacity: .65 of the text colour on parchment was
     4.0:1 — under the 4.5:1 body-text bar. #5c6577 is 5.1:1 on parchment. */
  .card-meta { color: #5c6577; font-size: 0.78rem; margin-top: 4px; }

  /* ---- The phase stepper ---- */
  .stepper { display: flex; align-items: flex-start; margin: .5rem 0 .3rem; }
  .step { display: flex; flex-direction: column; align-items: center; gap: 3px;
          flex: 0 0 auto; font-size: .7rem; color: #5c6577; min-width: 58px; }
  .step .dot {
      width: 32px; height: 32px; border-radius: 50%;
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
  .step-due { font-size: .66rem; color: #5c6577; direction: ltr; }   /* solid: opacity .6 measured 2.4:1 */
  .step-due.late { color: #b3261e; opacity: 1; font-weight: 700; }
  .stepper-mini .step { min-width: 46px; font-size: .62rem; }
  .stepper-mini .step .dot { width: 24px; height: 24px; font-size: .72rem;
                             border-width: 2px; }
  .stepper-mini .step-bar { margin-top: 12px; height: 2px; }
  .stepper-mini .step-due { font-size: .6rem; }

  /* ---- Mobile: Streamlit stacks columns by itself below ~640px; these
     rules keep OUR custom pieces usable on a phone: the stepper compresses,
     chips wrap. ---- */
  /* Cards FILL their row instead of leaving a ragged stripe on the left: a
     fixed width is the flex-basis, and the leftover space is shared out. */
  .st-key-pipeline-grid > *, .st-key-pipeline-past > *, .st-key-my-grid > * { flex: 1 1 240px !important; }
  .st-key-overdue-grid > * { flex: 1 1 300px !important; }
  [data-testid="stMetric"] { flex: 1 1 150px; }
  /* A slot's task chips: a bordered container's default padding is a card's;
     a chip wants a sliver, so two fit beside each other in a half-width column. */
  /* a slot's tasks: one full-width row each, the ✓ in one left column — the
     content-width chips made a staircase of left edges with a ✓ on every step */
  [class*="st-key-lt-"] { padding: 4px var(--sp-2) !important; gap: 0 !important; border-radius: 8px !important; }
  [class*="st-key-lt-"] [data-testid="stMarkdownContainer"] p { margin: 0; font-size: .82rem; }
  /* an icon box that carries a word: same 2rem height and hairline as `ib-` */
  [class*="st-key-ibw-"] button {
      height: 2rem; min-height: 2rem; padding: 0 var(--sp-2) !important; font-size: .85rem;
      border: 1px solid var(--line); border-radius: 8px; background: #ffffff; color: #1d3e7d;
  }
  [class*="st-key-ibw-"] button:hover { border-color: #1d3e7d; background: #f7f9fd; }
  /* Only where several cards actually fit does a cap make sense: below this a
     lone card should use the whole column, not sit in a 340px stripe. */
  @media (min-width: 1101px) {
      .st-key-pipeline-grid > *, .st-key-pipeline-past > *, .st-key-my-grid > * { max-width: 340px; }
      .st-key-overdue-grid > * { max-width: 420px; }
  }

  /* Two workfile columns become one below 1100px — the width where a
     button row in a half-column starts wrapping. Pure CSS: no rerun. */
  @media (max-width: 1100px) {
      /* direct children only — the flex rows INSIDE the columns must stay rows */
      .st-key-wf-cols > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-direction: column; }
      .st-key-wf-cols > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; }
      /* the speaker index keeps three columns at any width — with the sidebar
         open at 900px that leaves ~140px per card and every name wraps. Two
         across here; Streamlit stacks columns natively below ~640px. */
      [class*="st-key-sp-row-"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
      [class*="st-key-sp-row-"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
          /* no grow: the third card of a row wraps and stays half-width,
             so the grid reads as a grid instead of alternating 2-then-1 */
          width: calc(50% - var(--sp-2)) !important; flex: 0 1 calc(50% - var(--sp-2)) !important;
      }
  }
  @media (max-width: 740px) {
      .stepper { flex-wrap: nowrap; overflow-x: auto; }
      .chip { white-space: nowrap; }
      [data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button { padding: .25rem .55rem; min-height: 2.1rem; }
      /* fixed-width cards fill the phone instead of leaving a stripe */
      .st-key-pipeline-grid > *, .st-key-pipeline-past > *, .st-key-overdue-grid > *,
      .st-key-my-grid > * {
          flex: 0 0 100% !important; width: 100% !important; max-width: 100% !important; }
      .step { min-width: 48px; font-size: .62rem; }
      .step .dot { width: 24px; height: 24px; font-size: .78rem; }
      .chip { font-size: .66rem; padding: 1px var(--sp-2); }
      h1 { font-size: 1.5rem !important; }
      .block-container { padding-left: .8rem; padding-right: .8rem; }
  }

</style>
"""


def inject_rtl() -> None:
    st.markdown(RTL_CSS, unsafe_allow_html=True)
    if CHAT_ENABLED:
        from chat_panel import CHAT_CSS
        st.markdown(CHAT_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# 3. Authentication (session state only — no passwords in v1)
# --------------------------------------------------------------------------


def _init_session() -> None:
    st.session_state.setdefault("role", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("student_id", None)


def logout() -> None:
    """Clear the session. Under Google auth, also end the OIDC session."""
    for key in ("role", "user_name", "student_id", "search_result", "nav"):
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
            f"<div style='color:#5c6577;font-size:.85rem'>מדרשת עין פרת</div></div>",
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
            # the example comes from the database, not from a literal: it used
            # to read «חניך 3», a placeholder name the trainee migration
            # deleted — and a name that does not exist logs in and shows nothing
            name = st.text_input(
                "השם שלך",
                placeholder=f"למשל: {student_names[0]}" if student_names else "השם המלא שלך",
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


def _waiting_by_mishmar(outreach: list[dict]) -> dict[int, int]:
    """How many approaches per Mishmar are sitting at 📩 with no answer —
    the latest entry per speaker decides, the log is newest first."""
    latest: dict[int, dict] = {}
    for o in outreach:
        latest.setdefault(o["speaker_id"], o)
    out: dict[int, int] = {}
    for o in latest.values():
        if "📩" in (o.get("status") or "") and o.get("mishmar_id"):
            out[o["mishmar_id"]] = out.get(o["mishmar_id"], 0) + 1
    return out


def _mishmar_card(m: dict, progress: dict, overdue_count: int, owners: list[str],
                  lessons: list[dict], waiting: int, spent: float) -> None:
    """One Mishmar as a small box on the instructor's board. The title is the
    door — it opens the workfile. Everything else on it is either a reason to
    step in or a reason not to: the pair, the phase, the speakers, lateness,
    money. Fixed width on purpose (four fit a 1040px content column): the grid
    around it wraps 4 / 2 / 1 across."""
    topic = (m.get("topic") or "").strip()
    title = f"#{m['id']:02d} · {_fmt_date(m['gregorian_date'])} · {topic or 'ללא נושא'}"
    with st.container(border=True, width=240, key=f"card-pc-{m['id']}"):
        _card_door(f"pc-{m['id']}", title, m["id"])
        over_chip = _chip(f"{overdue_count} באיחור", "red") if overdue_count else ""
        st.markdown(
            f"<div>{_countdown_chip(m)}"
            f"{_owners_chip([] if m.get('is_staff_built') else owners)}{over_chip}</div>",
            unsafe_allow_html=True)
        st.markdown(_phase_axis_html(progress, m, mini=True), unsafe_allow_html=True)
        slots = [l for l in lessons if not l.get("is_break")
                 and (l.get("lesson_role") or "") != "חבורות"]
        closed = sum(1 for l in slots if l.get("speaker_name"))
        bits = []
        if slots:
            bits.append(f"🎤 {closed}/{len(slots)} מרצים סגורים")
        elif topic:
            bits.append("🎤 אין עדיין מבנה ערב")
        if waiting:
            bits.append(f"📩 {waiting} ממתין לתשובה")
        if spent:
            bits.append(f"💰 {_fmt_nis(spent)} עד כה")
        if bits:
            st.markdown(f"<div class='card-meta'>{' · '.join(bits)}</div>",
                        unsafe_allow_html=True)


def _needs_attention(mishmarim: list[dict], upcoming: list[dict],
                     owners: dict[int, list[str]],
                     all_lessons: Optional[list[dict]] = None,
                     outreach: Optional[list[dict]] = None) -> None:
    """The four things that actually stall an evening, none of them visible on
    a task board: an evening with no topic and a date approaching, slots with
    no speaker days before the night, the SAME person being courted by two
    pairs at once, and an approach that was sent and never answered."""
    today = _date_cls.today()
    soon = {m["id"]: (_parse_date(m["gregorian_date"]) - today).days
            for m in upcoming if _parse_date(m["gregorian_date"])}

    no_topic = [m for m in upcoming
                if not m.get("topic") and 0 <= soon.get(m["id"], 999) <= 21]

    # one query for every slot in the season, grouped here (the dashboard
    # passes its own copy so the pipeline cards and this block share one read)
    if all_lessons is None:
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
    if outreach is None:
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
        when = _parse_date(str(o.get("created_at") or "")[:10])
        if when and (today - when).days >= 10:
            waiting.append((o, (today - when).days))

    total = len(no_topic) + len(open_slots) + len(collisions) + len(waiting)
    if not total:
        return
    st.markdown(f"#### מה דורש התערבות ({total})")
    st.caption("ארבעה דברים שמעכבים ערב ואף לוח משימות לא מראה.")
    with st.container(border=True, key="card-attention"):
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
    _dashboard_body()


@st.fragment
def _dashboard_body() -> None:
    """Everything under the title, as ONE fragment — the workfile's grammar:
    ✓ / ▶ on an overdue card rerun this body, not the login gate, the CSS and
    the sidebar. A door (`_goto`) still restarts the app, on purpose."""
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

    # A wrapping row, not st.columns: four tiles across on a desktop, two on
    # a phone — laid out by the browser, no rerun.
    # What a Mishmar that ALREADY HAPPENED cost, on average. The old tile
    # showed the ₪500 indication — a constant, which tells nobody anything.
    # Dividing by all 21 would read as a collapsing average all season, so
    # the denominator is the evenings behind us, and it says which those are.
    avg = budget["avg_per_past"]
    with st.container(horizontal=True, wrap=True, gap="medium", key="metric-row"):
        st.metric("משמרים", len(mishmarim), width=190)
        st.metric("עם נושא סגור", f"{len(with_topic)} / {len(mishmarim)}", width=190)
        st.metric("סה״כ הוצאות", _fmt_nis(budget["total_spent"]), width=190)
        # The fourth tile used to carry its caption INSIDE a 210px container:
        # one tile 210×163 beside three of 150×81, which read as a broken grid.
        # Four identical tiles; the sentence explaining the average goes under
        # the row, where it has the width to be a sentence.
        if avg is None:
            st.metric("ממוצע הוצאות למשמר", "—", width=190)
        else:
            st.metric("ממוצע הוצאות למשמר", _fmt_nis(avg),
                      delta=_fmt_nis(avg - budget["nominal_per_mishmar"]),
                      delta_color="off", width=190)
    st.caption("עוד לא התקיים משמר" if avg is None else
               f"הממוצע הוא על פני {budget['past_count']} משמרים שהתקיימו · "
               f"מול אינדיקציה של {_fmt_nis(budget['nominal_per_mishmar'])} למשמר")
    if total_all:
        st.progress(done_all / total_all,
                    text=f"התקדמות העונה: {done_all}/{total_all} משימות הושלמו")

    st.divider()
    st.markdown("#### עבר את התאריך המומלץ")
    # derived from the task list this body already holds: v_overdue_tasks was
    # one more round-trip after every ✓ / ▶ on this screen, for the same rows.
    # The predicate is the one the trainee home uses (annotate_deadline).
    owners = dm.get_owners_by_mishmar()
    overdue = sorted(
        ({**t, "owners": " + ".join(sorted(owners.get(t["mishmar_id"], []))) or "צוות"}
         for t in all_tasks if dm.annotate_deadline(t)["overdue"]),
        key=lambda t: (str(t.get("due_date")), t["mishmar_id"], t["id"]))
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
        # A wrapping flex row of fixed-width cards: 4 / 2 / 1 across as the
        # viewport shrinks, laid out by the browser — no rerun, no breakpoint.
        with st.container(horizontal=True, wrap=True, gap="small", key="overdue-grid"):
            for t in cards:
                with st.container(border=True, width=300, key=f"card-ov-{t['id']}"):
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
                    # A door first: the instructor could see a task was late
                    # and had no way to reach the Mishmar it belongs to.
                    row = st.container(horizontal=True, wrap=False, gap="small")
                    if t.get("category") != "הזמנה" and row.button(
                            "פתח ↗", key=f"ov-go-{t['id']}",
                            help="פותח את המשמר הזה, במקום שבו סוגרים את המשימה"):
                        _goto(NAV_WORKFILE, t["mishmar_id"],
                              _section_for_category(t.get("category")),
                              task_focus=t["id"])
                    row.button("✓ הושלם", key=f"ov-dn-{t['id']}", type="primary",
                               on_click=_set_status, args=(t["id"], "DONE"))
                    if t.get("category") != "הזמנה":
                        row.button("▶ בתהליך", key=f"ov-ip-{t['id']}",
                                   on_click=_set_status, args=(t["id"], "IN PROGRESS"))

    # ---- The pipeline: what the flat table never told anyone ----
    st.divider()
    st.markdown("#### צינור המשמרים")
    st.caption("כל משמר, איפה הוא עומד בבנייה, ומי מחזיק אותו. לפי סדר הערבים — "
               "לחיצה על הכותרת פותחת את ניהול המשמר.")
    today = _date_cls.today()
    upcoming = [m for m in mishmarim
                if (_parse_date(m.get("gregorian_date")) or today) >= today]
    past = [m for m in mishmarim if m not in upcoming]
    # The roster in the database and the roster in students_tasks.md drift
    # apart every time the season changes — a trainee leaves, the pairs are
    # re-drawn. This card is the loud half of the answer (see the always-there
    # «חניכים ושיבוץ» panel at the foot of this screen for the quiet half):
    # it applies the same mapping as migrations/2026-09-assign-trainees.sql,
    # under the instructor's confirmation and without an SQL editor.
    placeholders = dm.roster_placeholders()
    unowned = not any(owners.get(m["id"]) for m in mishmarim
                      if m["id"] not in dm.STAFF_BUILT_MISHMARIM)
    drift = dm.roster_drift()
    if placeholders or unowned or drift["mishmarim"] or drift["added"] or drift["removed"]:
        with st.container(border=True, key="card-roster"):
            st.markdown("**👥 השיבוץ במסד שונה מהקובץ.**")
            st.caption(_roster_drift_line(placeholders, unowned, drift)
                       + " הלחיצה מיישרת את השמות ואת זוגות #03–#21 לפי `students_tasks.md` — "
                         "אותו שינוי שעושה `migrations/2026-09-assign-trainees.sql`.")
            if st.button("👥 החל את השמות והשיבוץ מהקובץ", key="roster-open", type="primary"):
                _roster_dialog()
    # Two season-wide reads, shared with «מה דורש התערבות» below.
    all_lessons = dm.get_all_lessons()
    outreach = dm.get_all_outreach()
    lessons_by_mid: dict[int, list[dict]] = {}
    for l in all_lessons:
        lessons_by_mid.setdefault(l["mishmar_id"], []).append(l)
    waiting_by_mid = _waiting_by_mishmar(outreach)
    spent_by_mid = {r["id"]: r["spent"] for r in budget["per_mishmar"]}

    def _grid(items: list[dict], key: str) -> None:
        with st.container(horizontal=True, wrap=True, gap="small", key=key):
            for m in items:
                _mishmar_card(m, progress[m["id"]], over_by_mid.get(m["id"], 0),
                              owners.get(m["id"], []), lessons_by_mid.get(m["id"], []),
                              waiting_by_mid.get(m["id"], 0), spent_by_mid.get(m["id"], 0))

    _grid(upcoming, "pipeline-grid")
    if past:
        with st.expander(f"🌙 משמרים שהתקיימו ({len(past)})"):
            _grid(list(reversed(past)), "pipeline-past")

    _needs_attention(mishmarim, upcoming, owners, all_lessons, outreach)

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
            _empty("עוד לא התקיים משמר.", "הטבלה תתמלא אחרי הערב הראשון.")

    # What the trainees are searching for — every run, the empty ones too. A
    # search that found nothing shows its map and its queries: that is where a
    # bad reading of a topic becomes visible, and where the tool gets better.
    searches = dm.get_all_searches()
    spent = sum(((r.get("results_json") or {}).get("usage") or {}).get("cost_usd") or 0
                for r in searches)
    with st.expander(f"🔍 חיפושי המרצים של החניכים ({len(searches)})"
                     + (f" · עד כה ≈₪{spent * ca.ILS_PER_USD:.0f}" if spent else "")):
        if not searches:
            _empty("עוד לא נערך חיפוש.", "כל סריקה מהמסך «חיפוש מרצים» תופיע כאן.")
        else:
            st.caption("לחיצה על «פתח» פותחת את החיפוש כפי שהחניך ראה אותו — המפה, השמות, ומה נפסל.")
            for row in searches[:40]:
                r = row.get("results_json") or {}
                n = len(r.get("candidates") or [])
                outcome = (f"{n} מועמדים" if not r.get("fallback") else
                           "בלי תוצאות — " + SCOUT_FALLBACK_TEXT.get(r.get("reason") or "error", "")[:50])
                fields = " · ".join(a.get("field") or a.get("label") or ""
                                    for a in (r.get("map") or {}).get("angles") or [] if a.get("on", True))
                added = r.get("added") or []
                c1, c2, c3 = st.columns([6, 1, 0.5])
                c1.markdown(
                    f"**{_clean(row.get('student_name') or 'צוות')}**"
                    + (f" · #{row['mishmar_id']:02d}" if row.get("mishmar_id") else "")
                    + f" · {_clean(row['topic'])}"
                    + (f" → {_clean(row['lesson_topic'])}" if row.get("lesson_topic") else "")
                    + f" <span class='card-meta'>{str(row.get('created_at') or '')[:10]} · {outcome}"
                    + (f" · {_money(r['usage'])}" if (r.get("usage") or {}).get("cost_usd") else "")
                    + (f" · נוספו: {_clean(' · '.join(added))}" if added else "")
                    + (f"<br>🗺️ {_clean(fields)}" if fields else "")
                    + (f"<br>⚠️ {_clean(str(r['error']))[:160]}"
                       if r.get("fallback") and r.get("error") else "") + "</span>",
                    unsafe_allow_html=True)
                if c2.button("פתח", key=f"ds-open-{row['id']}"):
                    st.session_state["scout_result"] = _reopened(row)
                    _goto(NAV_SEARCH, row.get("mishmar_id"))
                c3.button("🗑", key=f"ib-ds-{row['id']}", help="מחיקת הרישום",
                          on_click=dm.delete_search, args=(row["id"],))

    # The evening's opening hour. It lives here and only here: the whole clock
    # of a Mishmar derives from it, so it is the instructor's call, not a field
    # a pair can nudge from inside their own workfile.
    with st.expander("🕗 שעת ההתחלה של הערב"):
        st.caption(
            "כל שעות המקטעים נגזרות מהשעה הזו ומהמשכים — שינוי כאן מזרים מחדש את כל הערב. "
            f"ברירת המחדל של העונה היא {dm.EVENING_START}."
        )
        moved = [m for m in mishmarim
                 if (m.get("start_time") or dm.EVENING_START) != dm.EVENING_START]
        st.caption(
            ("משמרים בשעה אחרת: "
             + " · ".join(f"#{m['id']:02d} ב-{m['start_time']}" for m in moved))
            if moved else f"כל המשמרים מתחילים ב-{dm.EVENING_START}."
        )
        labels = {m["id"]: f"#{m['id']:02d} · {_fmt_date(m['gregorian_date'])}"
                  for m in mishmarim}
        # quarter hours around the real range; the value is stored as text,
        # exactly like lessons.start_time
        slots = [f"{h:02d}:{q:02d}" for h in range(18, 22) for q in (0, 15, 30, 45)]
        first = (upcoming or mishmarim)[0]
        now_at = (first.get("start_time") or dm.EVENING_START)
        with st.form("start-time"):
            s1, s2 = st.columns([1.4, 1])
            s1.selectbox("איזה משמר?", list(labels), key="start-mid",
                         format_func=lambda i: labels[i],
                         index=list(labels).index(first["id"]))
            # only the FIRST render honours index — after that the instructor's
            # own choice is in session_state, which is what a form should do
            s2.selectbox("שעת ההתחלה", slots, key="start-hhmm",
                         index=slots.index(now_at) if now_at in slots else
                         slots.index(dm.EVENING_START))
            st.checkbox("להחיל על כל המשמרים שטרם התקיימו", key="start-all")
            st.form_submit_button(
                "💾 שמור שעה", type="primary", on_click=_save_start_time_clicked,
                args=([m["id"] for m in upcoming],))

    # The quiet half of the roster answer. The loud card above only shows when
    # the two disagree — which meant that once it had been used it vanished,
    # and the NEXT change to the pairs had no way into the database at all.
    # A control that can only be used once is a control that cannot be used.
    with st.expander("👥 חניכים ושיבוץ"):
        st.caption(
            "המקור הוא `students_tasks.md` — נוצר על ידי `scripts/assign_trainees.py`. "
            "כאן רואים מה יש במסד מול מה שכתוב בקובץ, ומיישרים ביניהם. "
            "המשימות, המרצים ומבנה הערבים לא נוגעים."
        )
        st.markdown(f"**מה שונה כרגע:** {_roster_drift_line(placeholders, unowned, drift)}")
        rows = []
        for m in mishmarim:
            if m["id"] in dm.STAFF_BUILT_MISHMARIM:
                continue
            rows.append({
                "בקובץ": " + ".join(drift["file_pairs"].get(m["id"], [])) or "—",
                "במסד": " + ".join(owners.get(m["id"], [])) or "—",
                "תאריך": _fmt_date(m["gregorian_date"]),
                "משמר": f"#{m['id']:02d}",
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        # a plain `if`, like the other dialog openers: opening a dialog is a
        # rerun anyway, so on_click buys nothing
        if st.button("👥 החל את השמות והשיבוץ מהקובץ", key="roster-open-panel",
                     disabled=not (placeholders or unowned or drift["mishmarim"]
                                   or drift["added"] or drift["removed"])):
            _roster_dialog()

    if auth_configured():
        with st.expander("🔗 שיוך חשבונות"):
            st.caption(
                "כל חניך נכנס עם חשבון הגוגל שלו. שייכו כאן כתובת לכל שם — "
                "בלי שיוך, החניך יתחבר אבל לא ייכנס לשום משמר."
            )
            with st.form("emails"):
                students = [x for x in dm.get_students() if x["role"] == "student"]
                for stu in students:
                    st.text_input(stu["name"], value=stu.get("email") or "",
                                  key=f"em-{stu['id']}", placeholder="name@gmail.com")
                # the seventh form: it wrote and then reran the fragment, which
                # is one needless second run of the whole dashboard body
                st.form_submit_button("שמור שיוכים", on_click=_save_emails_clicked,
                                      args=([x["id"] for x in students],))


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


def _goto_local(section: Optional[str] = None, lesson_focus=None,
                task_focus: Optional[int] = None) -> None:
    """A door from the workfile's task board into the SAME evening: no page
    restart. The panels and the focus live in session state that the fragment
    reads, so setting them and rerunning the fragment is the whole trip —
    `_goto` restarted the app for a click that never left the screen."""
    if section is not None:
        st.session_state["wf_panel"] = section
        st.session_state["wf_panel_nonce"] = st.session_state.get("wf_panel_nonce", 0) + 1
    st.session_state["wf_focus_lesson"] = lesson_focus
    st.session_state["wf_focus_task"] = task_focus
    st.session_state["_scroll_req"] = True
    st.session_state.pop("_scroll_target_lesson", None)
    st.rerun(scope="fragment")


def _set_status(task_id: int, status: str, toast: Optional[str] = None) -> None:
    """on_click handler: the write happens BEFORE the run that follows the
    click, so that single run already shows it — no st.rerun(), no second run.
    This is the difference between one round-trip and two full page builds."""
    dm.update_task_status(task_id, status)
    if toast:
        st.toast(toast)


def _add_task_clicked(mid: int) -> None:
    """on_click of «➕ הוסף משימה»: the write happens before the ONE fragment
    run that follows the submit, which already shows the new card — the form
    used to write, then `st.rerun()` the whole app."""
    desc = (st.session_state.get(f"newtask-{mid}") or "").strip()
    if not desc:
        return
    cat = st.session_state.get(f"newtask-cat-{mid}")
    dm.add_task(mid, desc, category=None if cat in (None, "(אוטומטי)") else cat)
    st.toast("נוספה משימה — שובצה לשלב לפי הקטגוריה")


def _save_task_edit(t: dict, nonce: int, has_slots: bool) -> None:
    """on_click of the task editor's «💾 שמור». Bumping the nonce gives the
    popover a new key on the run that follows, i.e. a fresh, CLOSED editor —
    a dialog here needed `st.rerun()`, a whole-app run, just to close."""
    tid = t["id"]
    due = (st.session_state.get(f"edit-due-{tid}-{nonce}") or "").strip()
    d = _parse_date(due)
    dm.edit_task(tid,
                 description=st.session_state.get(f"edit-desc-{tid}-{nonce}"),
                 details=st.session_state.get(f"edit-details-{tid}-{nonce}"),
                 due_date=(d.isoformat() if d else None) if due else None)
    if has_slots:
        new_slot = st.session_state.get(f"edit-slot-{tid}-{nonce}")
        if new_slot != t.get("lesson_id"):
            dm.link_task_to_lesson(tid, new_slot)
    # the popover reopens under nonce+1, so THIS nonce's widget keys are dead
    # weight in session_state — one set per save, for the browser session
    for k in (f"edit-desc-{tid}-{nonce}", f"edit-details-{tid}-{nonce}",
              f"edit-due-{tid}-{nonce}", f"edit-slot-{tid}-{nonce}"):
        st.session_state.pop(k, None)
    st.session_state[f"edit-nonce-{tid}"] = nonce + 1
    st.toast("נשמר")


def _save_emails_clicked(student_ids: list[int]) -> None:
    """on_click of «שמור שיוכים»: the writes land before the fragment run that
    follows the submit, which already shows them."""
    n = 0
    for sid in student_ids:
        dm.set_student_email(sid, st.session_state.get(f"em-{sid}", "")); n += 1
    st.toast(f"נשמרו {n} שיוכים")


def _save_start_time_clicked(all_upcoming: list[int]) -> None:
    """on_click of «💾 שמור שעה»: writes the start time (and reflows every
    slot behind it) before the fragment run that follows the submit."""
    mid = st.session_state.get("start-mid")
    stamp = st.session_state.get("start-hhmm")
    if not mid or not stamp:
        return
    targets = all_upcoming if st.session_state.get("start-all") else [mid]
    ok = [t for t in targets if dm.set_mishmar_start_time(t, stamp)]
    if not ok:
        st.toast("השעה לא נשמרה — פורמט לא תקין")
        return
    st.toast(f"{len(ok)} משמרים מתחילים ב-{stamp} · שעות המקטעים חושבו מחדש"
             if len(ok) > 1 else f"משמר #{ok[0]:02d} מתחיל ב-{stamp}")


def _close_topic_clicked(mid: int) -> None:
    """on_click of «🎯 סגור את הנושא»: topic, its tasks and the default
    timeline in one callback, one fragment run after."""
    new_topic = (st.session_state.get(f"topic-new-{mid}") or "").strip()
    if not new_topic:
        return
    dm.set_mishmar_topic(mid, new_topic)
    for t in dm.get_tasks_for_mishmar(mid):
        if t.get("category") == "נושא" and t["status"] != "DONE":
            dm.update_task_status(t["id"], "DONE")
    # The structure appears the moment the topic closes.
    created = dm.create_default_timeline(mid)
    st.toast(f"הנושא נסגר! נבנה שלד ערב של {created} משבצות מ-{dm.mishmar_start(mid)}")


def _update_topic_clicked(mid: int) -> None:
    new_topic = (st.session_state.get(f"topic-edit-{mid}") or "").strip()
    if new_topic:
        dm.set_mishmar_topic(mid, new_topic)
        st.toast("הנושא עודכן")


def _add_logistics_clicked(mid: int, kind: str, with_detail: bool) -> None:
    label = (st.session_state.get(f"lgl-{mid}-{kind}") or "").strip()
    if label:
        detail = st.session_state.get(f"lgd-{mid}-{kind}", "") if with_detail else ""
        dm.add_logistics_item(mid, kind, label, detail)


def _save_feedback_clicked(mid: int, entries: list[tuple], my_titles: set,
                           feedback_task_ids: list[int]) -> None:
    """on_click of «💾 שמור משוב על הערב». `entries` is (lesson_id, name,
    speaker_name) per slot; the stars and the words are read by key."""
    n = 0
    for lid, name, speaker_name in entries:
        stars = st.session_state.get(f"fb-r-{lid}")
        if name in my_titles or stars is None:
            continue   # one submission per slot per trainee; unrated = skipped
        dm.add_feedback(
            mid, rating=stars + 1, lesson_id=lid, lesson_title=name,   # 0-based → 1–5
            speaker_name=speaker_name,
            student_id=st.session_state.student_id,
            what_worked=(st.session_state.get(f"fb-w-{lid}") or None))
        n += 1
    if n == 0:
        st.toast("לא סומנו כוכבים — לא נשמר משוב")
        return
    # feedback submitted => the trainee's feedback task closes
    for tid in feedback_task_ids:
        dm.update_task_status(tid, "DONE")
    st.toast(f"נשמרו {n} משובים · משימת המשוב נסגרה")


def _save_budget_clicked(mid: int, speakers: list[str]) -> None:
    n = 0
    for i, name in enumerate(speakers):
        dm.add_budget_entry(mid, "מרצה", actual_cost=st.session_state.get(f"pay-{mid}-{i}", 0.0),
                            description=name); n += 1
    extra_name = (st.session_state.get(f"bud-extra-name-{mid}") or "").strip()
    if extra_name:
        dm.add_budget_entry(mid, "מרצה", actual_cost=st.session_state.get(f"bud-extra-amt-{mid}", 0.0),
                            description=extra_name); n += 1
    refreshments = st.session_state.get(f"bud-refr-{mid}", 0.0)
    if refreshments:
        dm.add_budget_entry(mid, "כיבוד", actual_cost=refreshments, description="כיבוד"); n += 1
    other = st.session_state.get(f"bud-other-{mid}", 0.0)
    if other:
        dm.add_budget_entry(mid, "אחר", actual_cost=other, description="אחר"); n += 1
    st.toast(f"נשמרו {n} שורות תקציב")


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
    # Streamlit keeps the scroll position across a rerun, so a deep link from
    # the middle of the dashboard landed in the middle of the workfile. The
    # landing run scrolls once — to the focused slot if there is one, else up.
    st.session_state["_scroll_req"] = True
    st.session_state.pop("_scroll_target_lesson", None)


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


def _empty(text: str, hint: str = "") -> None:
    """The app's one voice for «nothing here yet»: a quiet line, never a blue
    info box shouting about an absence."""
    st.markdown(f"<div class='empty'>{_clean(text)}"
                + (f"<div class='card-meta'>{_clean(hint)}</div>" if hint else "")
                + "</div>", unsafe_allow_html=True)


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
    with st.container(border=True, key=f"card-t-{t['id']}"):
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
            f"<div>{ph['label']}</div><div style='color:#5c6577'>{count}</div></div>"
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


def _partner_chip(owners: list[str], me: str) -> str:
    """Who the trainee is building this evening WITH. The pair is the unit of
    work here, so the one name that is news is the other one — «👥 עם X»,
    not the pair, which would spend half the chip telling them their own name.
    A staff-built evening, or one the database has no pair for, says «צוות»."""
    partners = [n for n in owners if n != me]
    if not partners:
        return _owners_chip([])
    return _chip("👥 עם " + " · ".join(partners), "blue")


def _next_mishmar_hero(m: dict, progress: dict,
                       owners: Optional[list[str]] = None, me: str = "") -> None:
    """The trainee's ONE place to answer "what now?" — Mishmar identity, who
    they are building it with, the phase stepper, and only the current phase's
    open tasks."""
    cur = progress["phases"][progress["current"]]
    with st.container(border=True, key=f"card-hero-{m['id']}"):
        chips = [_countdown_chip(m)]
        if not m.get("is_staff_built"):
            chips.append(_partner_chip(owners or [], me))
        if m.get("mishmar_type"):
            chips.append(_chip(m["mishmar_type"], "gold"))
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap'>"
            f"<span style='font-size:1.25rem;font-weight:800'>🕯️ משמר #{m['id']:02d}</span>"
            f"<span style='color:#5c6577'>{m['gregorian_date']} · {m['hebrew_date']}</span>"
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
            _card_grid(sorted(open_cur, key=lambda t: str(t.get("due_date") or "9999")),
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


def _card_door(key: str, title: str, mid: int) -> None:
    """The WHOLE card is the door. The title used to be the only clickable
    thing — a tertiary button on the first line — and on a phone a thumb on
    the chips or the axis did nothing. Now the button is laid over the entire
    card by CSS (`st-key-card-pc-` / `-mc-` are `position: relative`, the
    button's container `inset: 0`, opacity 0) and keeps its label for screen
    readers and the focus ring; the visible title is this markdown line.
    The button must be the card's FIRST child, so the overlay has the card's
    full height to cover. Click cost unchanged: `_goto` is a screen change."""
    if st.button(title, key=key, type="tertiary", width="stretch"):
        _goto(NAV_WORKFILE, mid)
    st.markdown(f"<div class='task-desc'>{_clean(title)}</div>", unsafe_allow_html=True)


def _mini_mishmar_card(m: dict, progress: dict,
                       owners: Optional[list[str]] = None) -> None:
    """Same grammar as the instructor's pipeline row — partner names and the
    dated phase axis — so a trainee reads their own queue the same way."""
    with st.container(border=True, width=240, key=f"card-mc-{m['id']}"):
        _card_door(f"mc-{m['id']}", f"#{m['id']:02d} · {_fmt_date(m['gregorian_date'])}", m["id"])
        st.markdown(f"<div>{_countdown_chip(m)}{_owners_chip(owners or [])}</div>",
                    unsafe_allow_html=True)
        st.markdown(_phase_axis_html(progress, m, mini=True), unsafe_allow_html=True)


def show_student_view(student_name: str) -> None:
    st.title(f"שלום, {student_name}")
    _student_body(st.session_state.student_id, student_name)


@st.fragment
def _student_body(student_id: int, student_name: str = "") -> None:
    """The trainee's home under the greeting, as ONE fragment: ✓ / ▶ / ↩ on a
    task card used to restart the whole app for a status flip on the same
    screen. The hero, its stepper and the cards all read the same task list,
    so one fragment run keeps them in step."""
    mine = dm.get_mishmarim_for_student(student_id)
    if not mine:
        _empty("עוד לא משובצים לך משמרים.")
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
        _card_grid(sorted(overdue, key=lambda t: str(t.get("due_date") or "9999")),
                   "ovd", link=True)

    # One read for the hero AND the strip below it — the hero used to be drawn
    # before this line existed, which is why it never named the partner.
    owners = dm.get_owners_by_mishmar()

    st.markdown("#### המשמר הבא שלי")
    _next_mishmar_hero(hero, progress[hero["id"]],
                       owners.get(hero["id"], []), student_name)

    # by the PARSED date, not by id — the hero already learned that lesson
    others = sorted((m for m in mine if m["id"] != hero["id"]),
                    key=lambda m: _parse_date(m.get("gregorian_date")) or today)
    if others:
        st.markdown("#### שאר המשמרים שלי")
        st.caption("הם מחכים בתור — כל אחד ייפתח כשיגיע זמנו. קובץ העבודה פתוח לכולם תמיד.")
        # A wrapping flex row, not st.columns. Dealt round-robin into three
        # columns, a phone STACKED column 0 (#07, #21) before column 1 (#09) —
        # February before November. In a flex row the DOM order is the order
        # at every width; the browser wraps 3 / 2 / 1 across.
        with st.container(horizontal=True, wrap=True, gap="small", key="my-grid"):
            for m in others:
                _mini_mishmar_card(m, progress[m["id"]], owners.get(m["id"], []))

    done = [t for t in all_tasks if t["status"] == "DONE"]
    if done:
        with st.expander(f"✅ הושלמו ({len(done)})"):
            _card_grid(done, "done")


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


def _money(usage: dict) -> str:
    """≈₪ (and $) for a search — its usage carries cost_usd since round 2;
    an older record is priced from its tokens."""
    usd = (usage or {}).get("cost_usd")
    if usd is None:
        usd = ca._cost(usage or {})
    return f"≈₪{usd * ca.ILS_PER_USD:.2f} (${usd:.2f})"


def _link_label(url: str, title: str = "") -> str:
    """«title — domain»: the reader sees WHAT they are opening. Every link used
    to say «מאמר / ראיון בנושא», a Wikipedia page and a staff page alike."""
    from urllib.parse import urlparse
    host = (urlparse(url).netloc or "").removeprefix("www.")
    t = _clean(title or "")[:70]
    return f"{t} — {host}" if t else host or url


def _default_slot(slots: list[dict], lesson_topic: str) -> int:
    """The slot the search was FOR: its title shares a word with the lesson
    topic; else the first slot with no closed speaker; else the first."""
    words = {w for w in (lesson_topic or "").split() if len(w) > 2}
    for i, l in enumerate(slots):
        if words & set((l.get("title") or "").split()):
            return i
    return next((i for i, l in enumerate(slots) if not l.get("speaker_name")), 0)


def _scout_card(c: dict, mid: Optional[int], lesson: str, idx: int,
                search_id: Optional[int] = None, lesson_topic: str = "") -> None:
    """One researched candidate: who they are, where they are, why they fit,
    and the evidence. Everything here is grounded in what the search returned —
    a field the scout could not support comes back empty, and contact details
    are never carried at all."""
    name = c["name"]
    display = f"{c['title']} {name}" if c.get("title") else name
    with st.container(border=True, key=f"card-scout-{idx}"):
        label, kind = CONFIDENCE_CHIP.get(c.get("confidence") or "low",
                                          CONFIDENCE_CHIP["low"])
        chips = [_chip(label, kind)]
        flag = c.get("region_flag") or "⚪"
        # the place that DECIDED the flag — the chip used to print region_hint
        # («מיקום לא ידוע») beside a 🟡 found in the affiliation
        place = c.get("region_place") or c.get("region_hint") or ""
        chips.append(_chip(f"{flag} {place or 'מיקום לא ידוע'}",
                           "green" if flag == "🟢" else
                           "yellow" if flag == "🟡" else
                           "red" if flag == "🔴" else "gray"))
        for f in c.get("flags", []):
            if f != "⚠️ לאמת":              # said once, above the list
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
        if c.get("fit") or c.get("rationale"):
            st.caption("למה דווקא: " + _clean(c.get("fit") or c["rationale"]))
        if c.get("recent_years"):
            st.caption("פעיל/ה לפי התוצאות בשנים: " + ", ".join(c["recent_years"][:4]))
        # One line of institutional memory — the person is already in the
        # index, and this is what we know about when they were invited.
        if c.get("memory"):
            st.warning(_clean(c["memory"]))
        titles = {e.get("href"): e.get("title") for e in c.get("evidence") or []}
        if c.get("link"):
            st.markdown(f"📄 [{_link_label(c['link'], titles.get(c['link']))}]({c['link']})")
        for ev in (c.get("evidence") or [])[:3]:
            if ev.get("href") and ev["href"] != c.get("link"):
                st.caption(f"[{_link_label(ev['href'], ev.get('title'))}]({ev['href']})")
        st.caption("☎️ פרטי קשר לא נשלפים מהרשת — מצאו אותם דרך העמוד המוסדי.")

        ac1, ac2, ac3 = st.columns([1.6, 1.2, 0.7])
        if mid:
            lessons = dm.get_lessons(mid)
            slots = [l for l in lessons if not l.get("is_break")]
            # the evening's own slot names — a skeleton slot has no title, and
            # the picker read «20:00 / 21:30 / …» with nothing to choose by
            names = _slot_names(lessons)
            labels = {l["id"]: " · ".join(x for x in (l.get("start_time") or "",
                                                     names.get(l["id"], "")) if x)
                      or f"מקטע {l['slot_order']}" for l in slots}
            if labels:
                lid = ac1.selectbox("מקטע", list(labels), format_func=lambda i: labels[i],
                                    index=_default_slot(slots, lesson_topic),
                                    key=f"slot-{idx}-{name}", label_visibility="collapsed")
                # A candidate, NOT the speaker: you gather three and close one
                # later, in the workfile. Assigning straight from a search made
                # the first plausible name the decision.
                ac2.button("➕ הוסף כמועמד", key=f"cand-{idx}-{name}", type="primary",
                           help="מוסיף לרשימת המועמדים של המקטע — ולמאגר המשותף",
                           on_click=_add_candidate,
                           args=(c, display, name, lesson, lid, labels[lid], search_id))
            else:
                ac1.caption("אין עדיין מקטעים במשמר — צרו את שלד הערב קודם")
        else:
            ac1.caption("בחרו משמר למעלה כדי להוסיף כמועמד")
        # the institutional page, where contact details really live — the old
        # «אמת» re-ran a slow DuckDuckGo check of what the model had just read
        page = c.get("inst_link") or c.get("link")
        if page:
            ac3.link_button("🏛️ עמוד המוסד" if c.get("inst_link") else "🔗 הדף", page)


def _add_candidate(c: dict, display: str, name: str, lesson: str,
                   lid: int, slot_label: str, search_id: Optional[int] = None) -> None:
    """on_click: the found name becomes a CANDIDATE on the slot and a row in
    the shared index — and the search it came from remembers that it was
    taken up. Three writes, one run — never write(); st.rerun()."""
    href = c.get("link") or next(
        (e.get("href") for e in c.get("evidence") or [] if e.get("href")), None)
    # Only a person the index does not know becomes a new row. add_new_speaker
    # upserts on (name, source_type), so a known speaker under another source
    # got a second «web_search» row — and from then on resolve_speaker was
    # ambiguous for them and every ✅ / outreach on them went unlogged.
    try:
        known = dm.resolve_speaker(name=name) is not None
    except dm.AmbiguousSpeaker:
        known = True
    if not known:
        dm.add_new_speaker(
            name=display, expertise_topics=c.get("bio") or None,
            verification_url=href, source_type="web_search",
            lesson_fit=lesson or None,
            notes=" · ".join(x for x in [
                c.get("affiliation"), c.get("region_hint"),
                "נמצא בסריקת מרצים · ⚠️ לאמת לפני פנייה"] if x))
    dm.add_lesson_speaker(lid, name, student_id=st.session_state.student_id)
    dm.mark_search_added(search_id, name)
    st.toast(f"«{name}» נוסף כמועמד ל{slot_label}"
             + (" — כבר במאגר" if known else " — ולמאגר"))


# The angle picker is a segmented control, so the labels stay short; the
# explanation of each lives in ANGLE_HINTS (rendered as the control's help).
LESSON_ANGLES = {
    "בלי המלצה": "",
    "יסודות": "1",
    "ערעור / טוויסט": "2",
    "זווית מפתיעה": "3",
}
ANGLE_HINTS = {
    "בלי המלצה": "לחפש בכל הזוויות",
    "יסודות": "היסטוריון, חוקר, איש אקדמיה",
    "ערעור / טוויסט": "פילוסוף, הוגה, מחשבת ישראל",
    "זווית מפתיעה": "אמנות, קולנוע, פסיכולוגיה, סוציולוגיה",
}


def _reopened(row: dict) -> dict:
    """A saved search as the result screen draws it — no model call."""
    return {**(row.get("results_json") or {}), "search_id": row["id"], "topic": row["topic"],
            "lesson_topic": row.get("lesson_topic") or "", "mid": row.get("mishmar_id")}


def _norm_topic(t: Optional[str]) -> str:
    return " ".join((t or "").split()).strip(" ?.!").lower()


def _prior_search(held: dict) -> Optional[dict]:
    """The same Mishmar, topic and lesson topic, already scanned with results —
    a partner's scan included. Read from the SAME cached call the history
    above makes, so asking costs no query."""
    rows = dm.get_searches_for([m["id"] for m in _my_mishmarim()])
    want = (held.get("mid"), _norm_topic(held.get("topic")), _norm_topic(held.get("lesson_topic")))
    showing = (st.session_state.get("scout_result") or {}).get("search_id")
    for row in rows:
        if row["id"] == showing:            # the result already on screen
            continue
        r = row.get("results_json") or {}
        if r.get("fallback") or not r.get("candidates"):
            continue
        if (row.get("mishmar_id"), _norm_topic(row.get("topic")),
                _norm_topic(row.get("lesson_topic"))) == want:
            return row
    return None


def _search_history(mine: list[dict]) -> None:
    """The pair's own searches, on arrival and unfolded — a closed tab used to
    be the end of a search. Every run is kept, the empty ones too; «פתח»
    restores a saved result at no call."""
    rows = dm.get_searches_for([m["id"] for m in mine])
    if not rows:
        return
    dates = {m["id"]: m.get("gregorian_date") for m in mine}
    st.markdown(f"##### 🕘 החיפושים של המשמרים שלך ({len(rows)})")
    head, rest = rows[:5], rows[5:]

    def _line(row: dict) -> None:
        r = row.get("results_json") or {}
        mid = row.get("mishmar_id")
        n = len(r.get("candidates") or [])
        outcome = (f"{n} מועמדים" if not r.get("fallback") else
                   "בלי תוצאות — " + SCOUT_FALLBACK_TEXT.get(r.get("reason") or "error", "")[:60])
        added = r.get("added") or []
        fields = " · ".join(a.get("field") or a.get("label") or ""
                            for a in (r.get("map") or {}).get("angles") or [] if a.get("on", True))
        c1, c2 = st.columns([5, 1])
        c1.markdown(
            (f"**#{mid:02d}** · " if mid else "") + f"**{_clean(row['topic'])}**"
            + (f" → {_clean(row['lesson_topic'])}" if row.get("lesson_topic") else "")
            + f" <span class='card-meta'>{str(row.get('created_at') or '')[:10]} · {outcome}"
            + (f" · נוספו: {_clean(' · '.join(added))}" if added else "")
            + (f"<br>🗺️ {_clean(fields)}" if fields else "") + "</span>",
            unsafe_allow_html=True)
        c2.button("פתח", key=f"reopen-{row['id']}", on_click=_set_state,
                  args=("scout_result", _reopened(row)))

    for row in head:
        _line(row)
    if rest:
        with st.expander(f"עוד {len(rest)} חיפושים"):
            for row in rest:
                _line(row)


def show_speaker_search() -> None:
    st.title("חיפוש מרצים")
    st.caption(
        "המודל קורא את הנושא כ**תחומים** — אתם מאשרים או מתקנים את המפה — ואז הוא סורק "
        "את הרשת לפי התחומים ומחזיר שמות עם הזווית שכל אחד עונה עליה. "
        "כל שם הוא ⚠️ לאמת עד שבדקתם, ופרטי קשר לעולם לא נשלפים אוטומטית."
    )
    mine = _my_mishmarim()
    _search_history(mine)

    default_topic, default_mid = "", None
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
        angle = g1.segmented_control(
            "המלצה: איזו זווית? (רשות)", options=list(LESSON_ANGLES),
            default="בלי המלצה", key="scout-angle",
            help="  \n".join(f"**{k}** — {v}" for k, v in ANGLE_HINTS.items()))
        lesson = LESSON_ANGLES[angle or "בלי המלצה"]
        labels = {m["id"]: f"#{m['id']:02d} · {m['gregorian_date']}" for m in mine}
        mid = g2.selectbox(
            "לאיזה משמר משבצים?", [None, *labels],
            format_func=lambda i: "— בלי שיבוץ —" if i is None else labels[i],
            index=(list(labels).index(default_mid) + 1) if default_mid in labels else 0,
        ) if mine else None
        go_map = st.form_submit_button("🗺️ בנה מפה", type="primary")
    st.caption("המפה היא קריאה אחת קטנה של המודל — כמה שניות. הסריקה עצמה, אחרי שאישרתם "
               "את המפה, היא דקה או שתיים ועד שמונה חיפושים ברשת; התוצאה נשמרת.")

    topic, lesson_topic = topic.strip(), lesson_topic.strip()
    if go_map and (topic or lesson_topic):
        with st.spinner("קורא את הנושא כתחומים…"):
            m = ca.scout_map(topic or lesson_topic, lesson_topic, lesson)
        st.session_state["scout_map"] = {
            "nonce": st.session_state.get("scout_map_nonce", 0) + 1,
            "map": m, "topic": topic or lesson_topic, "lesson_topic": lesson_topic,
            "angle": lesson, "mid": mid,
        }
        st.session_state["scout_map_nonce"] = st.session_state["scout_map"]["nonce"]
        st.session_state.pop("scout_result", None)

    held = st.session_state.get("scout_map")
    if held:
        _map_step(held)

    result = st.session_state.get("scout_result")
    if not result:
        if not held:
            st.info("הזינו נושא — של המשמר, של השיעור, או שניהם — ולחצו «בנה מפה».")
        return
    _results_panel(result)


@st.fragment
def _results_panel(result: dict) -> None:
    """The candidate cards as ONE fragment. «➕ הוסף כמועמד» is a
    callback, but on this page-level screen the run after it was a whole-app
    run — sidebar, login gate, map, every card — for a three-row write
    (measured: 1 app run, 229 ms, and the page dimmed). Scoped here it is one
    fragment run of 12 ms. «בנה מפה» / «סרוק את הרשת» stay page-level: they
    change what this panel receives. The history list above does not redraw
    after an add — the toast confirms it, and the next full run catches up."""
    st.divider()
    if result.get("fallback"):
        _scout_fallback(result)
    else:
        _scout_results(result)


def _map_step(held: dict) -> None:
    """The intermediate step: the topic read as fields, one card per angle,
    editable — terms as a text line, a checkbox per angle — and only then the
    expensive button. The trainee sees how the topic was read and can fix it
    before anything is paid for; that reading is also the pedagogy here."""
    m, nonce = held["map"], held["nonce"]
    if m.get("error") or not m.get("angles"):
        st.warning(
            "המפה לא נבנתה — "
            + SCOUT_FALLBACK_TEXT.get(m.get("reason") or "error", SCOUT_FALLBACK_TEXT["error"])
            + (f" ({_clean(m['error'])[:80]})" if m.get("error") else "")
        )
        st.caption("בינתיים, חיפוש ידני לפי הזוויות:")
        for label, hint in ANGLE_HINTS.items():
            if label == "בלי המלצה":
                continue
            links = ss.manual_search_links(f"{held['topic']} {hint}")
            st.markdown(f"- **{label}** — [Google]({links['google']}) · [DuckDuckGo]({links['duckduckgo']})")
        st.button("🔁 נסו שוב", key=f"map-retry-{nonce}", on_click=_clear_map)
        return

    st.markdown("#### 🗺️ המפה — איך המודל קרא את הנושא")
    if m.get("reading"):
        st.caption(_clean(m["reading"]))
    for a in m["angles"]:
        k = a["key"]
        with st.container(border=True, key=f"card-map-{k}-{nonce}"):
            st.markdown(f"**{a['label']} — {_clean(a.get('field') or '')}**"
                        + (f" <span class='card-meta'>{_clean(a.get('who') or '')}</span>"
                           if a.get("who") else ""), unsafe_allow_html=True)
            if a.get("why"):
                st.caption(_clean(a["why"]))
            st.text_input("מונחי חיפוש (מופרדים בפסיק)", value=", ".join(a.get("terms") or []),
                          key=f"map-terms-{k}-{nonce}")
            if a.get("where"):
                st.caption("איפה יושבים אנשים כאלה: " + _clean(" · ".join(a["where"])))
            st.checkbox("לחפש בזווית הזו", value=True, key=f"map-on-{k}-{nonce}")

    prior = _prior_search(held)
    if prior:
        # don't pay twice for what the pair (or the partner) already has
        r = prior.get("results_json") or {}
        pc1, pc2 = st.columns([5, 1])
        pc1.info(f"הנושא הזה כבר נסרק ב-{str(prior.get('created_at') or '')[:10]} — "
                 f"{len(r.get('candidates') or [])} שמות. אפשר לפתוח אותם בלי לשלם שוב, "
                 "או לסרוק מחדש.")
        pc2.button("פתח", key=f"prior-{prior['id']}", on_click=_set_state,
                   args=("scout_result", _reopened(prior)))
    b1, b2 = st.columns([1.4, 1])
    if b1.button("🔎 סרוק את הרשת", type="primary", width="stretch", key=f"scan-{nonce}"):
        _run_scan(held)
    # a callback, not `pop(); st.rerun()` — the click already reruns the page
    b2.button("🔁 מפה מחדש", type="tertiary", key=f"map-again-{nonce}", on_click=_clear_map)


def _clear_map() -> None:
    """on_click: forget the map, any result under it — and the nonce-keyed
    widget entries the map's cards created, or every «מפה מחדש» leaves six
    dead session_state keys behind for the life of the browser session (the
    task editor's nonce cleanup, for the same reason)."""
    held = st.session_state.pop("scout_map", None) or {}
    nonce = held.get("nonce")
    for a in (held.get("map") or {}).get("angles") or []:
        st.session_state.pop(f"map-terms-{a['key']}-{nonce}", None)
        st.session_state.pop(f"map-on-{a['key']}-{nonce}", None)
    st.session_state.pop("scout_result", None)


def _edited_map(held: dict) -> dict:
    """The map as the trainee left it: edited terms, unticked angles off."""
    m, nonce = held["map"], held["nonce"]
    angles = []
    for a in m["angles"]:
        k = a["key"]
        raw = st.session_state.get(f"map-terms-{k}-{nonce}", "")
        terms = [x.strip() for x in str(raw).split(",") if x.strip()] or a.get("terms") or []
        angles.append({**a, "terms": terms[:4],
                       "on": bool(st.session_state.get(f"map-on-{k}-{nonce}", True))})
    return {**m, "angles": angles}


def _run_scan(held: dict) -> None:
    """The expensive call, fired ONLY from the button (rerun trap). Every run
    is saved — the empty ones too — so the pair, the partner and the
    instructor can come back to it."""
    smap = _edited_map(held)
    topic, lesson_topic, lesson, mid = (held["topic"], held["lesson_topic"],
                                        held["angle"], held.get("mid"))
    with st.status("סורק את הרשת…", expanded=True) as box:
        log, stages = st.empty(), []

        def _stage(line: str) -> None:
            stages.append(line)
            box.update(label=line)
            log.markdown("\n".join(f"- {_clean(x)}" for x in stages[-12:]))

        res = ca.scout_speakers(topic, lesson, lesson_topic, progress=_stage,
                                scout_map_result=smap)
        n_found = len(res.get("candidates") or [])
        u = res.get("usage") or {}
        box.update(
            label=(f"הסריקה הסתיימה · {n_found} מועמדים · {res.get('strong', 0)} בוודאות גבוהה"
                   f" · {u.get('searches') or 0} חיפושים"
                   if not res.get("fallback") else "הסריקה הסתיימה — בלי מועמדים"),
            state="complete", expanded=False)
    slim = ca.slim_for_storage(res)
    sid = dm.save_search(topic, slim, mishmar_id=mid, lesson_topic=lesson_topic,
                         angle=lesson, student_id=st.session_state.student_id)
    st.session_state["scout_result"] = {**res, "search_id": sid, "topic": topic,
                                        "lesson_topic": lesson_topic, "mid": mid}


def _scout_results(result: dict) -> None:
    """Grounded names, grouped under the angle each one answers, the group
    headed by the map's field and why it speaks to the topic."""
    cands = result["candidates"]
    smap = result.get("map") or {}
    by_key = {a["key"]: a for a in smap.get("angles") or []}
    mid, lesson = result.get("mid"), (st.session_state.get("scout_map") or {}).get("angle", "")
    st.markdown(f"#### המועמדים שנמצאו ({len(cands)})")
    # one line for the whole list — «⚠️ לאמת» on every card was noise
    st.caption("⚠️ כל השמות נמצאו ברשת על ידי המודל — לאמת בעמוד המוסד לפני פנייה. "
               "ודאות: 🟢 עמוד מוסדי וגם פעילות מ-2024 ואילך · 🟡 אחד מהשניים · 🟠 אף אחד.")
    groups = [(k, [c for c in cands if c.get("angle") == k]) for k in ("1", "2", "3")]
    groups.append(("", [c for c in cands if c.get("angle") not in ("1", "2", "3")]))
    idx = 0
    for k, group in groups:
        if not group:
            continue
        a = by_key.get(k) or {}
        st.markdown(f"##### {ca.ANGLES.get(k, 'ללא זווית')}"
                    + (f" — {_clean(a['field'])}" if a.get("field") else ""))
        if a.get("why"):
            st.caption(_clean(a["why"]))
        for i in range(0, len(group), 2):
            cols = st.columns(2)
            for col, c in zip(cols, group[i:i + 2]):
                with col:
                    _scout_card(c, mid, lesson, idx, result.get("search_id"),
                                result.get("lesson_topic") or "")
                idx += 1
    u = result.get("usage") or {}
    if u.get("input") is not None or u.get("searches") is not None:
        st.caption(
            f"עלות הסריקה: {_money(u)} · {u.get('searches') or 0} חיפושים · "
            f"{u.get('fetches') or 0} דפים נפתחו"
            + (" · פתיחת דפים חסומה בחשבון — השמות מבוססים על תוצאות החיפוש בלבד"
               if u.get("fetch_disabled") else ""),
            help=(f"טוקנים: {u.get('input') or 0:,} נכנסים · {u.get('output') or 0:,} יוצאים · "
                  f"{u.get('cache_read') or 0:,} מהמטמון · {u.get('cache_write') or 0:,} נכתבו למטמון. "
                  "כולל את קריאת המפה. השקלים לפי שער משוער."))
    if result.get("rejected"):
        with st.expander(f"🚫 נשקלו ונפסלו ({len(result['rejected'])})"):
            st.caption("כדי שלא תחפשו שוב את אותם שמות.")
            for r in result["rejected"]:
                st.markdown(f"- **{_clean(r.get('name') or '')}** — {_clean(r.get('why') or '')}")
    if result.get("queries"):
        with st.expander(f"🌐 מה החיפוש עשה ({len(result['queries'])})"):
            for q in result["queries"]:
                st.markdown(f"- {_clean(q)}")


# Why the scout came back without candidates, in the pair's language. The
# internal token («empty synthesis») used to be printed inside a Hebrew sentence.
SCOUT_FALLBACK_TEXT = {
    "no_map": "אין מפה — בנו מפה קודם.",
    "no_names": "החיפוש לא הביא אף שם שנתמך בדף שנקרא. נסו לערוך את מונחי המפה — רחב יותר, "
                "או תחום אחר — ולסרוק שוב.",
    "model_rejected_all": "הסינון בדק את השמות שעלו ופסל את כולם — אף אחד לא נראה כמו "
                          "מרצה חי ופעיל לנושא הזה. זו תשובה כנה, לא תקלה.",
    "truncated": "הסריקה נקטעה לפני שסיימה. סרקו שוב, אולי עם פחות זוויות.",
    "empty_reply": "המודל לא החזיר תשובה. סרקו שוב.",
    "search_disabled": "חיפוש המרצים באינטרנט חסום כרגע בחשבון Anthropic של התוכנית — "
                       "ספרו למדריך. עד שייפתח, אפשר להמשיך בקישורי החיפוש הידני שלמטה.",
    "error": "הסריקה לא רצה",
}


def _scout_fallback(result: dict) -> None:
    """The screen when the scout has no candidates: the reason, what was
    rejected and why, and — because the map is still here — one manual
    search link per term, so a pair can carry on by hand."""
    reason = result.get("reason") or ("error" if result.get("error") else "no_names")
    msg = SCOUT_FALLBACK_TEXT.get(reason, SCOUT_FALLBACK_TEXT["error"])
    st.warning(msg)
    if reason == "search_disabled" and st.session_state.get("role") == "admin":
        st.caption("להפעלה: [platform.claude.com/settings/privacy](https://platform.claude.com/settings/privacy) "
                   "→ Web search — צריך הרשאת אדמין בארגון של מפתח ה-API.")
    # the API's own words, whatever the reason: the first «search is off»
    # report could not be diagnosed because only reason «error» showed them
    if result.get("error"):
        with st.expander("פרטים טכניים"):
            st.code(str(result["error"])[:300], language=None, wrap_lines=True)
    if result.get("rejected"):
        with st.expander(f"🚫 נשקלו ונפסלו ({len(result['rejected'])})", expanded=True):
            for r in result["rejected"]:
                st.markdown(f"- **{_clean(r.get('name') or '')}** — {_clean(r.get('why') or '')}")
    smap = result.get("map") or {}
    terms = [(a["label"], t) for a in smap.get("angles") or [] if a.get("on", True)
             for t in (a.get("terms") or [])]
    if terms:
        st.markdown("**חיפוש ידני לפי מונחי המפה:**")
        for label, term in terms:
            links = ss.manual_search_links(f"{term} מרצה OR חוקר OR חוקרת")
            st.markdown(f"- {label} · **{_clean(term)}** — [Google]({links['google']}) · "
                        f"[DuckDuckGo]({links['duckduckgo']})")
    if result.get("queries"):
        with st.expander(f"🌐 מה החיפוש עשה ({len(result['queries'])})"):
            for q in result["queries"]:
                st.markdown(f"- {_clean(q)}")


def _speaker_index_card(r: dict, history: list[dict], dup_count: int,
                        teaching: Optional[dict] = None) -> None:
    """A person in the shared memory. The face of the card is who they are and
    what they bring; opening it gives what you actually need before calling —
    where they are, how to reach them, whether they have taught here, and how
    it landed. Outreach status is NOT on this screen: the index is memory, and
    a booking state told nobody anything while browsing."""
    teaching = teaching or {}
    with st.container(border=True, key=f"card-sp-{r['speaker_id']}"):
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
                            f"- {o['status']} · {where} · {who} · {str(o.get('created_at') or '')[:10]}"
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
        _empty("אין התאמות.", "נסו תחום אחר, או חיפוש חופשי.")
        return

    seen: dict[str, int] = {}
    for r in rows:
        seen[r["name"]] = seen.get(r["name"], 0) + 1

    shown = st.session_state.setdefault("speaker_page_size", 24)
    for i in range(0, min(len(rows), shown), 3):
        # keyed so the CSS can stretch the three cards of THIS row to one
        # height — st.columns leaves them `align-items: start` and the «פרטים»
        # doors landed at three different heights (measured 93 / 122 / 173px).
        cols = st.container(key=f"sp-row-{i}").columns(3)
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
        _empty("לא משובצים לך משמרים.")
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


# Two index rows share this name: the journal refuses to pick one, so the
# approach was NOT logged. Said out loud — it used to vanish silently.
_AMBIGUOUS_WARNING = ("במאגר יש יותר מרשומה אחת בשם «{name}» — הפנייה לא נרשמה ביומן. "
                      "המדריך צריך לאחד את הרשומות במאגר.")


def _candidate_status_changed(cid: int, key: str, mid: int, name: str) -> None:
    if not dm.update_lesson_speaker_status(cid, st.session_state[key], mishmar_id=mid,
                                           student_id=st.session_state.student_id):
        st.toast(_AMBIGUOUS_WARNING.format(name=name), icon="⚠️")


def _close_candidate(lesson_id: int, name: str, mid: int) -> None:
    res = dm.close_lesson_speaker(lesson_id, name, mishmar_id=mid,
                                  student_id=st.session_state.student_id)
    # The slot's own «סגירת מרצה» task is what this click means. The sync
    # derives completion from the slot's state, so it closes here AND catches
    # a task the sync created after the speaker was already closed.
    sync = dm.sync_lesson_tasks(mid)
    st.toast(f"«{res['closed']}» נסגר לשיעור"
             + (" · משימת סגירת המרצה סומנה כבוצעה" if sync.get("completed") else "")
             + (f" · הוסרו: {', '.join(res['removed'])}" if res["removed"] else ""))
    if not res.get("logged", True):
        st.toast(_AMBIGUOUS_WARNING.format(name=res["closed"]), icon="⚠️")


def _add_candidate_clicked(lesson_id: int, mid: int, close: bool = False) -> None:
    """on_click of the candidate form's submits. Reads the keyed inputs, writes,
    and EMPTIES them — a form submit used to `st.rerun()` the whole app and
    leave the previous name sitting in the box. With `close`, the person is
    added and closed as the slot's speaker in one click: with a single option
    there was no way to close without first adding and then closing."""
    nk, pk = f"cn-{lesson_id}", f"cp-{lesson_id}"
    name = (st.session_state.get(nk) or "").strip()
    phone = (st.session_state.get(pk) or "").strip()
    if not name:
        return
    dm.add_lesson_speaker(lesson_id, name, phone=phone,
                          student_id=st.session_state.student_id)
    st.session_state[nk] = ""
    st.session_state[pk] = ""
    if close:
        _close_candidate(lesson_id, name, mid)
    else:
        st.toast(f"«{name}» נוסף כמועמד — וגם למאגר המשותף")


def _phone_changed(cid: int, key: str) -> None:
    dm.set_candidate_phone(cid, st.session_state.get(key))


def _add_presenter_clicked(lesson_id: int, mid: int) -> None:
    """on_click of the חבורות form's submit: write, sync the day-of tasks, and
    reset the row to an empty name and the default room."""
    nk, rk = f"chn-{lesson_id}", f"chr-{lesson_id}"
    name = (st.session_state.get(nk) or "").strip()
    room = st.session_state.get(rk) or dm.DEFAULT_ROOM
    if not name:
        return
    dm.add_chavurot_presenter(lesson_id, name, room=room,
                              student_id=st.session_state.student_id)
    res = dm.sync_lesson_tasks(mid)
    st.session_state[nk] = ""
    st.session_state[rk] = dm.DEFAULT_ROOM
    st.toast(f"«{name}» נוסף כמעביר חבורה — {room}"
             + (" · נוספה משימת סידור" if res["created"] else ""))


def _add_slot_clicked(mid: int, role: Optional[str] = None) -> None:
    """A new slot is born with its tasks — a lesson gets «סגירת מרצה» and
    «דף מקורות», a חבורות round gets presenters, sheets and rooms."""
    dm.add_lesson_slot(mid, 60, role=role)
    dm.sync_lesson_tasks(mid)


def _sync_tasks_clicked(mid: int) -> None:
    res = dm.sync_lesson_tasks(mid)
    st.toast(f"נוספו {res['created']} משימות · נוקו {res['removed']}"
             + (f" · שויכו {res['adopted']}" if res.get("adopted") else "")
             + (f" · עודכן ניסוח ב-{res['renamed']}" if res.get("renamed") else ""))


def _room_changed(cid: int, key: str, mid: int) -> None:
    dm.set_candidate_room(cid, st.session_state[key] or None)
    dm.sync_lesson_tasks(mid)          # the day-of «סידור <חלל>» tasks follow the rooms


def _source_changed(cid: int, key: str, mid: int) -> None:
    dm.set_candidate_source(cid, st.session_state.get(key))
    dm.sync_lesson_tasks(mid)          # «דפי מקורות למעבירי החבורות» completes itself


def _remove_presenter(cid: int, mid: int) -> None:
    dm.delete_lesson_candidate(cid)
    dm.sync_lesson_tasks(mid)


def _chavurot_rows(mid: int, l: dict, cands: list[dict]) -> None:
    """A חבורות slot is not a competition between candidates — it is a LIST of
    presenters, and each one needs two things of their own: a room out of the
    four, and their own source sheet. There is no «סגרנו» here."""
    used = [c.get("room") for c in cands if c.get("room")]
    if cands:
        st.markdown("**מעבירי החבורות:**")
        st.caption("מעביר אחד — בבית המדרש (משימת «סידור הבית מדרש»). "
                   "משני מעבירים, כל חלל נוסף מקבל משימת סידור משלו ליום המשמר.")
    for cand in cands:
        clash = cand.get("room") and used.count(cand["room"]) > 1
        top = st.container(horizontal=True, wrap=True, gap="small",
                           vertical_alignment="center")
        top.markdown(
            f"👥 **{_clean(cand['name'])}**"
            + (" <span class='chip chip-red'>⚠️ אותו חלל לשניים</span>" if clash else "")
            + (f" <span class='card-meta'>{_clean(cand['phone'])}</span>"
               if cand.get("phone") else ""),
            unsafe_allow_html=True, width="stretch")
        rkey = f"room-{cand['id']}"
        top.selectbox(
            "חלל", ["", *dm.CHAVUROT_ROOMS], key=rkey, width=170,
            index=(dm.CHAVUROT_ROOMS.index(cand["room"]) + 1)
            if cand.get("room") in dm.CHAVUROT_ROOMS else 0,
            format_func=lambda r: r or "— חלל —", label_visibility="collapsed",
            on_change=_room_changed, args=(cand["id"], rkey, mid))
        top.button("🗑", key=f"ib-rmch-{cand['id']}", help="הסרת המעביר",
                   on_click=_remove_presenter, args=(cand["id"], mid))
        skey = f"csrc-{cand['id']}"
        st.text_input(
            "דף מקורות", key=skey, value=cand.get("source_url") or "",
            placeholder="📎 קישור לדף המקורות של החבורה הזו (Drive וכו׳)",
            label_visibility="collapsed",
            on_change=_source_changed, args=(cand["id"], skey, mid))
    if not cands:
        _empty("עוד לא נוספו מעבירים.", "כל מעביר מקבל חלל ודף מקורות משלו.")

    # The submit is a callback: the write lands before the fragment reruns,
    # the boxes come back empty, and nothing restarts the whole page.
    with st.form(f"addch-{l['id']}", border=False):
        fr = st.container(horizontal=True, wrap=True, gap="small")
        fr.text_input("שם המעביר", key=f"chn-{l['id']}", width="stretch",
                      label_visibility="collapsed", placeholder="שם המעביר")
        fr.selectbox("חלל", dm.CHAVUROT_ROOMS, key=f"chr-{l['id']}", width=170,
                     index=0, label_visibility="collapsed")
        fr.form_submit_button("➕ מעביר", on_click=_add_presenter_clicked,
                              args=(l["id"], mid))


def _candidate_rows(mid: int, l: dict, cands: list[dict]) -> None:
    """The lesson's optional-speakers list: name · phone · status · actions.
    Once one is closed, the list collapses to that single row."""
    closed = l.get("speaker_name")
    if closed:
        sc = st.container(horizontal=True, wrap=False, gap="small",
                          vertical_alignment="center")
        sc.markdown(f"🎤 **{_clean(closed)}** {_chip('✅ סגור', 'green')}",
                    unsafe_allow_html=True, width="stretch")
        # Closing used to be one-way. People change their minds, and the
        # journal keeps the history either way.
        sc.button("🔄 החלף", key=f"reopen-{l['id']}",
                   help="משחרר את המקטע וממשיך לרשימת המועמדים",
                   on_click=dm.reopen_lesson_speaker, args=(l["id"],))
        return
    if cands:
        st.markdown("**מרצים אופציונליים:**")
    for cand in cands:
        cr = st.container(horizontal=True, wrap=True, gap="small",
                          vertical_alignment="center")
        cr.markdown(f"**{_clean(cand['name'])}**", unsafe_allow_html=True, width="stretch")
        # the phone is a field, not a label — it was not editable once typed
        pkey = f"cph-{cand['id']}"
        cr.text_input("טלפון", key=pkey, value=cand.get("phone") or "", width=140,
                      placeholder="טלפון", label_visibility="collapsed",
                      on_change=_phone_changed, args=(cand["id"], pkey))
        cur = cand.get("status") or dm.SPEAKER_STATUSES[0]
        skey = f"cst-{cand['id']}"
        cr.selectbox(
            "סטטוס", dm.SPEAKER_STATUSES, width=150,
            index=dm.SPEAKER_STATUSES.index(cur) if cur in dm.SPEAKER_STATUSES else 0,
            key=skey, label_visibility="collapsed",
            on_change=_candidate_status_changed, args=(cand["id"], skey, mid, cand["name"]))
        cr.button("✅ סגור מרצה", key=f"close-{cand['id']}", type="primary",
                  help="הופך למרצה של השיעור; שאר המועמדים יוסרו ומשימת סגירת המרצה נסגרת",
                  on_click=_close_candidate, args=(l["id"], cand["name"], mid))
        cr.button("🗑", key=f"ib-rmc-{cand['id']}",
                  on_click=dm.delete_lesson_candidate, args=(cand["id"],))

    # The add form sits right under the list, as one flex row — the old three
    # columns squeezed the submit into «+ מו…» and it looked like a text field.
    # Two submits: «➕ מועמד» adds to the list, «✅ סגור מרצה» adds AND closes —
    # the one-option case had no door until the person was first a candidate.
    # Both are callbacks, so the fragment reruns once and the boxes empty.
    with st.form(f"addcand-{l['id']}", border=False):
        fr = st.container(horizontal=True, wrap=True, gap="small")
        fr.text_input("שם מרצה", key=f"cn-{l['id']}", width="stretch",
                      label_visibility="collapsed", placeholder="שם מרצה אפשרי")
        fr.text_input("טלפון", key=f"cp-{l['id']}", width=150,
                      label_visibility="collapsed", placeholder="טלפון (רשות)")
        fr.form_submit_button("➕ מועמד", on_click=_add_candidate_clicked,
                              args=(l["id"], mid, False))
        fr.form_submit_button("✅ סגור מרצה", type="primary",
                              help="מוסיף את השם וסוגר אותו כמרצה השיעור בלחיצה אחת",
                              on_click=_add_candidate_clicked, args=(l["id"], mid, True))


@st.dialog("עריכת מקטע", width="large")
def _lesson_edit_dialog(mid: int, l: dict) -> None:
    """The slot's editor as a modal. It used to unfold inline inside the card
    (eleven fields and an uploader pushing the whole column down); a dialog
    keeps the evening readable behind it and needs no session-state toggle —
    `st.rerun()` at the end is what closes it."""
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
        res = dm.delete_lesson_with_tasks(mid, l["id"])
        st.toast(f"המקטע נמחק · נמחקו איתו {res['tasks']} משימות פתוחות שלו")
        st.rerun()
    if cancel:
        st.rerun()
    if saved:
        dm.upsert_lesson(mid, l["slot_order"], title=title,
                         description=desc, lesson_role=role or None, fmt=fmt or None,
                         student_id=st.session_state.student_id)
        dm.set_lesson_duration(mid, l["id"], int(duration))
        source = None
        if up is not None:
            with st.spinner("מעלה את דף המקורות…"):
                source, err = dm.upload_source_sheet(mid, l["id"], up.name, up.getvalue())
            if not source:
                st.warning(f"ההעלאה נכשלה — הדביקו קישור במקום. ({err})")
        if source or link.strip() != (l.get("source_url") or ""):
            dm.set_lesson_source(l["id"], source or link)
        dm.recompute_lesson_times(mid)
        # a slot that became חבורות (or stopped being one) swaps its tasks now,
        # not when someone remembers the manual sync
        dm.sync_lesson_tasks(mid)
        st.toast("המקטע נשמר"); st.rerun()


def _topic_and_structure(mid: int, tasks: list[dict],
                         lessons: Optional[list[dict]] = None,
                         candidates: Optional[dict[int, list[dict]]] = None) -> None:
    m = dm.get_mishmar(mid)

    # --- the topic: a hero form until it exists, a quiet line after ---
    if not m.get("topic"):
        with st.container(border=True, key=f"card-topic-{mid}"):
            st.markdown("#### הצעד הראשון: לסגור נושא")
            st.caption(
                "הנושא הוא מנוע הערב כולו — מומלץ לסגור אותו כשלושה שבועות לפני. "
                "אין רעיון? בדקו בארכיון אם היה משמר דומה, ודברו עם המדריך."
            )
            with st.form(f"topic-{mid}"):
                st.text_input(
                    "שם הנושא", key=f"topic-new-{mid}",
                    placeholder="למשל: כרוניקה של שינוי — האם אדם יכול לשכתב את העבר?")
                st.form_submit_button("🎯 סגור את הנושא", type="primary",
                                      on_click=_close_topic_clicked, args=(mid,))
        return   # no timeline before a topic — one step at a time
    else:
        with st.expander(f"🎯 הנושא: {m['topic']} — לעריכה"):
            with st.form(f"topic-{mid}"):
                st.text_input("שם הנושא", value=m["topic"], key=f"topic-edit-{mid}")
                st.form_submit_button("עדכן נושא", on_click=_update_topic_clicked,
                                      args=(mid,))

    # --- the evening as a duration-driven timeline ---
    st.markdown("#### מבנה הערב")
    st.caption(
        "השעות נגזרות מהמשכים — שינוי משך של משבצת מזרים את כל הערב. "
        "שלושה שיעורים ושעת חבורות הם ברירת המחדל; אפשר לשנות הכל."
    )
    if lessons is None:
        lessons = dm.get_lessons(mid)
    if not lessons:
        st.button(f"✨ צור את שלד הערב ({dm.mishmar_start(mid)}, שלושה שיעורים + חבורות)",
                  type="primary", width="stretch",
                  on_click=dm.create_default_timeline, args=(mid,))
        return

    if candidates is None:
        candidates = dm.get_lesson_speakers(mid, lessons=lessons)
    linked = dm.get_tasks_for_lesson(tasks=tasks)
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
                    and not dm.is_chavurot(l):
                highlight = l["id"]        # the dialog is the pair's call; we only point
                break
    if highlight:
        st.session_state["_scroll_target_lesson"] = highlight   # read by _scroll_after_nav
    if focus_task:
        where = "" if highlight else " — לא זוהה מקטע ספציפי, בחרו למטה"
        st.info(f"⤴ הגעתם מהמשימה «{_clean(focus_task['task_description'])}»{where}")

    slot_names = _slot_names(lessons)
    lesson_no = 0
    for l in lessons:
        if l.get("is_break"):
            # a slim break row: the only knob is minutes
            br = st.container(horizontal=True, wrap=False, gap="small",
                              vertical_alignment="center")
            br.markdown(
                f"<div class='card-meta' style='white-space:nowrap;padding:.35rem .6rem'>"
                f"☕ {l.get('duration_minutes') or 30} דק׳ · "
                f"<span dir='ltr'>{_slot_times(l)}</span></div>",
                unsafe_allow_html=True, width="stretch",
            )
            br.number_input(
                "דק'", min_value=5, max_value=90, step=5,
                value=int(l.get("duration_minutes") or 30),
                key=f"brk-{l['id']}", label_visibility="collapsed", width=110,
                on_change=lambda mid=mid, lid=l["id"], k=f"brk-{l['id']}":
                    dm.set_lesson_duration(mid, lid, int(st.session_state[k])))
            br.button("✕", key=f"ib-brx-{l['id']}",
                      help="מחיקת ההפסקה — הזמנים שאחריה מתעדכנים",
                      on_click=dm.delete_lesson_with_tasks, args=(mid, l["id"]))
            continue

        lesson_no += 1
        cands = candidates.get(l["id"], [])
        # role OR format OR title — a pair that set only the FORMAT to חבורות
        # used to get an ordinary speaker slot, with no «מי מעביר» anywhere.
        is_chavurot = dm.is_chavurot(l)
        my_tasks = linked.get(l["id"], [])
        with st.container(border=True, key=f"card-l-{l['id']}"):
            head = _clean(slot_names.get(l["id"], f"שיעור {lesson_no}"))
            if not (l.get("title") or "").strip() and not is_chavurot:
                head += " — ללא כותרת"
            chips = []
            if l.get("lesson_role"):
                chips.append(_chip(l["lesson_role"], "gold"))
            if l.get("format"):
                chips.append(_chip(l["format"], "gray"))
            if is_chavurot and cands:
                chips.append(_chip(f"{len(cands)} מעבירים", "blue"))
            elif not l.get("speaker_name") and cands:
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

            if is_chavurot:
                _chavurot_rows(mid, l, cands)
            else:
                _candidate_rows(mid, l, cands)

            # The tasks that belong to THIS slot, closable where the work is.
            # This is the half that was missing: the board could point at the
            # evening, and the evening could not point back.
            # One full-width row per task: text on the right, the ✓ box in
            # the same left column on every row. Content-width chips made a
            # staircase — different widths, right-aligned, a ✓ on each step —
            # and long text pushed the box around.
            for t in open_here:
                with st.container(border=True, key=f"lt-{t['id']}"):
                    ch = st.container(horizontal=True, wrap=False, gap="small",
                                      vertical_alignment="center")
                    late = bool(t.get("overdue"))
                    ch.markdown(
                        f"<span class='card-meta' style='"
                        f"{'color:#b42318;font-weight:600' if late else ''}'>"
                        + ("⏰ " if late else "")
                        + f"{_clean(t['task_description'])}</span>",
                        unsafe_allow_html=True, width="stretch")
                    ch.button("✓", key=f"ib-lt-{t['id']}", help="סמן שבוצע",
                              on_click=_set_status,
                              args=(t["id"], "DONE", "בוצע 🎉"))

            # The slot's own controls. «דף מקורות» opens the EDITOR, where the
            # upload and the link field live — it used to create a task and
            # navigate back to this same panel, which read as a dead button.
            # No slot-level «סגירת מרצה» here: closing happens next to the
            # candidate's name, and the task already exists from the sync.
            tc = st.container(horizontal=True, wrap=True, gap="small",
                              vertical_alignment="center")
            if not is_chavurot:
                # `ibw-`: the 2rem icon-box grammar with a word in it — beside
                # the 2rem ✏️ box, a 40px button looked like a different app
                if tc.button("📎 דף מקורות", key=f"ibw-src-{l['id']}",
                             help="פותח את עריכת המקטע — שם מעלים קובץ או מדביקים קישור"):
                    _lesson_edit_dialog(mid, l)
            # opening a dialog IS a rerun, so a plain `if` is the honest form here
            if tc.button("✏️", key=f"ib-ed-{l['id']}", help="עריכת המקטע"):
                _lesson_edit_dialog(mid, l)


    ac = st.container(horizontal=True, wrap=True, gap="small")
    ac.button("➕ הוסף שיעור", on_click=_add_slot_clicked, args=(mid, None))
    ac.button("➕ הוסף חבורות", help="סבב חבורות נוסף — מעבירים, חללים ודפי מקורות משלו",
              on_click=_add_slot_clicked, args=(mid, "חבורות"))
    ac.button("➕ הוסף הפסקה", on_click=dm.add_break, args=(mid, 15))
    # For an evening built before the slots owned their tasks: fills in what is
    # missing and clears tasks whose slot is gone. Never touches a DONE row.
    ac.button("🔄 סנכרן משימות למקטעים",
              help="משלים לכל מקטע את המשימות שלו — סגירת מרצה, דף מקורות, "
                   "ובחבורות גם מי מעביר וחלוקת החללים",
              on_click=_sync_tasks_clicked, args=(mid,))


def _slot_names(lessons: list[dict]) -> dict[int, str]:
    """Every slot of the evening by name — ONE naming, shared by the structure
    panel, the feedback form and the rooms panel.

    Two rules the screens used to get wrong on their own:
    · a round of חבורות is recognised by `dm.is_chavurot` (role OR format OR
      title). The feedback form asked `lesson_role == "חבורות"`, so a round the
      pair marked in the FORMAT field was listed as «שיעור 2».
    · names must be UNIQUE. `feedback.lesson_title` is the key for «one
      submission per slot per trainee», so when #01's two rounds both read
      «חבורות», feedback on the first silently blocked the second. A round in
      an evening that holds several says which one it is.

    The lesson numbering counts every non-break slot, exactly as
    `dm._slot_tasks` numbers «סגירת מרצה — שיעור N» — the two must agree."""
    slots = [l for l in lessons if not l.get("is_break")]
    rounds = [l["id"] for l in slots if dm.is_chavurot(l)]
    names: dict[int, str] = {}
    for i, l in enumerate(slots, 1):
        title = (l.get("title") or "").strip()
        if dm.is_chavurot(l):
            names[l["id"]] = (title or "חבורות") + dm.round_suffix(
                rounds.index(l["id"]) + 1, len(rounds))
        else:
            names[l["id"]] = title or f"שיעור {i}"
    # two slots the pair gave the same title: the time tells them apart
    seen: dict[str, int] = {}
    for name in names.values():
        seen[name] = seen.get(name, 0) + 1
    for l in slots:
        if seen.get(names[l["id"]], 0) > 1 and l.get("start_time"):
            names[l["id"]] += f" ({l['start_time']})"
    return names


def _slot_label(l: dict, index: int) -> str:
    """How a slot is named in a task's «שייך למקטע» line."""
    title = (l.get("title") or "").strip()
    if not title and dm.is_chavurot(l):
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
                    detail_placeholder: Optional[str] = None,
                    with_detail: bool = True) -> None:
    """A checkable list: a label, an optional detail, and a done box.

    `with_detail=False` is the כיבוד list — «מי קונה» turned out not to matter,
    so one free-text line per row is the whole row."""
    st.markdown(f"**{title}**")
    st.caption(hint)
    for it in items:
        lr = st.container(horizontal=True, wrap=False, gap="small",
                          vertical_alignment="center")
        lr.checkbox("בוצע", value=bool(it.get("done")), key=f"lg-{it['id']}",
                    label_visibility="collapsed",
                    on_change=lambda i=it["id"], k=f"lg-{it['id']}":
                        dm.toggle_logistics_item(i, st.session_state[k]))
        style = "color:#5c6577;text-decoration:line-through" if it.get("done") else ""
        lr.markdown(
            f"<div style='{style}'>{_clean(it['label'])}"
            + (f" <span class='card-meta'>{_clean(it['detail'])}</span>"
               if it.get("detail") else "")
            + "</div>", unsafe_allow_html=True, width="stretch")
        lr.button("🗑", key=f"ib-lgx-{it['id']}",
                  on_click=dm.delete_logistics_item, args=(it["id"],))
    if not items:
        _empty("עוד לא נוספו שורות.")
    with st.form(f"lgadd-{mid}-{kind}", border=False, clear_on_submit=True):
        fr = st.container(horizontal=True, wrap=True, gap="small")
        fr.text_input("פריט", key=f"lgl-{mid}-{kind}", width="stretch",
                      label_visibility="collapsed", placeholder=placeholder)
        if with_detail:
            fr.text_input("פירוט", key=f"lgd-{mid}-{kind}", width=180,
                          label_visibility="collapsed",
                          placeholder=detail_placeholder or "פירוט (רשות)")
        fr.form_submit_button("➕ הוסף", on_click=_add_logistics_clicked,
                              args=(mid, kind, with_detail))


def _rooms_summary(mid: int, legacy: list[dict],
                   candidates: Optional[dict[int, list[dict]]] = None) -> None:
    """Who sits where — DERIVED from the חבורות presenters, not typed twice.

    The rooms used to be a free-text logistics list, so the same fact lived in
    two places and neither knew about the other. The presenters own it now;
    this panel only shows it, and offers the door to where it is edited."""
    st.markdown("**🚪 חלוקת החללים לחבורות**")
    st.caption("נגזר ממעבירי החבורות במבנה הערב — כל מעביר וחלל אחד, בתוך הסבב שלו.")
    all_lessons = dm.get_lessons(mid)
    rounds = [l for l in all_lessons if not l.get("is_break") and dm.is_chavurot(l)]
    # The candidates come from the caller, which already loaded them for the
    # structure panel: fetching again with a different argument list would miss
    # that memo and cost a second query for rows we are already holding.
    if candidates is None:
        candidates = dm.get_lesson_speakers(mid, lessons=all_lessons) if all_lessons else {}
    names = _slot_names(all_lessons)
    if any(candidates.get(l["id"]) for l in rounds):
        for l in rounds:
            rows = candidates.get(l["id"], [])
            # A room is taken FOR A ROUND. The count used to run over every
            # presenter of the evening, so #01's two rounds — an hour apart —
            # flagged each other: «אותו חלל לשניים» on eight rows at once.
            used = [r.get("room") for r in rows if r.get("room")]
            if len(rounds) > 1:
                st.markdown(f"<div class='card-meta'>🕘 {_clean(_slot_times(l))} · "
                            f"<b>{_clean(names.get(l['id'], 'חבורות'))}</b></div>",
                            unsafe_allow_html=True)
            if not rows:
                st.caption("— אין עדיין מעבירים בסבב הזה —")
                continue
            for r in rows:
                room = r.get("room")
                mark = " ⚠️ אותו חלל לשניים בסבב הזה" if room and used.count(room) > 1 else ""
                st.markdown(
                    f"- **{_clean(room or 'טרם נקבע חלל')}** — {_clean(r['name'])}{mark}"
                    + (f" · [📎 דף מקורות]({r['source_url']})" if r.get("source_url") else ""))
    else:
        _empty("אין עדיין מעבירי חבורות.", "הוסיפו אותם במבנה הערב.")
    st.button("↗ למבנה הערב", key=f"rooms-go-{mid}",
              on_click=_goto, args=(NAV_WORKFILE, mid, WF_STRUCTURE))
    if legacy:
        with st.expander(f"שורות חללים ישנות ({len(legacy)})"):
            st.caption("נרשמו כשהחללים היו רשימה חופשית. אפשר למחוק אותן.")
            for it in legacy:
                lr = st.container(horizontal=True, wrap=False, gap="small",
                                  vertical_alignment="center")
                lr.markdown(f"{_clean(it['label'])}"
                            + (f" <span class='card-meta'>{_clean(it['detail'])}</span>"
                               if it.get("detail") else ""),
                            unsafe_allow_html=True, width="stretch")
                lr.button("🗑", key=f"ib-lgold-{it['id']}",
                          on_click=dm.delete_logistics_item, args=(it["id"],))


def _upload_invitation_clicked(mid: int, key: str) -> None:
    """on_click of the invitation form: the uploaded file is in session_state
    under the uploader's key; upload it, store the URL, say what failed."""
    up = st.session_state.get(key)
    if up is None:
        st.toast("בחרו קובץ תמונה קודם")
        return
    url, err = dm.upload_invitation(mid, up.name, up.getvalue())
    if url:
        dm.set_invitation(mid, url=url)
        st.toast("ההזמנה הועלתה")
    else:
        st.toast(f"ההעלאה נכשלה — {err}")


def _logistics_panel(mid: int, m: dict,
                     candidates: Optional[dict[int, list[dict]]] = None) -> None:
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
        "למשל: עוגות · פיצוחים · שתייה חמה", with_detail=False)
    st.divider()
    _rooms_summary(mid, items.get("חלל", []), candidates)
    st.divider()
    st.markdown("**✉️ ההזמנה למשמר**")
    st.caption("ההזמנה היא תמונה אחת — הפוסטר שיוצא בוואטסאפ. מעלים אותה כאן.")
    if m.get("invitation_url"):
        st.image(m["invitation_url"], width=320)
        st.button("🗑", key=f"ib-inv-{mid}", help="הסרת ההזמנה",
                  on_click=dm.set_invitation, args=(mid, None, ""))
    ukey = f"invup-{mid}"
    with st.form(f"inv-{mid}", border=False):
        st.file_uploader("תמונת ההזמנה", key=ukey, type=["png", "jpg", "jpeg", "webp"],
                         label_visibility="collapsed")
        st.form_submit_button("⬆️ העלאת ההזמנה", type="primary",
                              on_click=_upload_invitation_clicked, args=(mid, ukey))


def _roster_drift_line(placeholders: list[dict], unowned: bool, drift: dict) -> str:
    """One sentence naming exactly what the file says and the database does not.
    «N שורות שונות» told the instructor nothing he could check; the Mishmar
    numbers and the names do."""
    if drift.get("error"):
        return drift["error"]
    bits = []
    if placeholders:
        bits.append(f"{len(placeholders)} שורות עדיין נקראות «חניך N»")
    if unowned:
        bits.append("אף משמר אינו משובץ לחניכים")
    if drift["mishmarim"]:
        shown = " · ".join(f"#{m:02d}" for m in drift["mishmarim"][:8])
        more = f" ועוד {len(drift['mishmarim']) - 8}" if len(drift["mishmarim"]) > 8 else ""
        bits.append(f"{len(drift['mishmarim'])} משמרים עם זוג אחר ({shown}{more})")
    if drift["added"]:
        bits.append("חניכים חדשים בקובץ: " + " · ".join(drift["added"]))
    if drift["removed"]:
        bits.append("ירדו מהרשימה: " + " · ".join(drift["removed"]))
    return " · ".join(bits) if bits else "שום דבר — המסד והקובץ זהים."


@st.dialog("👥 שמות החניכים והשיבוץ")
def _roster_dialog() -> None:
    """Apply students_tasks.md to `students` + `assignments`. Two steps, like
    the reset: it adds missing names, REMOVES a trainee the file no longer
    lists, and replaces the pairs of every trainee Mishmar. Idempotent, so a
    second run is harmless — but it is still the instructor's call, not the
    app's, and a deletion is not something to discover afterwards, so the
    dialog names every change before the checkbox."""
    drift = dm.roster_drift()
    st.markdown(
        "מעדכן את שמות החניכים לפי טבלת האינדקס ב-`students_tasks.md` ומשבץ מחדש את "
        "משמרים #03–#21 לפי שורות «אחראים». **משמרי הצוות (#01–#02) לא נוגעים.** "
        "משימות, מרצים ומבנה הערבים נשארים כפי שהם."
    )
    if drift.get("error"):
        st.error(drift["error"])
        return
    if drift["mishmarim"]:
        st.markdown("**משמרים שישתנו:** "
                    + " · ".join(f"#{m:02d}" for m in drift["mishmarim"]))
    if drift["added"]:
        st.markdown("**ייווספו:** " + " · ".join(drift["added"]))
    if drift["removed"]:
        st.warning(
            "**יימחקו מהמסד:** " + " · ".join(drift["removed"])
            + " — השם יורד מרשימת החניכים ומכל השיבוצים, והכניסה שלו לאפליקציה נסגרת. "
              "מה שהוא כתב (פניות למרצים, משוב) נשאר, בלי שם הכותב."
        )
    if not (drift["mishmarim"] or drift["added"] or drift["removed"]):
        st.success("המסד והקובץ כבר זהים — אין מה להחיל.")
    ok = st.checkbox("אני מבין/ה — להחיל את השמות והשיבוץ", key="roster-ok")
    if st.button("👥 החל", key="roster-apply", type="primary", disabled=not ok):
        res = dm.apply_trainee_roster()
        if res.get("error"):
            st.error(res["error"])
            return
        gone = (" · הוסרו: " + " · ".join(res["removed"])) if res["removed"] else ""
        st.toast(f"{res['names']} שמות · נוספו {res['created']} · נמחקו {res['deleted']}"
                 f"{gone} · {res['assignments']} שיבוצים")
        st.rerun()   # closes the dialog; the cards read the new names


@st.dialog("⚠️ איפוס המשמר")
def _reset_dialog(mid: int) -> None:
    """Start the evening over. A modal, deliberately two steps and deliberately
    loud — it deletes a season's worth of a pair's work."""
    st.markdown(
        "מוחק את **כל** מה שנבנה כאן — מבנה הערב והמרצים, המשימות, הלוגיסטיקה, "
        "התקציב והמשוב — ומחזיר את המשמר לנקודת ההתחלה: בחירת נושא, "
        "עם תבנית המשימות האחידה. "
        "**יומן הפניות למרצים לא נמחק** — הוא הזיכרון המשותף של כל הזוגות, "
        "ומחיקה שלו הייתה מוחקת מידע של אחרים."
    )
    ok = st.checkbox(f"אני מבין/ה — לאפס את משמר #{mid:02d}", key=f"rst-ok-{mid}")
    if st.button("🗑 אפס את המשמר", key=f"rst-{mid}", type="primary", disabled=not ok):
        res = dm.reset_mishmar(mid)
        st.toast(
            f"המשמר אופס · נמחקו {res['lessons']} מקטעים, {res['tasks']} משימות · "
            f"הוחזרו {res['tasks_restored']} משימות מקוריות")
        st.rerun()   # closes the dialog and restarts the page on the empty Mishmar


def _reset_panel(mid: int, m: dict) -> None:
    # The door to the dialog. Opening a dialog IS a rerun, so this is the one
    # button here that legitimately stays an `if`, not an on_click.
    if st.button("⚠️ איפוס המשמר…", key=f"rst-open-{mid}",
                 help="מוחק את כל מה שנבנה במשמר הזה ומחזיר אותו להתחלה — שני שלבים, עם אישור"):
        _reset_dialog(mid)


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
    # One fetch of the evening's speakers, shared by the structure panel and the
    # rooms summary — two calls with different argument lists are two queries.
    candidates = dm.get_lesson_speakers(mid, lessons=lessons) if lessons else {}
    # keyed container → `.st-key-wf-cols` in CSS: below 1100px the two columns
    # stack (evening first) instead of squeezing every button into a sliver.
    right, left = st.container(key="wf-cols").columns([1.15, 1], gap="medium")
    with right:
        with _wf_panel(WF_STRUCTURE, f"{len([l for l in lessons if not l.get('is_break')])} מקטעים"):
            _safe(_topic_and_structure, mid, tasks, lessons=lessons,
                  candidates=candidates)
        with _wf_panel(WF_LOGISTICS):
            _safe(_logistics_panel, mid, m, candidates)
        with _wf_panel(WF_AFTER):
            _safe(_after_tab, mid)
        _reset_panel(mid, m)
    with left:
        st.markdown("#### ✅ המשימות")
        _tasks_tab(mid, progress, lessons)


def _task_editor(row, t: dict, slots: list[dict], k: str) -> None:
    """The task editor as a popover under the card's ✏️. It was a `st.dialog`
    — which closes only through `st.rerun()`, a whole-app run for a title
    edit — and before that an inline form that pushed the column. A popover
    opens and saves INSIDE the workfile fragment; its key carries a nonce
    the save bumps, so the run after the save draws a fresh, closed editor."""
    tid = t["id"]
    nonce = st.session_state.get(f"edit-nonce-{tid}", 0)
    with row.popover("✏️", key=f"ib-ed-{k}-{nonce}", help="עריכה"):
        with st.form(f"edit-{tid}-{nonce}", border=False):
            st.text_input("כותרת", value=t["task_description"],
                          key=f"edit-desc-{tid}-{nonce}")
            st.text_area("תיאור", value=t.get("details") or "", height=68,
                         key=f"edit-details-{tid}-{nonce}")
            st.text_input("מומלץ עד (dd.mm.yyyy)",
                          value=_fmt_date(t["due_date"]) if t.get("due_date") else "",
                          key=f"edit-due-{tid}-{nonce}")
            # Tying a task to a slot by hand — this is what turns the guess
            # above into a fact. «לא שייך למקטע» is the honest default:
            # כיבוד, קישוט and הזמנה belong to the evening, not to a slot.
            if slots:
                choices = [None] + [l["id"] for l in slots]
                labels = {l["id"]: _slot_label(l, i + 1)
                          for i, l in enumerate(slots)}
                st.selectbox(
                    "שייך למקטע בערב", choices,
                    index=choices.index(t["lesson_id"])
                    if t.get("lesson_id") in choices else 0,
                    format_func=lambda i: labels.get(i, "— לא שייך למקטע —"),
                    placeholder="— לא שייך למקטע —",   # a None option shows the placeholder, not format_func
                    key=f"edit-slot-{tid}-{nonce}")
            st.form_submit_button("💾 שמור", type="primary",
                                  on_click=_save_task_edit,
                                  args=(t, nonce, bool(slots)))


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

    with st.container(border=True, key=f"card-wt-{key_prefix}-{t['id']}"):
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
        # one flex row that never stacks — on a phone the four controls
        # used to become four lines
        row = st.container(horizontal=True, wrap=False, gap="small")
        # The invitation is designed and sent outside the app: there is nowhere
        # for «פתח» to lead and «בתהליך» says nothing. Done, or not done.
        no_door = t.get("category") == "הזמנה"
        if t["status"] != "DONE":
            if not no_door and row.button("פתח ↗", key=f"{k}-go",
                                          help="למקום שבו סוגרים את זה"):
                # same evening, same screen: a fragment rerun, not a page restart
                if t.get("category") == "אחרי":
                    _goto_local(WF_AFTER)
                elif slot or t.get("category") in ("מרצים", "תוכן", "נושא"):
                    # the evening builder resolves the exact slot from the task
                    _goto_local(WF_STRUCTURE, task_focus=t["id"])
                else:
                    _goto_local(WF_LOGISTICS)
            row.button("✓", key=f"ib-dn-{k}", help="סמן שבוצע",
                      on_click=_set_status, args=(t["id"], "DONE", "בוצע 🎉"))
        else:
            row.button("↩ החזר", key=f"{k}-re",
                      on_click=_set_status, args=(t["id"], "TO DO"))
        _task_editor(row, t, slots, k)
        row.button("🗑", key=f"ib-rm-{k}", help="מחיקה",
                  on_click=dm.delete_task, args=(t["id"],))



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
    by_due = lambda t: str(t.get("due_date") or "9999")
    all_tasks = [t for ph in progress["phases"] for t in ph["tasks"]]
    done = [t for t in all_tasks if t["status"] == "DONE"]

    # No pinned «overdue» block: the five groups below ARE the board, and each
    # folded phase declares its own lateness in its header.
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
    # the write is the submit's callback: the one fragment run that follows
    # shows the card and empties the field — `write(); st.rerun()` restarted
    # the whole app for it
    with st.form(f"addtask-{mid}", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        c1.text_input("משימה חדשה", key=f"newtask-{mid}")
        c2.selectbox("קטגוריה", ["(אוטומטי)"] + list(dm.TASK_CATEGORIES),
                     key=f"newtask-cat-{mid}")
        st.form_submit_button("➕ הוסף משימה", on_click=_add_task_clicked, args=(mid,))

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
        "דרגו רק מקטעים שהייתם בהם — מקטע בלי כוכבים לא נשמר. "
        "שליחה גם סוגרת את משימת המשוב שלך."
    )
    evening = _parse_date((m or {}).get("gregorian_date"))
    if evening and evening > _date_cls.today():
        # nothing to rate before the night — and no feedback read either
        # (one round-trip on every cold workfile of an upcoming evening)
        _empty("המשוב נפתח ביום הערב.", "אז אפשר לדרג כל מקטע ולכתוב מה עבד.")
        existing, my_titles = None, set()
    else:
        existing = dm.get_feedback_for_mishmar(mid)
        my_titles = {f.get("lesson_title") for f in existing
                     if f.get("student_id") == st.session_state.student_id}

    if existing is None:
        pass
    elif not lessons:
        _empty("אין עדיין מבנה ערב.", "המשוב ייפתח כשיהיו מקטעים.")
    else:
        with st.form(f"slot-feedback-{mid}"):
            entries = []
            fb_names = _slot_names(lessons)
            for l in lessons:
                # one naming for the whole app — and a UNIQUE one: two rounds of
                # חבורות both called «חבורות» made the second unratable, because
                # `my_titles` is keyed by this very string
                name = fb_names.get(l["id"], "מקטע")
                st.markdown(
                    f"**{_clean(name)}**"
                    + (f" · 🎤 {_clean(l['speaker_name'])}" if l.get("speaker_name") else "")
                    + (" · ✅ כבר נשלח" if name in my_titles else ""),
                    unsafe_allow_html=True)
                # one flex row: the stars at their own width, the text taking
                # the rest — two columns in a half-width panel overlapped
                fr = st.container(horizontal=True, wrap=True, gap="small",
                                  vertical_alignment="center")
                fr.feedback("stars", key=f"fb-r-{l['id']}")
                fr.text_input("התייחסות", key=f"fb-w-{l['id']}", width="stretch",
                              label_visibility="collapsed",
                              placeholder="התייחסות — מה עבד, מה פחות")
                entries.append((l["id"], name, l.get("speaker_name")))
            st.form_submit_button(
                "💾 שמור משוב על הערב", type="primary",
                on_click=_save_feedback_clicked,
                args=(mid, entries, my_titles,
                      [t["id"] for t in tasks
                       if "משוב" in t["task_description"] and t["status"] != "DONE"]))

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
            for i, name in enumerate(speakers):
                st.number_input(f"{name} (₪)", min_value=0.0, step=50.0,
                                key=f"pay-{mid}-{i}")
            if not speakers:
                st.caption("לא רשומים מרצים במבנה הערב.")
            st.text_input("מרצה נוסף שלא מופיע למעלה", key=f"bud-extra-name-{mid}")
            st.number_input("תשלום למרצה הנוסף (₪)", min_value=0.0, step=50.0,
                            key=f"bud-extra-amt-{mid}")
            st.number_input("כיבוד (₪)", min_value=0.0, step=10.0, key=f"bud-refr-{mid}")
            st.number_input("הוצאות אחרות (₪)", min_value=0.0, step=10.0,
                            key=f"bud-other-{mid}")
            st.form_submit_button("שמור סיכום תקציב", on_click=_save_budget_clicked,
                                  args=(mid, speakers))
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
    # the same cached read as the trainee home and the dashboard — get_partners
    # was two more round-trips (assignments + students) for the same two names
    partners = dm.get_owners_by_mishmar().get(mid, [])

    # --- the Mishmar's identity card: who, when, where it stands ---
    with st.container(border=True, key=f"card-wf-{mid}"):
        chips = [_countdown_chip(m)]
        if m.get("mishmar_type"):
            chips.append(_chip(m["mishmar_type"], "gold"))
        if partners:
            chips.append(_chip("👥 " + " · ".join(partners), "blue"))
        title = _clean(m.get("topic") or "") or "<span style='color:#5c6577'>עדיין בלי נושא</span>"
        st.markdown(
            f"<div style='display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap'>"
            f"<span style='font-size:1.35rem;font-weight:800'>🕯️ {title}</span>"
            f"<span style='color:#5c6577'>משמר #{m['id']:02d} · {m['gregorian_date']} · "
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
    # a door pressed on this screen reruns only this fragment, so the landing
    # scroll has to be issued from inside it; on a full run main() finds the
    # request already consumed and does nothing
    _scroll_after_nav()




def _my_mishmarim() -> list[dict]:
    if st.session_state.role == "admin":
        return dm.get_all_mishmarim()
    return dm.get_mishmarim_for_student(st.session_state.student_id)



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
            f"<div style='color:#5c6577;font-size:.8rem'>"
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
        # the Streamlit version too: RTL_CSS is measured against one bundle, and
        # a drift on Cloud (1.64 changed the radio DOM) must be visible from a phone
        st.caption(f"גרסה: {build_stamp()} · Streamlit {st.__version__}")
        # a callback: logout runs before the page renders, so one run draws
        # the login screen — `if button: logout(); st.rerun()` drew it twice
        st.button("התנתק", width="stretch", on_click=logout)


def _scroll_after_nav() -> None:
    """One 0-height component on the run that lands a deep link — nothing on
    any other run. The script runs in the component's iframe and reaches the
    app through `window.parent`: to the focused slot card when the workfile
    resolved one, otherwise to the top of the page."""
    if not st.session_state.pop("_scroll_req", False):
        return
    target = st.session_state.pop("_scroll_target_lesson", None)
    sel = f".st-key-card-l-{int(target)}" if target else ""
    import streamlit.components.v1 as components
    components.html(
        "<script>setTimeout(function(){"
        "var d=window.parent.document;"
        f"var el={'d.querySelector(' + repr(sel) + ')' if sel else 'null'};"
        "if(el){el.scrollIntoView({block:'start'});}"
        "else{var m=d.querySelector('[data-testid=\"stMain\"]');"
        "if(m){m.scrollTo(0,0);} window.parent.scrollTo(0,0);}"
        "},60);</script>", height=0)


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
        _scroll_after_nav()
        return

    chat_open = st.session_state.setdefault("chat_open", True)
    if chat_open:
        main_col, chat_col = st.columns([2.4, 1.1], gap="medium")
    else:
        main_col, chat_col = st.columns([14, 1], gap="small")

    with main_col:
        _route_main()
        _scroll_after_nav()
    with chat_col:
        if chat_open:
            from chat_panel import render_chat_panel
            render_chat_panel(_my_mishmarim())
        else:
            st.button("💬", key="chat_reopen", help="פתח את שותף הבנייה",
                      on_click=_set_state, args=("chat_open", True))


if __name__ == "__main__":
    main()
