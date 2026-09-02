# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The toolkit for Midreshet Ein Prat's **Mishmar** programme — Thursday-night study seminars, scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim built by pairs of trainees. Two halves: a **Streamlit web app** (10 trainees + one instructor), and a **Hebrew content repository** (generator prompt, work-file templates, speaker database, invitation assets). The chat is **dormant** behind `app.CHAT_ENABLED = False` (its UI is parked in `chat_panel.py`); the live Anthropic use is the speaker-search scout (`chat_agent.scout_speakers`), one model call per search.

**Stack:** Python · Streamlit · Supabase (PostgreSQL over PostgREST) · Anthropic API (Sonnet 5).

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # do not skip the venv
pip install -r requirements.txt
streamlit run app.py
```

Without a venv, `Authlib`→`cryptography` fails on Debian/Ubuntu system Python with *"Cannot uninstall cryptography, RECORD file not found"*, aborting the whole install. Escape hatch: `pip install --ignore-installed cryptography Authlib`.

```bash
python3 -m py_compile app.py data_manager.py chat_agent.py speaker_search.py chat_panel.py archive.py   # the only static check
MISHMAR_NO_CACHE=1 streamlit run app.py                                                                  # read cache off, for scripts that write around the seam
```

There is no test suite and no live Supabase reachable from a sandbox. Verification runs on a local PostgreSQL 16 + a PostgREST-shaped shim + headless Chromium — described in `.claude/rules/database.md` §"Verifying changes" and `.claude/rules/ui.md` §"Verifying the UI", run end to end by the `deploy-check` agent. Without Streamlit secrets the app boots in name-only dev login, but storage still needs Supabase — there is no local storage mode.

## Hard constraints

- **Storage is Supabase only — never SQLite, never local files as a database.** `data_manager.py` is the ONLY module that talks to storage. The REST API cannot CREATE TABLE, so structure lives in `supabase_schema.sql`, run manually in the Supabase SQL Editor; a schema change means editing that file, **bumping `REQUIRED_SCHEMA_VERSION` in `data_manager.py` in the same commit** (the app compares it to `app_meta.schema_version`; a stale DB otherwise throws a redacted `APIError` inside a screen), AND telling the user to re-run it (idempotent). Joins/aggregates are views in that file — PostgREST cannot express them.
- **Secrets come from `st.secrets` (Streamlit Secrets): `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `ANTHROPIC_API_KEY`. Never generate or read `.env` files** — the user has no local dev environment. Full setup: `DEPLOY.md`.
- **No agent or skill writes to Supabase.** Every `.claude/agents/*.md` is read-only (`disallowedTools: Write, Edit, NotebookEdit`; no `dm.add_*` / `update_*` / `record_outreach`). Writes happen in the app, or under a human's confirmation.
- **Never invent content**: topics, speakers, texts, dates, contact details, budget figures. Unknown stays `TBD`. Never propose a speaker who is not alive and active.
- **Git:** all development on `claude/mishmer-generator-setup-h5gxqx`. **`main` is empty** — Streamlit Cloud deploys from the working branch. Commit and push when a piece of work completes. Enforced, not advisory: `.claude/hooks/guard-bash.sh` (PreToolUse on Bash) blocks `git push` to `main` or with `--force`, and any Bash access to the Streamlit secrets file.

## Where the detailed knowledge lives

Path-scoped rules load automatically when their files enter context:

- `.claude/rules/database.md` — the tables, RLS/service_role, views (and when they must be DROPped), the schema-version gate, the per-table read cache (`_READS`/`_WRITES`), the derived evening timeline, the candidates flow, name normalisation, the outreach log, derived deadlines, and the local-PG16 verification harness.
- `.claude/rules/ui.md` — RTL mechanics, the rerun trap, the design system + brand theme, deep-link navigation and its widget-state trap, phase-driven UI, query budgets, date formats, Playwright verification, the micro-interactions in use (`st.dialog` / `st.status` / `st.feedback` / `st.segmented_control`) and the hook's path-token rule.
- `.claude/rules/pedagogy.md` — what a Mishmar is, ideal vs. real format, the content rules (dead-thinker trap, ⚠️ לאמת, no invented contacts), the archive's traps, speaker-search throttling, the image workflow.
- `.claude/rules/chat-agent.md` — the dormant chat loop and the live scout: the Mishmar-scoping rule and the four cost ceilings that keep a turn flat.
- **Performance is a rule, not a phase**: reads are cached by table and every write invalidates through `data_manager` (`_READS`/`_WRITES`); buttons use `on_click`, never `write(); st.rerun()`; the workfile body and the chat are fragments. Details in `database.md` and `ui.md`.

**`system_rules.md` is the operating layer** — read it when acting as the programme's assistant rather than as a repo developer. `.claude/skills/` holds the programme's recurring workflows; `.claude/agents/` holds the specialized subagents (speaker-scout, topic-ideation, archive-diver, app-reviewer, weekly-brief, deploy-check).

## Repository structure

```
app.py                 # Streamlit UI (render only; phase-driven; chat behind CHAT_ENABLED)
data_manager.py        # the ONLY data seam — Supabase REST, seeding, phase model
chat_agent.py          # Anthropic client + the scout (live); the 13-tool chat loop (dormant)
chat_panel.py          # the chat UI — imported only when app.CHAT_ENABLED is True
speaker_search.py      # discovery (mines names) + verification, throttled
archive.py             # cross-year memory over 2025-26 work-files
supabase_schema.sql    # tables, views, RLS + GRANTs — run in Supabase SQL Editor
.streamlit/config.toml # brand theme (navy/parchment) — deploys with the app
.claude/hooks/         # guard-bash.sh — the PreToolUse guard wired in .claude/settings.json
DEPLOY.md              # Supabase + Streamlit Secrets setup, RLS rationale, first-run seed
system_rules.md        # operating layer: roles, pedagogy, speaker mandate, budget
students_tasks.md      # seed data read on first run
Mishmer-section/       # generator prompt · templates · speakers · 2025-26 archive · 2026-27 season
Invitations/           # house style, watercolor prompts, past posters
```
