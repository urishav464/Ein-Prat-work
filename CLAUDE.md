# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The educational toolkit for Midreshet Ein Prat. Two halves that live together:

1. **A Streamlit web app** (`app.py`, `data_manager.py`) that runs the Mishmar programme — scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**. This is real, running code.
2. **A Hebrew content repository** — Markdown work-files, a generator prompt, a self-contained HTML invitation, a PPTX deck. "Building" there means composing Hebrew documents and rendering HTML/PPTX to images for visual QA.

The app migrates the content half's task tracking into SQLite. That migration is written and tested but **has not been run against the repo yet** — `students_tasks.md` is still present and intact.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # see the note below — do not skip
pip install -r requirements.txt
streamlit run app.py                    # first run creates mishmar.db AND archives students_tasks.md
python3 data_manager.py                 # bootstrap the DB without the UI; prints migration counts
export ANTHROPIC_API_KEY=sk-ant-...     # only the chat page needs this; everything else works without
```

**Install into a venv.** `Authlib` (for Google sign-in) pulls `cryptography`, and on Debian/Ubuntu system Python that fails with *"Cannot uninstall cryptography, RECORD file not found"* — which aborts the whole `pip install` and, in a `&&` chain, never reaches `streamlit run`. A venv sidesteps it entirely. Without one, `pip install --ignore-installed cryptography Authlib` is the escape hatch; everything except Google login works without Authlib at all.

Deployment (Google sign-in, the ephemeral-disk problem): **`DEPLOY.md`**.

There is no test suite. Verify against a **sandboxed copy**, never the live repo — the migration is destructive (it renames `students_tasks.md`), so testing in place consumes the seed data:

```bash
mkdir -p /tmp/sb/Mishmer-section/speakers && cd /tmp/sb
cp <repo>/{app.py,data_manager.py,students_tasks.md} .
cp <repo>/Mishmer-section/speakers/database.md Mishmer-section/speakers/
python3 -c "import data_manager as dm; print(dm.bootstrap('/tmp/sb/test.db'))"
```

Every `data_manager` function takes a `db_path` argument for exactly this reason — pass a temp path to test without touching `mishmar.db`.

To verify the UI actually renders (not just that it parses), run headless and drive it with the pre-installed Chromium. Streamlit only executes the script when a browser session connects, so `curl` alone returns the shell HTML and proves nothing:

```bash
streamlit run app.py --server.headless true --server.port 8555 &
# Playwright: executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"]
```

## Application architecture

**`data_manager.py` is the only data seam.** Nothing else opens the database or reads the Markdown sources. It owns the schema, the migration, and every query.

- **SQLite in WAL mode**, `check_same_thread=False`, `timeout=10`. Not incidental: Streamlit serves each session on its own thread and reruns the whole script on every interaction, so without WAL the app hits "database is locked" as soon as two people use it.
- **Eleven tables**: `Mishmarim`, `Students`, `Tasks`, `Budget`, `Speakers`, `Lessons`, `Feedback`, `ChatMessages`, plus `Assignments` (Mishmar ownership is a *pair*, so it is many-to-many), `_meta` (migration guard + schema version) and `SearchCache`.

- **Schema changes go in `MIGRATIONS`, never into `SCHEMA`.** `CREATE TABLE IF NOT EXISTS` adds a missing table but never a missing *column*, so anything past the base schema is a numbered step applied once and recorded in `_meta.schema_version`. Bump `SCHEMA_VERSION` with it.
- **`Lessons` is deliberately not four rows.** `slot_order` is 1..N and `lesson_role` is free text, because the 2025-26 archive holds a ceremony plus two lessons, and a song circle. The four-lesson arc is the default the generator emits, not a constraint the schema enforces.
- **Task deadlines are derived, never stored by hand** — `classify_task()` maps the text to a category, `compute_due_date()` offsets from the Mishmar date (topic −21d, speakers −14d, invitation/refreshments/decoration −7d). The opening deck calls these *"המלצה — לא חוק"*, so `annotate_deadline()` phrases them as nudges; only the instructor dashboard treats a passed date as actionable.
- **`budget_used` is a view**, never a stored column — a stored copy drifts from the `Budget` rows it derives from.
- **`Tasks.student_id` is nullable**: `NULL` means the task belongs to the Mishmar and therefore to both owners in the pair, which is how the task lists were actually written.
- **`Speakers.source_type`** separates `original_44` (seeded from `Mishmer-section/speakers/database.md`) from `web_search`, so growth of the index is measurable.
- **Outreach is a log, not a field.** `SpeakerOutreach` records each approach (speaker, Mishmar, who, status, note) and `v_speaker_status` derives current status from the newest row — same reasoning as `budget_used`. **`record_outreach()` is the only writer**; `upsert_lesson` delegates to it rather than setting `speaker_status` itself. Before this, closing a speaker wrote only `Lessons.speaker_status`, so the shared index never learned and the next pair got a stale answer — defeating the one mechanism the opening deck relies on to stop two pairs approaching the same person.
- **Speaker names must be normalised before lookup.** `normalize_name()` / `_norm_sql()` fold Hebrew gershayim (`״`) to ASCII. Three seeded names use the Hebrew form, and without folding a trainee typing `ד"ר` both missed the record *and* caused `record_outreach` to create a second row for the same human.
- **Name lookup refuses to guess.** `resolve_speaker()` raises `AmbiguousSpeaker` when several rows share a name — flag ה7 (up to four people called אורי, *"אל תאחד אותם על דעתך"*) is live data, not a hypothetical.

