# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The toolkit for Midreshet Ein Prat's **Mishmar** programme — Thursday-night study seminars, scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim built by pairs of trainees. Two halves: a **Streamlit web app** (8 trainees + one instructor), and a **Hebrew content repository** (generator prompt, work-file templates, speaker database, invitation assets). The chat is **dormant** behind `app.CHAT_ENABLED = False` (its UI is parked in `chat_panel.py`); the live Anthropic use is the speaker-search scout — two model calls per search: `chat_agent.scout_map` reads the topic as fields, then `scout_speakers` searches the web itself with Anthropic's server web-search tool ($10 per 1,000 searches, capped at 8 per run).

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
```

**Run the harness on the Streamlit that `requirements.txt` pins** (`streamlit>=1.63,<1.65`): Cloud installs the newest allowed version on every push, and 1.64 moved the radio DOM under a sidebar the 1.63 harness had just measured. Upgrading = `pip install`, `scripts/streamlit_dom_context.py`, re-measure, then widen the pin.

There is no test suite and no live Supabase reachable from a sandbox. Verification runs on a local PostgreSQL 16 + a PostgREST-shaped shim + headless Chromium — described in `.claude/rules/database.md` §"Verifying changes" and `.claude/rules/ui.md` §"Verifying the UI", run end to end by the `deploy-check` agent. Without Streamlit secrets the app boots in name-only dev login, but storage still needs Supabase — there is no local storage mode.

## Hard constraints

- **Storage is Supabase only — never SQLite, never local files as a database.** `data_manager.py` is the ONLY module that talks to storage. The REST API cannot CREATE TABLE, so structure lives in `supabase_schema.sql`, run manually in the Supabase SQL Editor; a schema change means editing that file, **bumping `REQUIRED_SCHEMA_VERSION` in `data_manager.py` in the same commit** (the app compares it to `app_meta.schema_version`; a stale DB otherwise throws a redacted `APIError` inside a screen), AND telling the user to re-run it (idempotent). Joins/aggregates are views in that file — PostgREST cannot express them.
- **Secrets come from `st.secrets` (Streamlit Secrets): `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `ANTHROPIC_API_KEY`. Never generate or read `.env` files** — the user has no local dev environment. Full setup: `DEPLOY.md`.
- **No agent or skill writes to Supabase.** Every `.claude/agents/*.md` is read-only (`disallowedTools: Write, Edit, NotebookEdit`; no `dm.add_*` / `update_*` / `record_outreach`). Writes happen in the app, or under a human's confirmation.
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
- **Slots own their tasks.** `lessons` is the evening's structure; `tasks.lesson_id` ties a task to
  the slot it is about; `sync_lesson_tasks()` is the single reconciler — it creates each slot's
  tasks, adopts orphans written in its own wording, retires its own wording when a slot changes
  shape or number, renames a round's tasks when the evening gains or loses a second round of
  חבורות (same rows, «— סבב א׳»), and never deletes a DONE row or touches a human-written one.
  Everything about a round — presenters, sheets, rooms — is scoped to THAT round.
- **Reads are cached per table and writes invalidate per table** (`_READS` / `_WRITES` at the foot
  of `data_manager.py`). A new write function missing from `_WRITES` leaves stale rows on screen
  for up to two minutes.
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

**`system_rules.md` is the operating layer** — read it when acting as the programme's assistant rather than as a repo developer. `.claude/skills/` holds the programme's recurring workflows; `.claude/agents/` holds the specialized subagents (speaker-scout, topic-ideation, archive-diver, app-reviewer, weekly-brief, deploy-check, design-review, rerun-audit).

## Repository structure

```
app.py                 # Streamlit UI (render only; phase-driven; chat behind CHAT_ENABLED)
data_manager.py        # the ONLY data seam — Supabase REST, seeding, phase model
chat_agent.py          # Anthropic client + the scout (live); the 13-tool chat loop (dormant)
chat_panel.py          # the chat UI — imported only when app.CHAT_ENABLED is True
speaker_search.py      # verification («אמת»), throttling, manual search links — discovery is the scout's now
archive.py             # cross-year memory over 2025-26 work-files
supabase_schema.sql    # tables, views, RLS + GRANTs — run in Supabase SQL Editor
.streamlit/config.toml # brand theme (navy/parchment) — deploys with the app
.claude/hooks/         # guard-bash.sh — the PreToolUse guard wired in .claude/settings.json
DEPLOY.md              # Supabase + Streamlit Secrets setup, RLS rationale, first-run seed
system_rules.md        # operating layer: roles, pedagogy, speaker mandate, budget
students_tasks.md      # seed data read on first run
migrations/            # one-off SQL run by a human in the SQL Editor (trainee names + pairs)
scripts/               # rerun_audit · streamlit_dom_context · assign_trainees (writes migrations/ + docs)
Mishmer-section/       # generator prompt · templates · speakers · 2025-26 archive · 2026-27 season
Invitations/           # house style, watercolor prompts, past posters
```
