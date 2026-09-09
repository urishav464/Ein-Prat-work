---
paths:
  - "app.py"
---

# Streamlit UI — RTL, reruns, and the design system

**`app.py` renders only** — all data access through `data_manager`. **The UI is phase-driven:** `dm.mishmar_progress()` derives the 4-phase build state, and every screen shows the current phase first. The student home shows ONLY the current phase's tasks (progressive disclosure — 1 card on day one, not 40); the workfile tasks tab is an accordion opened on the current phase. The chat is a global panel beside every page, not a page; a completed chat turn ends with `st.rerun()` so writes appear on the screen the trainee is looking at.

## Navigation — deep links are STAGED

`_goto(nav, mishmar_id, section, lesson_focus)` deep-links any screen/section. **Writing a widget's session key after that widget was drawn in the same run raises StreamlitAPIException** — and the sidebar nav always draws before any button — so `_goto` parks the request under `_goto_req` and `_apply_goto()` lands it at the top of `main()` before a single widget exists. The workfile uses a keyed `wf_section` radio (constants `WF_SECTIONS`) because `st.tabs` cannot be selected programmatically; `wf_focus_lesson` accepts a lesson id or the sentinel `"first_open_speaker"`; `task_focus=<task id>` (staged as `wf_focus_task`) lets the instructor's dashboard open a task's slot WITHOUT loading 21 timelines — the landing page resolves it (`tasks.lesson_id`, else `suggest_lesson_for_task`) and highlights that slot with «⤴ כאן סוגרים את המשימה». The tasks board pins an always-open «⏰ עברו את התאריך המומלץ» group above the phase accordion (spanning `after` and `יום המשמר`, which the accordion routes elsewhere) — a late task can never sit folded inside a shut phase while the dashboard shouts about it.

**Clicks cost one run, not two, and reruns are partial.** Measured with a 150 ms simulated Supabase round-trip: opening a task editor was 2 runs / 16 queries / 2.8 s and a section switch 1.9 s; after the fix, 2–34 ms and zero queries, a ✓ on a task ~400–650 ms with exactly `[update tasks, select v_tasks_full]`. Two rules made it so and must hold: (1) a button that writes or toggles state uses `on_click=` (`_set_status`, `_toggle`, `_set_state`, or the `dm` write itself) — the callback runs BEFORE the run that follows the click, so `write(); st.rerun()` is a duplicate full run; selectboxes and number inputs use `on_change=`. (2) The workfile body under the picker (`_workfile_body`) and the chat panel are `@st.fragment`s — a click inside reruns only them, over cached reads. `_goto` and the chat turn's final rerun are `st.rerun(scope="app")` because they must restart the page from the top. The stale-element dimming users called «the slow animation» is Streamlit's `opacity 1s ease-in 0.5s` on runs longer than half a second — it vanishes when runs are fast; do not hide it with CSS, it is the regression alarm. Harness: a scratch `run_app_perf.py` wraps the shim's `execute` with a counter and `time.sleep(RTT)`; guard the patch with a module flag — the script re-executes per rerun and re-wrapped itself 14 deep the first time.

**The workfile is two columns, not tabs.** Under RTL `st.columns` mirrors, so declaring `[evening, tasks]` puts the evening on the RIGHT (verified: x=626 vs x=80) and Streamlit stacks them on a phone. The evening column is three expanders (`WF_STRUCTURE` / `WF_LOGISTICS` / `WF_AFTER`); the tasks column is the ONLY task board, so `_tasks_tab` now renders every phase including «אחרי» — routing a phase elsewhere would make it disappear. A deep link opens a panel by setting `wf_panel` **and bumping `wf_panel_nonce`**, which is part of the expander's `key`: an expander remembers its open state client-side, so remounting is the only reliable way to force one open. A Mishmar with no topic skips the columns entirely — there is one thing to do and two columns of empty panels would hide it.

**The chat is off behind `CHAT_ENABLED = False`** — panel not rendered, content full width. The panel UI lives in `chat_panel.py`, imported lazily only when the flag is on (moved out of `app.py` so 170 dormant lines stop costing every reader); `chat_agent.py` keeps the tool loop and the `chat_messages` rows stay. The scout behind «חיפוש מרצים» is a separate, button-triggered model call and is unaffected.