**Migration & deprecation.** `migrate_and_archive_md()` parses `students_tasks.md` — which carries dates, type, ownership *and* tasks, so it seeds the whole schema — loads it into SQLite, then **renames** it to `students_tasks_ARCHIVED.md`. From then on SQLite is the sole source of truth. Guarded by a `_meta` flag, so it is safe to call on every start. Rename rather than delete: it holds 193 hand-written task lines.

**`speaker_search.py`** is the speaker-discovery layer. Two paths, and the distinction is the whole design: `search_candidates()` **discovers** — broad queries (including `site:ac.il`) whose results are mined for names by `extract_names()`; `verify_speaker()` **verifies** one name against the `⚠️ לאמת` checklist. Discovery is what surfaces a lecturer no model has heard of, so it is not optional garnish on verification. Synthesis happens in chat via `format_for_chat()` — no paid API in v1. Every network call funnels through one `_fetch()` so the cache, the 4s throttle and the cooldown ladder cannot be bypassed.

**`chat_agent.py`** is the conversational layer, and it is where the pedagogy and the app finally meet: the generator prompt is loaded from disk as the system prompt rather than pasted into an external chat. Nine tools read and write the real data. **Every writing tool is bound to the Mishmar in the session context — the model never supplies a `mishmar_id`**, so a trainee's chat cannot reach another pair's Mishmar even if the conversation asks it to. The ~20k-char stable half of the system prompt carries the cache breakpoint; live context sits after it.

**`archive.py`** is cross-year memory. Two traps it already hit: this season's folders are unfilled templates and must not be searched as history, and every work-file inherits a status legend containing `ממתין לתשובה`, so an unfiltered search for a Mishmar on תשובה matched all 21 templates. Strip boilerplate before matching.

**`app.py`** renders only. Bootstrap is wrapped in `@st.cache_resource` — uncached, it would reopen the database on every click. Login is name-based with no password (`Uri`/`uri`/`אורי` → admin); a deliberate v1 decision, and the login screen carries the warning. **Run locally only** while the speaker index holds contact details.

## Operating layer

`system_rules.md` is the operating layer for the app — hardcoded scope, roles (Instructor `Uri` / Student), the 4-lesson pedagogy, the web-search speaker mandate, and the budget model. **Read it whenever someone interacts as a student or as the instructor**, rather than as a repo developer.

