---
paths:
  - "app.py"
---

# Streamlit UI — RTL, reruns, and the design system

**`app.py` renders only** — all data access through `data_manager`. **The UI is phase-driven:** `dm.mishmar_progress()` derives the 4-phase build state, and every screen shows the current phase first. The student home shows ONLY the current phase's tasks (progressive disclosure — 1 card on day one, not 40); the workfile tasks tab is an accordion opened on the current phase. The chat is a global panel beside every page, not a page; a completed chat turn ends with `st.rerun()` so writes appear on the screen the trainee is looking at.

## Navigation — deep links are STAGED

`_goto(nav, mishmar_id, section, lesson_focus)` deep-links any screen/section. **Writing a widget's session key after that widget was drawn in the same run raises StreamlitAPIException** — and the sidebar nav always draws before any button — so `_goto` parks the request under `_goto_req` and `_apply_goto()` lands it at the top of `main()` before a single widget exists. The workfile uses a keyed `wf_section` radio (constants `WF_SECTIONS`) because `st.tabs` cannot be selected programmatically; `wf_focus_lesson` accepts the sentinel `"first_open_speaker"`.

**Editors are session-state toggles, not expanders** (`editing_lesson`, `editing_task`): expanders remember their open state client-side, so a form inside one never collapses after saving.

## RTL — no native mode; `direction: rtl` is injected CSS

- `st.columns` **does** mirror under RTL: declaring `[main, chat]` renders main on the RIGHT. Declaring `[TO DO, IN PROGRESS, DONE]` puts TO DO on the right — correct Hebrew reading order.
- `st.dataframe` **does NOT** mirror. Columns lay out left-to-right in insertion order, so dict keys are written in reverse to put the first column on the right.
- The sidebar lands on the RIGHT under the RTL CSS — desired for Hebrew.
- Anything inside a raw-HTML block needs `html.escape` plus markdown stripping (`_clean()`), or backticks and `**` render literally.
- Never start a Hebrew title with a leading digit (bidi misplaces it — "כל 21 המשמרים", not "21 המשמרים").

## The design system (config.toml theme + one injected CSS layer)

- **Base colors live in `.streamlit/config.toml`** (Ein-Prat brand: navy `#1d3e7d` primary on parchment `#f2eee3`) so Streamlit's own primitives — primary buttons, progress bars, focus rings — follow without CSS fights. The CSS layer adds Rubik headings / Assistant body, a 4/8px spacing scale (`--sp-1..6`), hairline card borders instead of shadows, and ghost secondary buttons.
- Fonts load with `!important` — **but Streamlit's icons are Material ligature text**: without re-exempting `[data-testid="stIconMaterial"]` back to `Material Symbols Rounded`, every expander arrow renders as the literal word `keyboard_arrow_down`.
- **Headings carry a navy accent bar instead of emojis — as a physical `border-right`, never a `::before`**: Streamlit headings are flex containers, and an inline pseudo-box drifts to the line's END under RTL (three attempts to learn this). Emojis live only in nav labels, chips, stepper dots, and true icon buttons.
- **The sidebar collapse fix must stay**: Streamlit's collapse animation translates LEFT while RTL holds the panel RIGHT, leaving a 1px strip of letter-stacked nav mid-screen — content is hidden the moment `aria-expanded="false"`. This build has NO native sidebar drag-resize (no handle in the DOM); don't promise it.
- `build_stamp()` shows the deployed short SHA + commit time in the sidebar — the answer to "did the deploy update?".
- Card primitive = `st.container(border=True)` (styled white/rounded/shadow globally). Tags = `.chip .chip-{red,yellow,green,gray,gold,blue}`. Phases = `.stepper/.step/.step-bar`. Chat bubbles style `[data-testid="stChatMessage"]`; avatars hidden via `[data-testid^="stChatMessageAvatar"]`.
- The sidebar nav is `st.radio` restyled: the label IS the card; the radio mark is drawn twice in the DOM (hidden input wrapper `label > span:first-child` AND a 16px circle at `label > div > div > div:first-child`) — both must stay hidden.
- No data dumps: prefer cards/grids/steppers over giant tables; long grids fold into expanders (open only when nothing urgent).

## Reruns and cost

- **Streamlit reruns the whole script on every interaction.** Anything expensive or side-effecting sits behind an explicit button and is cached in `session_state` — calling it at render time re-fires it on every unrelated click (this shipped a live bug: `verify_speaker` firing per rerun).
- **List views load their rows in one or two queries and group in Python.** A query per row was 47 HTTPS round-trips per rerun on the speaker index — the whole reason it felt slow. See `dm.get_all_tasks()`, `dm.get_all_outreach()`.
- The chat's live history holds API content *blocks*; a renderer that only displays `str` silently drops every assistant reply — use `_message_text()`.

## Dates

`mishmarim.gregorian_date` is **TEXT in d.m.Y** (`15.10.2026`), by repo convention; `tasks.due_date` is a real DATE (ISO). `_parse_date()` handles both — an ISO-only parser silently kills every countdown chip. Display through `_fmt_date()`. Hebrew dates via `pyluach` (`GregorianDate(...).to_heb().hebrew_date_string()`).

## Auth modes

No `[auth]` in secrets → name-only login, development only. `[auth]` present → Google OIDC **and the name box is removed entirely** — leaving it would keep the "type Uri" bypass open beside real authentication.

## Verifying the UI actually renders

`curl` proves nothing — Streamlit executes the script only when a browser session connects. Run headless and drive with the pre-installed Chromium (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `--no-sandbox`). **Streamlit renders tracebacks into the DOM** — check `inner_text` for "Traceback"/"AttributeError", a `pageerror` listener won't catch them. `st.dataframe` draws to canvas, so its cells never appear in `inner_text`. A running Streamlit process caches imported modules — after editing `data_manager.py`, restart the process, or you are testing stale code.

More probe traps that produced false test results here: **input placeholders never appear in `inner_text`** — assert with element locators, not body text; `st.pills` renders as `[data-testid="stButtonGroup"]`; and **kill test Streamlit processes only by matching `/proc/<pid>/exe` to python** — `pkill -f`/cmdline matching kills your own shell, whose command line contains the pattern (exit 144, repeatedly).