**A `st.rerun()` after `form_submit_button` is a duplicate run** — the submit already reruns. It is tolerated only because reads are cached (≈100 ms, 0 queries); do not add new ones, and convert a form to keyed widgets + `on_click` when you touch it.

**Probe trap: a `st.selectbox`'s current value is in `input.value`, not `inner_text`** — reading the element's text shows only the label, which looks exactly like an empty control.

**Editors are session-state toggles, not expanders** (`editing_lesson`, `editing_task`): expanders remember their open state client-side, so a form inside one never collapses after saving.

## RTL — no native mode; `direction: rtl` is injected CSS

- `st.columns` **does** mirror under RTL: declaring `[main, chat]` renders main on the RIGHT. Declaring `[TO DO, IN PROGRESS, DONE]` puts TO DO on the right — correct Hebrew reading order.
- `st.dataframe` **does NOT** mirror. Columns lay out left-to-right in insertion order, so dict keys are written in reverse to put the first column on the right.
- The sidebar lands on the RIGHT under the RTL CSS — desired for Hebrew.
- Anything inside a raw-HTML block needs `html.escape` plus markdown stripping (`_clean()`), or backticks and `**` render literally.
- Never start a Hebrew title with a leading digit (bidi misplaces it — "כל 21 המשמרים", not "21 המשמרים").

## What Streamlit portals to `<body>` never inherits the app's RTL