The split: this file guides whoever *builds* the repo; `system_rules.md` guides whoever *operates* the programme. Sibling to `Mishmer-section/generator/mishmar-generator-prompt.md`, the topic-design tool.

## Conventions

- **Language:** file/folder names in English, all content in Hebrew.
- **Dates:** always give Hebrew + Gregorian together (e.g. `כ״א אלול תשפ״ו | 3.9.2026`).
- **Never invent content.** Topics, speakers, texts, dates, contact details, budget figures. Unknown fields stay `TBD` — never filled in by guessing.
- **Never invent a speaker — but never narrow to the database either.** It is a growing index, not the candidate set; web search is a primary discovery path (`system_rules.md` §4). Every proposed name needs a source. A name from model knowledge carries `⚠️ לאמת` plus the checklist (alive? still active? where do they live?). Watch the dead-thinker trap: the generator prompt is full of Spinoza, Levinas, Kafka, Agnon — those are texts to study, not people to invite.
- **Flag inconsistencies, don't silently fix them.** See `Mishmer-section/2025-26/mishmarim/` for the pattern, and the open `ה7` flag in `Mishmer-section/speakers/database.md` (up to four different people named אורי — the standing instruction is *"אל תאחד אותם על דעתך"*).
- **Budget is tracking, not enforcement.** ₪500 per Mishmar is an average covering speakers *and* refreshments. Overrun on one Mishmar is not an error — it draws from the season-wide line and cheap nights balance it. There is deliberately no season ceiling.
- **Two auth modes.** No `[auth]` in `.streamlit/secrets.toml` → name-only login, for local development. `[auth]` present → Google OIDC, and the name box is removed entirely; leaving it would keep the "type Uri" bypass open next to real auth.
- **Git:** all development happens on `claude/mishmer-generator-setup-h5gxqx`. `main` exists only as a base for Pull Requests — don't push work there directly.

## Repository structure

```
app.py                 # Streamlit frontend: login, admin dashboard, student Kanban
data_manager.py        # the ONLY data seam — SQLite schema, migration, all queries
system_rules.md        # operating layer: roles, philosophy, speaker mandate, budget
students_tasks.md      # seed data for the migration; archived on first app run

Mishmer-section/
├── generator/mishmar-generator-prompt.md   # "Mishmar Architect" prompt + Appendix A speaker digest
├── templates/mishmar-workfile-template.md  # the REAL per-Mishmar operating format
├── speakers/database.md                    # cross-year speaker index (~44 seeded people)
├── 2025-26/mishmarim/                      # archive: 5 real work-files, verbatim
└── 2026-27/                                # current season
    ├── schedule.md                         # source of truth: 21 dates, type, responsible pair
    ├── students.md                         # round-robin pairing (placeholder names)
    ├── speakers.md                         # this season's outreach log
    └── mishmarim/NN-slug/{workfile,draft,brief,invitation}.md

Invitations/           # house style, watercolor prompts, past posters
```

**Important architectural note:** the generator prompt describes an idealized 4-lesson Logos→Pathos structure (Foundation → Conflict → Twist → Soul). In practice real Mishmarim rarely follow it — some have 3 lessons, some are ceremonial (יום הזכרון), some are song circles. **The actual operating format is `templates/mishmar-workfile-template.md`**, reverse-engineered from five real 2025-26 documents. The four-lesson arc is a strong default and the app's generator always emits it, but a student who wants to deviate should be helped, not corrected.

## Image workflow (no image generation available)

Claude cannot generate images here. The workflow is fixed:

1. User names the Mishmar's topic.
2. Claude writes an image-generation prompt from `Invitations/prompt/base-prompt.md` and its variants.
3. User generates the image externally and uploads it (chat-pasted images are not persisted to disk — must arrive via GitHub upload or `git push`).
4. Claude composes the invitation from the uploaded image.

**Exception:** if the user prefers an existing background from `Invitations/examples/`, skip steps 2–3.

Never suggest filters (sharpen, upscale, texture) as a substitute for actually generating watercolor artwork — those improve an existing file, they don't produce the house style from scratch.

