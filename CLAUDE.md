# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The toolkit for Midreshet Ein Prat's **Mishmar** programme — Thursday-night study seminars, 20:30–02:00. Two halves that live together:

1. **A Streamlit web app** that 10 trainees and one instructor work against, scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim, built by pairs.
2. **A Hebrew content repository** — the generator prompt, work-file templates, a cross-year speaker database, invitation assets. "Building" there means composing Hebrew documents and rendering HTML/PPTX to images for visual QA.

The app is not a task board with a chatbot bolted on. The generator prompt *is* the chat's system prompt, loaded from disk, and the chat's tools read and write the same rows the UI shows.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # see the note below — do not skip
pip install -r requirements.txt
streamlit run app.py
```

**Install into a venv.** `Authlib` (Google sign-in) pulls `cryptography`, and on Debian/Ubuntu system Python that fails with *"Cannot uninstall cryptography, RECORD file not found"*, which aborts the whole `pip install` and — in a `&&` chain — never reaches `streamlit run`. Escape hatch without a venv: `pip install --ignore-installed cryptography Authlib`.

**There is no local database and no `.env`.** The app needs `SUPABASE_URL`, `SUPABASE_KEY` and `ANTHROPIC_API_KEY` in `.streamlit/secrets.toml` (locally) or Streamlit Secrets (deployed). Full setup, including the Google OAuth redirect URI: **`DEPLOY.md`**.

## Application architecture

**`data_manager.py` is the only data seam.** Nothing else talks to storage. Storage is **Supabase**, over its REST API.

**The two-file split is forced by the platform: the REST API reads and writes rows but cannot CREATE TABLE.** Structure lives in `supabase_schema.sql`, pasted once into the Supabase SQL Editor. A schema change means editing that file *and* telling the user to re-run it — it is idempotent, so re-running is safe.

**Anything needing a join or an aggregate is a VIEW in that file**, because PostgREST cannot express one: `v_speaker_status`, `v_mishmar_budget`, `v_overdue_tasks`, `v_student_progress`, `v_outreach_full`, `v_tasks_full`. Python reads views and never assembles a join itself.

**Twelve tables.** `mishmarim`, `students`, `assignments`, `tasks`, `budget`, `speakers`, `speaker_outreach`, `lessons`, `feedback`, `chat_messages`, `search_cache`, `app_meta`.

Decisions that are not obvious from the DDL:

- **RLS is on for every table with no policies at all.** `anon` and `authenticated` get nothing; `service_role` has `BYPASSRLS` and is what the app uses. **This makes the key type load-bearing — an anon key produces a permission error, not an empty result.** `storage_ready()` detects that case specifically and says so, because a wrong key and an uninstalled schema look identical from the client but need opposite fixes. **Every view must carry `WITH (security_invoker = true)`** so it respects the caller's permissions rather than the creator's — a new view without it is flagged CRITICAL by Supabase's linter, and rightly so.
- **Outreach is a log, not a field.** `speaker_outreach` records each approach; current status is derived by `v_speaker_status` from the newest row. **`record_outreach()` is the only writer** — `upsert_lesson()` delegates to it rather than setting `speaker_status` itself. Before this, closing a speaker wrote only to that one Mishmar's lesson row, so the shared index never learned and the next pair got a stale answer, defeating the single mechanism that stops two pairs approaching the same person.
- **A title is not part of a name.** `speakers.title` holds ד״ר / הרב / פרופ׳. `split_title()` separates on the way in, `display_name()` rejoins for display.
- **`name_norm` is a generated column, not Python.** A PostgREST filter cannot call `REPLACE`. Without the Hebrew-gershayim folding, a trainee typing `ד"ר` both misses `ד״ר` *and* causes a second row to be created for the same human.
- **`resolve_speaker()` raises `AmbiguousSpeaker` rather than guessing** when several rows share a name. Callers must ask which person is meant.
- **Task deadlines are derived, never typed.** `classify_task()` maps the text to a category and `compute_due_date()` offsets from the Mishmar date (topic −21d, speakers −14d, invitation/refreshments/decoration −7d). Two ordering rules in `_CATEGORY_RULES` carry weight: `אחרי` is tested before `מרצים` so "עדכון מאגר המרצים" is not dated two weeks early, and `לוגיסטיקה` before `תוכן` so "סידור חדרי חבורות" is not read as content.
- **`lessons` is deliberately not four rows.** `slot_order` is 1..N and `lesson_role` is free text: the 2025-26 archive holds a ceremony plus two lessons, and a song circle.
- **`tasks.student_id` is nullable** — `NULL` means the task belongs to the Mishmar and therefore to both owners in the pair, which is how the lists were actually written.
- **`budget_used` is a view**, never a stored column.
- **Seeding does not archive `students_tasks.md`.** The checkout is rebuilt from git on every deploy, so a rename would not survive and would break the next deploy's seed. An `app_meta` flag guards it instead.