`st.dialog`, popovers, toasts and the selectbox's dropdown are rendered **outside
`[data-testid="stAppViewContainer"]`** (measured: the dialog's `parentElement` is `BODY`). Every
rule scoped to that container therefore stops at their edge, and they render **LTR**: the slot
editor's title hugged the left, its field pair read «כותרת | משך» left-to-right, and its button
row put «💾 שמור» leftmost with «🗑 מחק מקטע» where the eye lands first. Element- and class-scoped
rules (`h1..h6`, `.stButton button`) still reach inside, which is what made the bug look partial
and survive two design passes. The four portal roots are named explicitly in the base RTL rule —
`stDialog`, `stPopoverBody`, `stToastContainer`, `stSelectboxVirtualDropdown`. **Add any new
portaled primitive to that list**; measure with `!!el.closest('[data-testid=stAppViewContainer]')`,
never by eye.

## The design system (config.toml theme + one injected CSS layer)

- **Base colors live in `.streamlit/config.toml`** (Ein-Prat brand: navy `#1d3e7d` primary on parchment `#f2eee3`) so Streamlit's own primitives — primary buttons, progress bars, focus rings — follow without CSS fights. The CSS layer adds Rubik headings / Assistant body, a 4/8px spacing scale (`--sp-1..6`), hairline card borders instead of shadows, and ghost secondary buttons.
- Fonts load with `!important` — **but Streamlit's icons are Material ligature text**: without re-exempting `[data-testid="stIconMaterial"]` back to `Material Symbols Rounded`, every expander arrow renders as the literal word `keyboard_arrow_down`.
- **Headings carry a navy accent bar instead of emojis — as a physical `border-right`, never a `::before`**: Streamlit headings are flex containers, and an inline pseudo-box drifts to the line's END under RTL (three attempts to learn this). Emojis live only in nav labels, chips, stepper dots, and true icon buttons.
- **The sidebar collapse fix must stay, and it is a `transform: none`, not a `display: none`.** Streamlit 1.62 styles the panel `transform: isCollapsed ? translateX(-<width>px) : none` (bundle `index.*.js`, emotion target `eelgd2m0`) — correct for its native LEFT sidebar, wrong for ours on the RIGHT: it slid ACROSS the content. The CSS kills the transform and lets Streamlit's own 300ms width transition do the collapse (measured: right edge pinned at the viewport, left edge 1200→1500, transform `none` throughout); the content keeps `min-width: 244px` + `overflow: hidden` on the section so it is clipped, not reflowed into stacked letters. The old `[aria-expanded=false] * { display: none }` sledgehammer is gone — reopening via `stExpandSidebarButton` restores 300px.
- **Sidebar drag-resize exists but is unreachable**: the `re-resizable` handle IS in the DOM (`cursor: col-resize`, 8px wide) but Streamlit places it at `right: -6px` — the panel's physical right edge, which under RTL is the viewport edge (measured at x=1498 of 1500). Don't promise it; don't claim it isn't there.
- **Full-width sidebar controls need `align-self: stretch` AND the element container**: the nav radio's `stElementContainer` is sized to its content (137px in a 239px block), and the label's inner wrappers are RTL flex rows that pack RIGHT — so `width: 100%` on the label and `text-align: center` on the `<p>` changed nothing. The rules that work: stretch `stElementContainer`/`stRadio`/`radiogroup`, and `justify-content: center` on the label's inner `div`s (verified: left gap == right gap on all four cards).
- **`st.caption` renders `data-testid="stCaptionContainer"`, NOT `stMarkdownContainer`** (`StreamlitMarkdown.*.js`, chosen by the `isCaption` prop). It must be in the RTL selector list explicitly — until it was, no caption in the app was ever right-aligned.
- `build_stamp()` shows the deployed short SHA + commit time in the sidebar — the answer to "did the deploy update?".
- Card primitive = `st.container(border=True, key="card-…")`. **In Streamlit 1.62 the border lives on the `stVerticalBlock` itself** — `stVerticalBlockBorderWrapper` is gone from the bundle, and the white/rounded/hairline card rule was silently dead for a whole release because it still named it. **`data-test-scroll-behavior` is NOT a card discriminator either**: it sits on width-only, keyed and fragment wrappers too, and a rule anchored on it painted the whole workfile and the metric column white. The card rule is therefore **opt-in by key**: `[class*="st-key-card-"]` (white, hairline, 12px radius, `padding: var(--sp-4)`, inner `gap: var(--sp-2)`); every `st.container(border=True)` that is a card carries a `card-` key, and a bordered container without one is deliberately unstyled. **Audit every `data-testid` in `RTL_CSS` against `streamlit/static/static/js/*.js` after any Streamlit upgrade** (the `design-review` agent does exactly this; zero hits = dead rule). Tags = `.chip .chip-{red,yellow,green,gray,gold,blue}`. Phases = `.stepper/.step/.step-bar`. Chat bubbles style `[data-testid="stChatMessage"]`; avatars hidden via `[data-testid^="stChatMessageAvatar"]`.
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

**Subagent files and hot-reload.** The docs say `.claude/agents/` is watched and a change serves within seconds on the CLI. In this remote/SDK session a diagnostic asked the agent to quote its own instructions and it quoted the PRE-rewrite file — so after editing an agent here, verify with that same diagnostic before trusting a round-trip, and treat a new session as the reliable reload.

## Micro-interactions in use (Streamlit 1.62) and their probe facts

- **Reset is a `@st.dialog`** (`_reset_dialog`), opened from `_reset_panel`'s button with a plain
  `if st.button(...)` — opening a dialog IS a rerun, so `on_click` buys nothing there. Inside the
  dialog `st.rerun()` closes it and restarts the page; this works from within the `_workfile_body`
  fragment. Probe: `[role=dialog]`; the confirm button is disabled until the checkbox is ticked.
- **The search narrates through `st.status`**: `scout_speakers(..., progress=fn)` threads a
  callback down to `search_candidates`, which reports each round; the scout adds a line per
  enriched name and one before curation. `status.update(label=…)` + one `st.empty()` list. A
  callback that raises would abort the search — keep `_stage` trivial.
- **Per-slot ratings are `st.feedback("stars")`**: returns `0–4` or `None`; the form maps to
  `1–5` and **skips unrated slots** (an unrated slot is not a 4). Probe: `[data-testid=stFeedback]`
  → `[data-testid=stFeedbackButton]`; the icons' `inner_text` is the literal word `star`.
- **The angle picker is `st.segmented_control`** with short labels (`LESSON_ANGLES`) and the
  explanations in `help` (`ANGLE_HINTS`). Probe: `[data-testid=stButtonGroup]`; it returns `None`
  when nothing is selected, so the code falls back to «בלי המלצה».
- **Project hooks**: `.claude/settings.json` runs `.claude/hooks/guard-bash.sh` before every Bash
  call. It matches the secrets file as a *path token* (start / whitespace / quote / `=` / redirect /
  paren before it), so writing docs that mention the file in backticks passes; a quote-preceded
  prose mention is blocked on purpose. The push check needs an actual invocation (`git push` followed by whitespace) and inspects only that line's arguments, so a commit message describing the rule still commits. Tests live outside the repo (`/tmp/pwtest/hooktest.py`),
  because the command strings they feed would trip the hook if typed into a live Bash call.

## Layout that adapts without a rerun (the flex rule)

- **`st.columns` is for forms only.** It stacks below ~640px and squeezes above it — on a phone a
  task card's four controls became four lines. A row of controls is
  `st.container(horizontal=True, wrap=False, gap="small", vertical_alignment="center")` and the
  widgets are called on that container (`row.button(...)`); text takes `width="stretch"`, inputs a
  px width. The browser lays it out; nothing reruns on resize.
- **Grids are wrapping flex rows of fixed-width cards**: `st.container(horizontal=True, wrap=True)`
  around `st.container(border=True, width=300)` — the dashboard's `_mishmar_card`s and its overdue
  cards wrap 4 / 2 / 1 across. Below 740px the CSS forces those cards to 100% (keyed containers
  `pipeline-grid` / `pipeline-past` → `.st-key-…`).
- **The two workfile columns are the one media query**: `st.container(key="wf-cols").columns(...)`
  and `@media (max-width: 1100px) .st-key-wf-cols …` stacks them, evening first.
- **The dashboard card's title is a tertiary button** inside a plain `if` — a deep link is a rerun
  anyway (`_goto`), so `on_click` buys nothing there. The trainee's «שאר המשמרים שלי» mini-cards
  (`_mini_mishmar_card`, key `mc-…`) open the workfile the same way; `[class*="st-key-pc-"] button,
  [class*="st-key-mc-"] button { justify-content: flex-end; text-align: right }` keeps a
  `width="stretch"` label at the right edge with the chips under RTL instead of centred.
- The pinned «עברו את התאריך המומלץ» block is gone from the workfile board by request: the five
  groups (four phases + יום המשמר) are the board, and a folded phase declares its own lateness in
  its header badge.

## The evening panel after the slot↔task round

- **A חבורות slot renders `_chavurot_rows`, not `_candidate_rows`.** It is a LIST of presenters,
  not a competition: no «סגרנו», each row carries a room picker (`dm.CHAVUROT_ROOMS`) and its own
  source-sheet field, and a room used twice shows ⚠️ on both rows.
- **«📎 דף מקורות» opens the slot editor** (`_set_state("editing_lesson", …)`), where the uploader
  and the link field live. It used to create a task and `_goto` back to the same panel — which is
  why it read as a dead button.
- **The invitation task is done-or-not**: a task whose category is `הזמנה` shows no «פתח» in the
  workfile card and no «▶ בתהליך» on the dashboard card. It is designed and sent outside the app.
- **The rooms panel in לוגיסטיקה is derived**, not typed: it reads the חבורות presenters. The
  candidates are fetched ONCE in `_workfile_columns` and passed to both the structure panel and the
  rooms panel — calling `get_lesson_speakers` twice with different argument lists misses the memo
  and costs a second query (measured: 10 → 9 on a cold workfile).
- **Cards fill their row**: `flex: 1 1 240px` on `.st-key-pipeline-grid` / `.st-key-overdue-grid`
  children, capped (`max-width`) only above 1101px so a lone card does not sit in a stripe, and
  forced to 100% below 740px. Measured 4 / 1 / 1 across at 1500 / 900 / 390 with no h-overflow.
- **Closing a speaker happens next to the candidate** («✅ סגור מרצה» on each candidate row); there
  is no slot-level «סגירת מרצה» button — it only ever created a task the sync had already made,
  and a pair typed a name into the add form and pressed it. The add form is one flex row under the
  list (the old `st.columns` split truncated its submit to «+ מו…»). The חבורות add form takes a
  room (default בית מדרש), not a phone.
- **A slot's open tasks are chips** (`st.container(border=True, width="content", key="ltc-…")`
  inside a wrapping flex row, ✓ right after the text as an `ib-lt-` box, lateness as red text).
  The keyed class AND the border/padding both sit on the inner `stVerticalBlock`, so the trim is
  `[class*="st-key-ltc-"] { padding: 2px 8px }` on the block itself — the earlier `:has()` rule
  on the `stLayoutWrapper` trimmed nothing and left every chip 63px tall. Measured: 32px tall,
  two per row in the evening column at 1500.
