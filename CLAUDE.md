# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The toolkit for Midreshet Ein Prat's **Mishmar** programme — Thursday-night study seminars, scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim built by pairs of trainees. Two halves: a **Streamlit web app** (8 trainees + one instructor), and a **Hebrew content repository** (generator prompt, work-file templates, speaker database, invitation assets). The chat is **dormant** behind `app.CHAT_ENABLED = False` (its UI is parked in `chat_panel.py`); the live Anthropic use is the speaker-search scout — two model calls per search: `chat_agent.scout_map` reads the topic as fields, then `scout_speakers` searches the web itself with Anthropic's server web-search tool ($10 per 1,000 searches, capped at 8 per run).

**`web/` is v2**: the trainee home rebuilt as a static React app (Vite · TypeScript · Tailwind, installable PWA), published on GitHub Pages at `https://urishav464.github.io/mishmar/` by a separate deploy-only repo, `urishav464/mishmar` (its `deploy.yml` builds this repo's `web/` — hourly when `web/` changed, or on dispatch; **after changing `web/`, dispatch it**), with Supabase Auth (Google), on the same Supabase — the trainee home and the workfile (`src/Workfile.tsx`, hash route `#/m/N`: the task board to work on — ✓, add, edit, delete — the evening's structure to build in `src/Evening.tsx` — topic, slots, candidates, panel, חבורות, a source sheet as a link or an uploaded file — and logistics to read; the demo makes structure changes on the screen only, `src/demoEdits.ts`). Cloudflare was tried first (`web/wrangler.jsonc` still describes it): the build deployed, but the new `workers.dev` address stayed NXDOMAIN. All `urishav464.github.io` sites (the Shabbat pages too) share one origin and its `localStorage`, where the v2 session lives — never put a third-party script on any of them. **Stage 1** (the real trainee home) is set up and was tried by trainees, who asked for the whole system there; **stage 2** moves it part by part, each with its own plan and the instructor's preview first: **2א the workfile (done)** → **2ב editing the evening's structure (done)** → 2ג logistics, uploads (the source-sheet upload is done), feedback, budget → 2ד the speaker index and search → 2ה the instructor's dashboard. Until a part moves, it is edited in the Streamlit app, which keeps working on the same data.