**`chat_agent.py`** — Sonnet 5, streaming, ten tools. **Every writing tool is bound to the Mishmar in the session context; the model never supplies a `mishmar_id`**, so a trainee's chat cannot reach another pair's Mishmar even if the conversation asks. The ~17.5k-char stable half of the system prompt (role + generator prompt + work-file template) carries the cache breakpoint; live context sits after it.

**A turn re-sends its whole history on every API call, and a tool-using turn makes several — the two multiply.** Four ceilings keep the cost of a turn flat instead of linear in thread length; removing any one restores the growth:

- `MAX_TOOL_ROUNDS = 3`, and the **last round sets `tool_choice: none`** so a trainee always ends with an answer rather than "I ran out of steps".
- `trim_history()` sends a trailing window, not the thread. **It may only cut on a plain user turn** — a `tool_result` whose `tool_use` was trimmed away is a 400 from the API, not a cheaper request, and that is how this optimisation usually breaks. The window never opens later than the current question, so the turn in flight goes whole, thinking blocks included. The caller keeps everything; only what is *sent* is trimmed.
- `compact_tool_output()` caps a result at 1500 chars **structurally — fewer rows, shorter strings — never by cutting the JSON text**, which would spend the tokens and lose the answer too.
- `search_speaker_index` projects columns and caps rows *before* enriching. It used to `select("*")` and enrich every match with two more Supabase round-trips: a one-letter topic — which is what a model sends when it widens a search — matched 46 rows, cost 92 round-trips, and produced a 20k-char result that was then re-sent on every later round.

**The 44-name roster is stripped from the generator prompt at load** (`_drop_speaker_roster`), because it is a dated snapshot of what `search_speaker_index` reads live — paying ~3.2k chars on every request to hand the model *staler* data than its own tool returns. The file keeps it: it is still pasted whole into external chat windows, which have no tools. The legend, the ה1–ה7 collision flags and the institution list around it are not duplicated anywhere and must survive the cut.

**`speaker_search.py`** — two paths, and the distinction is the whole design. `search_candidates()` **discovers**: broad queries including `site:ac.il` whose results are mined for names by `extract_names()`. `verify_speaker()` **verifies** one name against the `⚠️ לאמת` checklist. Discovery is what surfaces a lecturer no model has heard of, so it is not garnish on verification. Every network call funnels through one `_fetch()` so the cache, throttle and cooldown cannot be bypassed.

**`archive.py`** — cross-year memory. Two traps it already hit: this season's folders are unfilled templates and must not be searched as history, and every work-file inherits a status legend containing `ממתין לתשובה`, so an unfiltered search for a Mishmar on תשובה matched all 21 templates. Strip boilerplate before matching.

**`app.py`** renders only. **The UI is phase-driven:** `dm.mishmar_progress()` derives a 4-phase build state (נושא → מרצים ותוכן → לוגיסטיקה → אחרי) from task categories, and every screen shows the current phase first — the student home shows ONLY the current phase's tasks, the workfile is an accordion opened on it. The chat is a global panel beside every page, not a page. List views (admin pipeline, speaker index) load their rows in one or two queries and group in Python — a query per row was 47 HTTPS round-trips per rerun and the reason the speaker index felt slow. `mishmarim.gregorian_date` is TEXT in d.m.Y (`15.10.2026`), not a DATE — a date parser that only reads ISO silently breaks every countdown. Login has two modes: no `[auth]` in secrets → name-only, for development; `[auth]` present → Google OIDC **and the name box is removed entirely**, since leaving it would keep the "type Uri" bypass open beside real authentication.

## Verifying changes

**There is no test suite, and no live Supabase is reachable from a sandbox.** The substitute is real and worth the setup — run the schema against a local PostgreSQL 16 (the major version Supabase runs) and drive `data_manager` through a PostgREST-shaped shim, so query construction is genuinely exercised rather than mocked:

```bash
apt-get install -y postgresql            # PG16
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /tmp/pgd -A trust"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgd -o '-p 5433 -k /tmp' start"
```