- **Feedback stars + text are one flex row** (`fr.feedback` + `fr.text_input(width="stretch")`);
  two `st.columns` in the half-width panel overlapped.

## Design pass (the Twitter-prompt comparison) — what was taken, what was not

- **Taken**: metric tiles (`[data-testid="stMetric"]` styled with the card grammar); a reading
  width (`stMainBlockContainer` max 1320px); solid muted ink `#5c6577` for `.card-meta`, `.step`
  and captions instead of `opacity` (0.65 of the text colour on parchment measured 4.0:1, under
  4.5:1) — **and the same for inline `style='opacity:…'` on raw HTML**: seven such spans survived
  the first pass at .5–.7 (2.78:1 to 4.72:1 composited) and are now `color:#5c6577` too; the
  struck-through «done» logistics line keeps the strike and drops the dimming; icon-only buttons (✏️ 🗑 ✕ ✓) were briefly `type="tertiary"` and then, by decision
  («כולם בקופסאות קטנות ואחידות»), became **uniform 32×32 boxes**: every icon-only button has a
  key prefixed `ib-` (`ib-dn-` ✓ · `ib-ed-` ✏️ · `ib-rm-`/`ib-rmc-`/`ib-rmch-` 🗑 · `ib-brx-`/`ib-lgx-`
  ✕ · `ib-lt-` chip ✓) and one rule `[class*="st-key-ib-"] button { width/height: 2rem; padding: 0;
  border: 1px solid var(--line) }`, navy border for `ib-dn-`/`ib-lt-` (the affirmative one); one voice for «nothing yet» via `_empty(text, hint)` (dashed hairline,
  muted), replacing the mix of `st.info` / `st.caption`.
