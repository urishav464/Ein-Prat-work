# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The toolkit for Midreshet Ein Prat's **Mishmar** programme — Thursday-night study seminars, scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim built by pairs of trainees. Two halves: a **Streamlit web app** (10 trainees + one instructor), and a **Hebrew content repository** (generator prompt, work-file templates, speaker database, invitation assets). The generator prompt IS the chat's system prompt, and the chat's tools read and write the same rows the UI shows.

**Stack:** Python · Streamlit · Supabase (PostgreSQL over PostgREST) · Anthropic API (Sonnet 5).

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate   # do not skip the venv
pip install -r requirements.txt
streamlit run app.py
```

Without a venv, `Authlib`→`cryptography` fails on Debian/Ubuntu system Python with *"Cannot uninstall cryptography, RECORD file not found"*, aborting the whole install. Escape hatch: `pip install --ignore-installed cryptography Authlib`.

## Hard constraints

- **Storage is Supabase only — never SQLite, never local files as a database.** `data_manager.py` is the ONLY module that talks to storage. The REST API cannot CREATE TABLE, so structure lives in `supabase_schema.sql`, run manually in the Supabase SQL Editor; a schema change means editing that file AND telling the user to re-run it (idempotent). Joins/aggregates are views in that file — PostgREST cannot express them.
- **Secrets come from `st.secrets` (Streamlit Secrets): `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `ANTHROPIC_API_KEY`. Never generate or read `.env` files** — the user has no local dev environment. Full setup: `DEPLOY.md`.
- **Never invent content**: topics, speakers, texts, dates, contact details, budget figures. Unknown stays `TBD`. Never propose a speaker who is not alive and active.
- **Git:** all development on `claude/mishmer-generator-setup-h5gxqx`. **`main` is empty** — Streamlit Cloud deploys from the working branch. Commit and push when a piece of work completes.

## Where the detailed knowledge lives

Path-scoped rules load automatically when their files enter context:

- `.claude/rules/database.md` — the 12 tables, RLS/service_role, views, name normalisation, the outreach log, derived deadlines, and the local-PG16 verification harness.
- `.claude/rules/ui.md` — RTL mechanics, the rerun trap, the design system, phase-driven UI, query budgets, date formats, Playwright verification.
- `.claude/rules/pedagogy.md` — what a Mishmar is, ideal vs. real format, the content rules (dead-thinker trap, ⚠️ לאמת, no invented contacts), the archive's traps, speaker-search throttling, the image workflow.
- `.claude/rules/chat-agent.md` — the Mishmar-scoping rule and the four cost ceilings that keep a chat turn flat.

**`system_rules.md` is the operating layer** — read it when acting as the programme's assistant rather than as a repo developer. `.claude/skills/` holds the programme's recurring workflows; `.claude/agents/` holds the specialized subagents (speaker-scout, topic-ideation, lesson-builder, app-reviewer, archive-diver).

## Repository structure

```
app.py                 # Streamlit UI (render only; global chat panel; phase-driven)
data_manager.py        # the ONLY data seam — Supabase REST, seeding, phase model
chat_agent.py          # Sonnet 5 + 10 tools; generator prompt as system prompt
speaker_search.py      # discovery (mines names) + verification, throttled
archive.py             # cross-year memory over 2025-26 work-files
supabase_schema.sql    # tables, views, RLS + GRANTs — run in Supabase SQL Editor
system_rules.md        # operating layer: roles, pedagogy, speaker mandate, budget
students_tasks.md      # seed data read on first run
Mishmer-section/       # generator prompt · templates · speakers · 2025-26 archive · 2026-27 season
Invitations/           # house style, watercolor prompts, past posters
```