Create roles mirroring Supabase (`anon`, `authenticated`, `service_role` with `BYPASSRLS`) before applying the schema, or the `REVOKE` statements fail and the RLS behaviour cannot be checked. A shim that turns `.select().eq().execute()` into SQL is ~150 lines; **have it `SET ROLE service_role`**, because connecting as the owner bypasses RLS and makes the test meaningless.

To verify the UI actually renders, run headless and drive it with the pre-installed Chromium — Streamlit only executes the script when a browser session connects, so `curl` returns the shell HTML and proves nothing:

```bash
streamlit run app.py --server.headless true --server.port 8555 &
# Playwright: executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"]
```

**Streamlit renders Python tracebacks into the DOM**, not as JS errors — check `inner_text` for "Traceback"/"AttributeError", because a `pageerror` listener will not catch them. And `st.dataframe` draws to a canvas, so its cell contents never appear in `inner_text`; verify that data by querying the layer directly.

**Not verifiable here:** live web search (`ddgs` gets `403` on the proxy CONNECT — the whole sandbox is blocked, including Wikipedia), and any real Anthropic API call. Test the failure paths and the caching; leave live runs to the user.

## Conventions

- **Language:** file and folder names in English, all content in Hebrew.
- **Dates:** always Hebrew + Gregorian together (`כ״א אלול תשפ״ו | 3.9.2026`).
- **Never invent content.** Topics, speakers, texts, dates, contact details, budget figures. Unknown stays `TBD`. Contact details are never scraped from search results — store the institutional URL where a human can find them.
- **Never invent a speaker — but never narrow to the database either.** It is a growing index, not the candidate set. Every proposed name needs a source; a name from model knowledge carries `⚠️ לאמת` plus the checklist. Watch the dead-thinker trap: the generator prompt is full of Spinoza, Levinas, Kafka, Agnon — those are texts to study, not people to invite.
- **Flag inconsistencies, don't silently fix them.** Flag ה7 (the ambiguous "אורי") was closed only because Uri identified himself; the principle stands, and `AmbiguousSpeaker` enforces it in code. A live example: three documents word the outreach ladder differently (`✅ אישר/לימד` vs `✅ אישר` vs `✅ סגור`) — the code follows the work-file template and the divergence is flagged, not rewritten.
- **Deadlines are "המלצה — לא חוק"**, per the opening deck. A trainee sees a soft nudge and a DONE task never nags; only the instructor dashboard treats a passed date as actionable.
- **Budget is tracking, not enforcement.** ₪500 per Mishmar is an average covering speakers *and* refreshments. Overrun draws from the season-wide line; there is deliberately no ceiling.
- **Git:** all development happens on `claude/mishmer-generator-setup-h5gxqx`. **`main` is empty** — Streamlit Cloud must deploy from the working branch.

## Repository structure

```
app.py                 # Streamlit: login, dashboard, workfile, chat, speaker index, search
data_manager.py        # the ONLY data seam — Supabase REST, seeding, all queries
chat_agent.py          # Sonnet 5 + 10 tools; generator prompt loaded as system prompt
speaker_search.py      # discovery (mines names from results) + verification
archive.py             # cross-year memory over the 2025-26 work-files and feedback
supabase_schema.sql    # tables, views, RLS — run once in the Supabase SQL Editor
system_rules.md        # operating layer: roles, pedagogy, speaker mandate, budget
students_tasks.md      # seed data seeding reads on first run (213 task lines)

Mishmer-section/
├── generator/mishmar-generator-prompt.md   # the pedagogy + QUALITY BAR + speaker digest
├── templates/mishmar-workfile-template.md  # the REAL per-Mishmar operating format
├── speakers/database.md                    # cross-year seed + paste-block for external chat
├── 2025-26/mishmarim/                      # archive: 5 real work-files, verbatim
└── 2026-27/                                # current season
    ├── schedule.md                         # source of truth: 21 dates, type, responsible pair
    ├── binyat-mishmar-mifgash-peticha.pptx # the deck trainees are taught from
    └── mishmarim/NN-slug/                  # workfile · draft · brief · invitation

Invitations/           # house style, watercolor prompts, past posters
```

**`system_rules.md` is the operating layer** — read it when acting as the programme's assistant rather than as a repo developer. This file guides whoever *builds* the repo; that one guides whoever *operates* the programme.