- **Fields must be bounded on both surfaces**: `secondaryBackgroundColor = #ffffff` makes every
  input wrapper white with a **white 1px border**, invisible on a white card. The field rule
  (`stTextInputRootElement`, `stNumberInputContainer`, `stTextArea textarea`, the selectbox's
  control, `stFileUploaderDropzone`) paints `#fbfaf6` with a `var(--line)` border, 8px radius.
- **The selectbox is react-aria in 1.62, not BaseWeb.** `[data-baseweb="select"]` matches **zero
  nodes** (measured); the control is `[data-testid="stSelectbox"] div[role="group"]` and the value
  sits in its `input`. Two rules named the BaseWeb selector — the field background and the RTL
  rule — so every dropdown in the app stayed white-on-white while the text inputs went cream.
  **A dead-selector audit that only checks `data-testid` misses this**: `data-baseweb` and
  `role` selectors need checking too.
- **Streamlit's `stMarkdownContainer` carries `margin-bottom: -16px`** to cancel the bottom margin
  of a trailing `<p>`. Our raw-HTML blocks end in a `<div>`, so the negative margin ate 16px of
  real content: the overdue card's action row started **11px above the end of its `.card-meta`
  line** and drew on top of it. The rule
  `[data-testid="stMarkdownContainer"]:has(> :last-child:not(p)) { margin-bottom: 0 }` gives the
  space back wherever the last child is not a paragraph, and leaves Streamlit's own text alone.