## Repeatable techniques used in this repo

**RTL in Streamlit** — no native mode; `direction: rtl` is injected as CSS. Two behaviours differ and both matter:
- `st.columns` **does** mirror under RTL. Declaring `[TO DO, IN PROGRESS, DONE]` renders TO DO on the right — correct Hebrew reading order.
- `st.dataframe` **does not**. Columns lay out left-to-right in insertion order, so declare them in reverse to put the first column on the right.
- Anything inside a raw-HTML block (e.g. Kanban cards) needs `html.escape` plus markdown stripping, or backticks and `**` render literally.

**Hebrew/Gregorian date conversion** — use `pyluach`:
```python
from pyluach.dates import GregorianDate
GregorianDate(2026, 9, 3).to_heb().hebrew_date_string()
```

**Speaker search — the burst, not the volume, is the constraint.** A season is only ~300-600 queries, but a pair building one Mishmar fires 25 in three minutes, which is what trips DuckDuckGo's limiter. Hence: SQLite cache (60 days for a success, **1 hour for a failure** — otherwise one blocked afternoon poisons the cache for the season), a module-level `threading.Lock` enforcing a 4s gap (all trainees share one machine and therefore one IP, so a process-wide lock genuinely gates everyone), a 60s→5m→15m cooldown ladder, and backend rotation across the eight `ddgs` text backends. Every failure degrades to a clickable manual-search link rather than an exception.

**Search the `notes` column, not just `expertise_topics`.** The parser files "מה העביר אצלנו" into `notes`, and that is often the strongest topical signal — גדי תורג'מן is filed under "הלכה, מחשבת הרמב"ם" while his notes read "מועמד טבעי לכל משמר תשובה". Searching topics alone hid exactly the person a תשובה search most wanted.

**Web search is blocked in this sandbox.** The `ddgs` package (renamed from `duckduckgo-search`; the class is `DDGS`) fails here with `403 Forbidden` on the proxy CONNECT — it defaults to a Google backend, and the DuckDuckGo backend is blocked too. Code depending on it must degrade gracefully and cannot be verified live from this environment: test the failure path and the caching, and leave live verification to the user's machine.

**Rendering a self-contained invitation HTML to PNG** — Playwright/Chromium is pre-installed (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, do not run `playwright install`). Invitation HTML embeds all fonts as base64 `woff2` (via `@font-face`, no external CDN) so it renders identically anywhere. If Playwright gets reinstalled via pip it may expect a browser build that isn't present — pass `executable_path` to the one that is (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`).

**Building/QA'ing a `.pptx` deck** — built with `pptxgenjs` (+ `react-icons` → `ReactDOMServer.renderToStaticMarkup` → `sharp` for icon PNGs). Requires `libreoffice-impress` and `libreoffice-writer` (not just `libreoffice-core`/`libreoffice-common`, which alone fail with "source file could not be loaded" on every conversion) plus `poppler-utils`:
```
apt-get update && apt-get install -y libreoffice-impress libreoffice-writer poppler-utils
```
QA pipeline for any `.pptx`/`.docx`:
```
python scripts/office/validate.py <file>.pptx      # OOXML schema/relationship check
soffice --headless --convert-to pdf <file>.pptx     # render
pdftoppm -jpeg -r 120 <file>.pdf <prefix>            # slide-by-slide images for visual review
markitdown <file>.pptx                               # text-content dump, e.g. to grep for leftover placeholders
```

**RTL layout in `pptxgenjs`** — no native RTL mode. Right-align text manually; order table columns right-to-left in the source array; for two-column grids fill the *right* column first, top-to-bottom; never start a Hebrew title string with a leading digit (bidi misplaces it — write "כל 21 המשמרים", not "21 המשמרים").

**Round-robin pairing schedule** (N people × M slots, no repeated pairs, balanced load, max spacing) — 1-factorization of the complete graph K_N ("circle method"). Used for `2026-27/students.md`; reusable if the headcount or slot count changes.