**The generator prompt describes an idealized 4-lesson Logos→Pathos arc** (Foundation → Conflict → Twist → Soul). Real Mishmarim rarely follow it: some have three lessons, some are ceremonial, some are song circles, and roughly half of a real work-file is logistics — decoration, shopping list, a themed dinner. **The actual operating format is `templates/mishmar-workfile-template.md`**, reverse-engineered from five real documents. Help a student who wants to deviate; never tell them a three-lesson Mishmar is wrong.

## Image workflow (no image generation available)

Claude cannot generate images here, and this cannot be automated away:

1. User names the topic. 2. Claude writes a prompt from `Invitations/prompt/base-prompt.md`. 3. **User generates the image externally and uploads it** — chat-pasted images are not persisted; they must arrive via GitHub upload or `git push`. 4. Claude composes the invitation from the uploaded file.

**Exception:** if the user prefers an existing background from `Invitations/examples/`, skip steps 2–3. Never suggest filters (sharpen, upscale, texture) as a substitute for actually generating watercolor artwork.

## Repeatable techniques used in this repo

**RTL in Streamlit** — no native mode; `direction: rtl` is injected as CSS. Two behaviours differ and both matter:
- `st.columns` **does** mirror under RTL. Declaring `[TO DO, IN PROGRESS, DONE]` renders TO DO on the right — correct Hebrew reading order.
- `st.dataframe` **does not**. Columns lay out left-to-right in insertion order, so declare them in reverse to put the first column on the right.
- Anything inside a raw-HTML block (Kanban cards) needs `html.escape` plus markdown stripping, or backticks and `**` render literally.

**Streamlit reruns the whole script on every interaction.** Anything expensive or side-effecting must sit behind an explicit button and be cached in `session_state` — calling it at render time re-fires it on every unrelated click. This has already caused one live bug (`verify_speaker` firing on every rerun) and one class of invisible bug: the chat's live history holds API content *blocks*, so a renderer that only displays `str` silently drops every assistant reply.

**Hebrew/Gregorian date conversion** — use `pyluach`:
```python
from pyluach.dates import GregorianDate
GregorianDate(2026, 9, 3).to_heb().hebrew_date_string()
```

**Speaker search — the burst, not the volume, is the constraint.** A season is only ~300–600 queries, but a pair building one Mishmar fires 25 in three minutes, which is what trips DuckDuckGo's limiter. Hence: a Supabase cache (60 days for a success, **1 hour for a failure** — otherwise one blocked afternoon poisons the cache for the season), a module-level `threading.Lock` enforcing a 4s gap, a 60s→5m→15m cooldown ladder, and rotation across the eight `ddgs` text backends. Every failure degrades to a clickable manual-search link rather than an exception.

**Search the `notes` column, not just `expertise_topics`.** The parser files "מה העביר אצלנו" into `notes`, and that is often the strongest topical signal — גדי תורג'מן is filed under "הלכה, מחשבת הרמב"ם" while his notes read "מועמד טבעי לכל משמר תשובה". Searching topics alone hid exactly the person a תשובה search most wanted.

**Rendering a self-contained invitation HTML to PNG** — Playwright/Chromium is pre-installed (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`; do not run `playwright install`). Invitation HTML embeds all fonts as base64 `woff2` so it renders identically anywhere. If Playwright is reinstalled via pip it may expect a browser build that isn't present — pass `executable_path` to the one that is.

**Building/QA'ing a `.pptx` deck** — built with `pptxgenjs` (+ `react-icons` → `ReactDOMServer.renderToStaticMarkup` → `sharp` for icon PNGs). Requires `libreoffice-impress` and `libreoffice-writer` (not just `libreoffice-core`/`-common`, which alone fail with "source file could not be loaded") plus `poppler-utils`:
```
soffice --headless --convert-to pdf <file>.pptx     # render
pdftoppm -jpeg -r 120 <file>.pdf <prefix>            # slide-by-slide images
markitdown <file>.pptx                               # text dump, e.g. to grep for placeholders
```

**RTL layout in `pptxgenjs`** — no native RTL mode. Right-align text manually; order table columns right-to-left in the source array; for two-column grids fill the *right* column first, top-to-bottom; never start a Hebrew title with a leading digit (bidi misplaces it — write "כל 21 המשמרים", not "21 המשמרים").

**Round-robin pairing** (N people × M slots, no repeated pairs, balanced load, max spacing) — 1-factorization of the complete graph K_N, the circle method. Used for `2026-27/students.md`; reusable if the headcount or slot count changes.