- **Equal heights are opt-in, per row.** `st.columns` leaves its row `align-items: start`, so the
  speaker index's three cards ended at three different heights (93 / 122 / 173px) and the «פרטים»
  doors never lined up. Each row is wrapped in a keyed container (`sp-row-{i}`); the CSS stretches
  the row, gives the column's block `height: 100%`, makes the card's `stLayoutWrapper` a growing
  flex item (`flex: 1 1 auto` — it is a flex ITEM in a column and stays content-tall otherwise),
  and pushes the card's last child down with `margin-top: auto`. Measured after: 189 / 189 / 189.
  The four dashboard metric tiles use the same grammar (`metric-row`), all at `width=190`; the
  fourth tile's explanatory caption moved OUT of the row, where it has room to be a sentence.
- **Gaps are on the scale, not Streamlit's default**: `stHorizontalBlock { gap: var(--sp-2) }`
  (rows of controls were 16px apart) and the card's inner gap is 8px through the `card-` rule.
- **Chips pad the keyed block, not its wrapper**: `[class*="st-key-ltc-"] { padding: 2px 8px }`
  — the earlier `:has()` rule padded the `stLayoutWrapper`, so each chip kept the bordered block's
  15px padding and stood 63px tall, one per row. Measured after: 32px tall, two per row at 1500.
- **Not taken, by decision**: any palette change (navy/parchment is the brand), Inter/Geist
  (Hebrew: Rubik/Assistant), dark mode (locked light), sticky headers, third-party component
  libraries. A design finding that proposes any of these is out of scope.
- `.claude/agents/design-review.md` audits screens against this section by measuring: dead
  selectors against the installed bundle, WCAG contrast of the colours actually set, off-scale
  spacing, RTL misses, button noise. Read-only; JSON findings with a measured value each.

## Editors are dialogs; every click has a known cost

- **Task and slot editors are `@st.dialog`s** (`_task_edit_dialog`, `_lesson_edit_dialog`), opened
  from ✏️ (and «📎 דף מקורות») with a plain `if` — opening a dialog is a rerun by nature. The
  `editing_task` / `editing_lesson` session keys are gone; `st.rerun()` at the end of the dialog is
  what closes it. Literal `session_state` keys: 14.
- **`scripts/rerun_audit.py` is the click-cost contract**: one row per widget site — `callback`
  (on_click/on_change), `fragment`, `page`, `nav` (body calls `_goto`/`logout`/opens a dialog),
  `form-submit`, `rerun` (legitimate only after a submit, to close a dialog, or for nav/auth).
  Exit 1 on a `page` site or a `DOUBLE RUN`. The `rerun-audit` agent runs it and, on request,
  measures representative clicks on the harness. The search screen's «אמת» / «הוסף למאגר» are the
  sanctioned `page` sites: the screen is not a fragment and each runs a long verify — noted, not
  hidden.
- **Dashboard ✓ was measured and left as a page rerun** (~400 ms, 2 queries): the pipeline's
  «n באיחור» chips and the metrics depend on the same write, so a fragment would need a page-scope
  rerun anyway — no gain to take.
- **Focus is visible**: a 2px navy `outline` on `:focus-visible` for buttons, inputs, selects and
  the nav card (`label:has(input:focus-visible)` — its radio input is hidden). `help=` renders a
  tooltip, NOT an `aria-label`; Streamlit gives no way to name an icon button in Hebrew for a
  screen reader — a known limitation, not something `help=` covers.
- **`.claude/rules/streamlit-dom.md` is generated** (`scripts/streamlit_dom_context.py`) from the
  installed bundle: every `data-testid` + the measured structural facts. Regenerate after any
  Streamlit upgrade; `design-review` and `app-reviewer` read it instead of remembering.
- Sanctioned off-scale values: the sidebar nav card padding (`0.6rem 0.9rem`) and the phone
  button paddings (`.25rem .55rem`) are deliberate fine-tuning — an audit may list them, not fail
  on them.
- `[data-testid="stButtonGroup"]` (`segmented_control`, `st.pills`) labels through
  `DynamicButtonLabel`, not markdown — it needs its own RTL rule (added), like `stCaptionContainer`.