**Stack:** Python · Streamlit · Supabase (PostgreSQL over PostgREST) · Anthropic API (Sonnet 5).

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # do not skip the venv
pip install -r requirements.txt
streamlit run app.py
```

Without a venv, `Authlib`→`cryptography` fails on Debian/Ubuntu system Python with *"Cannot uninstall cryptography, RECORD file not found"*, aborting the whole install. Escape hatch: `pip install --ignore-installed cryptography Authlib`.

```bash
python3 -m py_compile app.py data_manager.py chat_agent.py speaker_search.py chat_panel.py archive.py scripts/*.py   # the only static check
MISHMAR_NO_CACHE=1 streamlit run app.py               # read cache off, for scripts that write around the seam
python3 scripts/rerun_audit.py app.py                 # what every click costs; exit 1 on a write+st.rerun() double run
python3 scripts/streamlit_dom_context.py              # regenerate .claude/rules/streamlit-dom.md after a Streamlit upgrade
python3 scripts/assign_trainees.py                    # regenerate migrations/2026-09-assign-trainees.sql + the three owner docs (seed 5787)
python3 scripts/harness/db.py up && python3 scripts/harness/harness.py serve   # local PG16 fixture + the app, traced
python3 scripts/harness/harness.py sweep              # every screen + one click per kind vs the click contract
python3 scripts/harness/harness.py stop && python3 scripts/harness/db.py down
cd web && npm install && npm run build                # v2: tsc --noEmit + vite build (no env vars → demo mode)
python3 web/supabase/test_v2.py                       # v2's database doors vs Supabase's default grants (after db.py up)
python3 web/supabase/test_v2.py --on 5 --export web/src/demo.json --export-workfile web/src/demo_workfile.json   # regenerate the demo data
python3 web/supabase/test_v2_structure.py            # the structure doors vs data_manager, step for step on two fixture copies (--sql FILE: a planted bug must fail it)
python3 web/supabase/test_v2_tools.py [--deno PATH]   # the v2-tools Edge Function: its twins vs data_manager, its handler under Node; --deno: index.ts served by Deno against a stand-in Supabase
python3 web/check_ui.py                               # v2 in Chromium under /mishmar/: demo, mocked-auth, workfile, instructor and bad-settings builds, 390/1500px
```

**Run the harness on the Streamlit that `requirements.txt` pins** (`streamlit>=1.63,<1.65`): Cloud installs the newest allowed version on every push, and 1.64 moved the radio DOM under a sidebar the 1.63 harness had just measured. Upgrading = `pip install`, `scripts/streamlit_dom_context.py`, re-measure, then widen the pin.

There is no test suite and no live Supabase reachable from a sandbox. Verification runs on a local PostgreSQL 16 + a PostgREST-shaped shim + headless Chromium — **committed in `scripts/harness/`**, with a tracer that names the cause of every run (the callback, widget or `st.rerun` line) and its queries by table. Described in `.claude/rules/database.md` §"Verifying changes" and `.claude/rules/ui.md` §"Verifying the UI"; `app-reviewer` uses it to prove why a click reruns and to prove its fixes on a scratch copy, `deploy-check` runs the sweep. Without Streamlit secrets the app boots in name-only dev login, but storage still needs Supabase — there is no local storage mode.

## Hard constraints

- **Storage is Supabase only — never SQLite, never local files as a database.** `data_manager.py` is the ONLY module that talks to storage. The REST API cannot CREATE TABLE, so structure lives in `supabase_schema.sql`, run manually in the Supabase SQL Editor; a schema change means editing that file, **bumping `REQUIRED_SCHEMA_VERSION` in `data_manager.py` in the same commit** (the app compares it to `app_meta.schema_version`; a stale DB otherwise throws a redacted `APIError` inside a screen), AND telling the user to re-run it (idempotent). Joins/aggregates are views in that file — PostgREST cannot express them.
- **Secrets come from `st.secrets` (Streamlit Secrets): `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `ANTHROPIC_API_KEY`. Never generate or read `.env` files** — the user has no local dev environment. Full setup: `DEPLOY.md`.
- **No agent or skill writes to Supabase.** Every `.claude/agents/*.md` is read-only (`disallowedTools: Write, Edit, NotebookEdit`; no `dm.add_*` / `update_*` / `record_outreach`). Writes happen in the app, or under a human's confirmation.
- **v2 (`web/`) goes through doors only.** Its browser holds the public anon key, so no table or view is ever granted to `anon` / `authenticated`.
  - A Google-signed-in user may EXECUTE only the `SECURITY DEFINER` functions in `web/supabase/v2.sql` — today `v2_my_home()`, `v2_home_as()`, `v2_workfile()` (reads) and `v2_set_task_status()`, `v2_add_task()`, `v2_edit_task()`, `v2_delete_task()` and the evening's structure — `v2_set_topic()`, `v2_add_slot()`, `v2_save_slot()`, `v2_delete_slot()`, `v2_reopen_slot()`, `v2_add_person()`, `v2_edit_person()`, `v2_set_person_status()`, `v2_remove_person()` (writes; each answers with the whole evening, already reconciled). None ever returns an e-mail or a `speakers.contact` (the structure doors write a phone into it when it is empty, as the app does); a speaker's phone (`lesson_speakers.phone`) and task `details` come only from `v2_workfile`, to the pair of that evening and the instructor (the instructor's decision, stage 2א). Every write is scoped to the caller's own evenings, and the instructor writes nothing.
  - **The task classifier and the deadline offsets have SQL twins** in `v2.sql` (`v2_private.classify_task` / `due_date`, used by `v2_add_task`). `test_v2.py` fails if they drift from `dm._CATEGORY_RULES` / `DEADLINE_OFFSETS_DAYS` — change both together.
  - **So does the evening's structure** (stage 2ב): `v2_private.sync_lesson_tasks` and the rules it stands on — the clock (`recompute_times`, `create_default_timeline`, `delete_slot`), the people (`close_speaker`, `set_person_status`, `refresh_panel`, `adopt_panel_speaker`), the shared index (`resolve_speaker`, `learn_speaker`, `learn_phone`, `split_title`) and the journal's single writer (`record_outreach`) — each named after its `dm` original. `test_v2_structure.py` runs every door and its Streamlit callback on two copies of the fixture and compares the evening, the index and the journal after every step (a fixed scenario through every path, old states for the reconciler, seeded random walks; twelve planted bugs, each caught). **Change a rule in `data_manager` → change its twin in `v2.sql` in the same commit.**
  - The instructor is the address on the `role='instructor'` row (linked in the same «🔗 שיוך חשבונות» form): `v2_my_home()` answers them with the trainees' ids and names, and `v2_home_as(id)` with exactly that trainee's own answer (both built by `v2_private.home_of`). View-only — `v2_set_task_status` refuses them. An address on a trainee's row wins.
  - Who the caller is lives in `v2_private.caller()`, a schema PostgREST does not expose and the public roles cannot use; every door goes through it.
  - `test_v2.py` fails if the catalog shows any other privilege for the public roles. A new door means updating `EXPECTED_LEAKS` on purpose, with its own refuse/allow checks.
  - `v2.sql` is v2-only and run by hand (the whole file, idempotent); it does not touch `REQUIRED_SCHEMA_VERSION`. A v2 write bypasses the Streamlit read cache, so the old app shows it within 15 minutes.
  - **One server-side piece: the Edge Function `v2-tools`** (`web/supabase/functions/v2-tools` — `index.ts` wires, `handler.ts` decides, `upload.ts` holds the rules, imported by the site too). It stores a source sheet (pdf/doc(x)/ppt(x)/png/jpg/webp, ≤ 20MB) in the public `sources` bucket and answers with the public link; the site then saves it through `v2_save_slot` / `v2_edit_person`. It writes no row. Who may upload is asked of the database: it calls `v2_workfile` **with the caller's own token** and the public key, and goes on only for `viewer = trainee` with the slot or person in that answer (never a break; the instructor never). The service key exists only inside the function, from the environment Supabase gives it — never in the browser, never on the read. Deployed through the Supabase connection with **verify_jwt off on purpose** (the project's new signing keys are not read by the platform check; the database checks instead), only after the instructor approves each deploy. The key it stores under is a twin: `safeFilename` = `dm._safe_filename`, `contentTag` = `dm._content_tag`, a slot's path = `dm.upload_source_sheet`'s (`mishmar-NN/lesson-<id>-<sha1[:8]>-<safe>`; a presenter's is `presenter-<id>-…`). `test_v2_tools.py` fails if they drift — change both together.
  - The only build variables are `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`, set as repository Variables of `urishav464/mishmar` (Settings → Secrets and variables → Actions → Variables) — never a `.env`, never the service_role key: `vite.config.ts` fails the build on a secret key (`sb_secret_…` or a service_role JWT, via `src/env.ts`), and a malformed value shows a screen naming the setting instead of a blank page.
  - `web/public/privacy.html` is the privacy policy Google's consent screen links to (Google Auth Platform → Branding requires one before the app can leave Testing). It must stay **true**: a change that makes v2 store, show or load something new updates it in the same commit (an uploaded sheet is public to whoever has its link — said there). Static — no script, nothing fetched from elsewhere (`check_ui.py` checks).
- **Never invent content**: topics, speakers, texts, dates, contact details, budget figures. Unknown stays `TBD`. Never propose a speaker who is not alive and active.
- **Git:** all development on `claude/mishmer-generator-setup-h5gxqx`. **`main` is empty** — Streamlit Cloud deploys from the working branch. Commit and push when a piece of work completes. Enforced, not advisory: `.claude/hooks/guard-bash.sh` (PreToolUse on Bash) blocks `git push` to `main` or with `--force`, and any Bash access to the Streamlit secrets file.

## The ideas that explain most of the code

- **One renderer, one seam.** `app.py` (~3.7k lines) only renders; `data_manager.py` (~2.7k) is the
  only module that talks to storage. Anything needing a join or an aggregate is a **view** in
  `supabase_schema.sql` — `v_tasks_full`, `v_speaker_status`, `v_overdue_tasks`, `v_mishmar_budget`,
  `v_outreach_full`, `v_student_progress` — because PostgREST cannot express one.
- **Every screen is phase-driven.** `dm.PHASES` maps task *categories* onto four build phases
  (נושא → מרצים ותוכן → לוגיסטיקה → אחרי הערב) and `mishmar_progress()` derives where an evening
  stands. The trainee home shows only the current phase, the dashboard sorts by it, the workfile
  accordion opens on it. It takes preloaded rows, so a 21-Mishmar list costs two queries, not 42.
  An evening that has happened closes its tasks once — all but its feedback task
  (`close_past_mishmar_tasks`, run daily); late tasks on the dashboard and the home are folded
  per Mishmar, phases inside (`_late_by_mishmar`).
- **Slots own their tasks.** `lessons` is the evening's structure; `tasks.lesson_id` ties a task to
  the slot it is about; `sync_lesson_tasks()` is the single reconciler — it creates each slot's
  tasks, adopts orphans written in its own wording, retires its own wording when a slot changes
  shape or number, renames a round's tasks when the evening gains or loses a second round of
  חבורות (same rows, «— סבב א׳»), and never deletes a DONE row or touches a human-written one.
  Everything about a round — presenters, sheets, rooms — is scoped to THAT round. A **panel**
  slot (format «פאנל») holds several speakers who are ALL closed — closing one never deletes
  another, and the slot's `speaker_name` is derived from its ✅ rows (`dm.close_panelist`,
  `dm.refresh_panel_speakers`).
- **Reads are cached per table and writes invalidate per table** (`_READS` / `_WRITES` at the foot
  of `data_manager.py`). A new write function missing from `_WRITES` leaves stale rows on screen
  for up to fifteen minutes (`CACHE_TTL_SECONDS = 900`).
- **Navigation is staged; panels are isolated.** `_goto()` parks a deep link under one session key
  and `_apply_goto()` lands it at the top of `main()` before any widget exists — writing a widget's
  key after that widget was drawn raises. The workfile body, the dashboard body and the trainee
  home are `@st.fragment`s (a task click reruns the body, not the app; closing a `st.dialog` is a
  whole-app run, so the task editor is a popover), and the three evening panels are wrapped in
  `_safe()` so one broken panel cannot blank a column.
- **The season's data starts as Markdown.** `students_tasks.md` seeds a first run against an empty
  Supabase — the trainees from its index table, the 21 evenings, their tasks — and
  `app_meta.seeded` guards it forever after. **The file stays the source of the roster after
  that too**: `dm.roster_drift()` diffs it against the live tables by name, and the dashboard's
  always-present «👥 חניכים ושיבוץ» panel applies the difference (`dm.apply_trainee_roster`,
  behind a two-step dialog) — a trainee leaving and the pairs being re-drawn, not just the first
  time the names arrived. **A replacement is a delete plus an insert, never a rename** — the
  leaver's row carries their Google `email` (their login) and their history — and a new trainee
  gets `MAX(id)+1` on both paths, never a retired id. `migrations/2026-09-assign-trainees.sql` is the same mapping for the SQL
  Editor; `scripts/assign_trainees.py` regenerates it and the Markdown together.

## Where the detailed knowledge lives

Path-scoped rules load automatically when their files enter context:

- `.claude/rules/database.md` — the tables, RLS/service_role, views (and when they must be DROPped), the schema-version gate, the per-table read cache (`_READS`/`_WRITES`), the derived evening timeline, the candidates flow, name normalisation, the outreach log, derived deadlines, and the local-PG16 verification harness.
- `.claude/rules/ui.md` — RTL mechanics, the rerun trap, the design system + brand theme, deep-link navigation and its widget-state trap, phase-driven UI, query budgets, date formats, Playwright verification, the micro-interactions in use (`st.dialog` / `st.status` / `st.feedback` / `st.segmented_control`) and the hook's path-token rule.
- `.claude/rules/pedagogy.md` — what a Mishmar is, ideal vs. real format, the content rules (dead-thinker trap, ⚠️ לאמת, no invented contacts), the archive's traps, speaker-search throttling, the image workflow.
- `.claude/rules/streamlit-dom.md` — **generated** from the installed Streamlit bundle: every
  `data-testid` it contains plus the measured structural facts (what is portaled outside the RTL
  root, that a selectbox is react-aria not BaseWeb, the negative markdown margin). A selector absent from
  it is a dead rule. Regenerate after a Streamlit upgrade; `design-review` and `app-reviewer` read
  it instead of guessing.
- `.claude/rules/chat-agent.md` — the dormant chat loop and the live scout: the Mishmar-scoping rule and the four cost ceilings that keep a turn flat.
- **Performance is a rule, not a phase**: reads are cached by table and every write invalidates through `data_manager` (`_READS`/`_WRITES`); buttons use `on_click`, never `write(); st.rerun()`; the workfile body and the chat are fragments. Details in `database.md` and `ui.md`.

**`system_rules.md` is the operating layer** — read it when acting as the programme's assistant rather than as a repo developer. `.claude/skills/` holds the programme's recurring workflows; `.claude/agents/` holds the specialized subagents (speaker-scout, topic-ideation, archive-diver, app-reviewer, weekly-brief, deploy-check, design-review).

## Repository structure

```
app.py                 # Streamlit UI (render only; phase-driven; chat behind CHAT_ENABLED)
data_manager.py        # the ONLY data seam — Supabase REST, seeding, phase model
chat_agent.py          # Anthropic client + the scout (live); the 13-tool chat loop (dormant)
chat_panel.py          # the chat UI — imported only when app.CHAT_ENABLED is True
speaker_search.py      # manual search links (screen) · verification + discovery for the CLI agents
archive.py             # cross-year memory over 2025-26 work-files
supabase_schema.sql    # tables, views, RLS + GRANTs — run in Supabase SQL Editor
.streamlit/config.toml # brand theme (navy/parchment) — deploys with the app
.claude/hooks/         # guard-bash.sh — the PreToolUse guard wired in .claude/settings.json
DEPLOY.md              # Supabase + Streamlit Secrets setup, RLS rationale, first-run seed
system_rules.md        # operating layer: roles, pedagogy, speaker mandate, budget
students_tasks.md      # seed data read on first run
migrations/            # one-off SQL run by a human in the SQL Editor (trainee names + pairs)
scripts/               # rerun_audit · streamlit_dom_context · assign_trainees · keep_awake · harness/ (local PG16 + shim + rerun tracer, test-only)
.github/workflows/     # keep-awake.yml — visits the Cloud app every 6 h (needs the STREAMLIT_APP_URL repo variable)
web/                   # v2 — React PWA (the home, the workfile, the evening's structure) · supabase/v2.sql the doors + test_v2.py + test_v2_structure.py · supabase/functions/v2-tools the upload function + test_v2_tools.py · check_ui.py
Mishmer-section/       # generator prompt · templates · speakers · 2025-26 archive · 2026-27 season
Invitations/           # house style, watercolor prompts, past posters
```
