---
name: calculate-deadlines
description: Derive or backfill recommended due dates for a Mishmar's tasks from its date (topic −21d, speakers −14d, logistics −7d). Use when tasks are missing due dates, a Mishmar's date changed, or new tasks were added in bulk.
argument-hint: "[mishmar-id | all]"
allowed-tools: Bash, Read, Grep
---

# Calculate deadlines

Deadlines in this repo are **derived, never typed**, and they are **"המלצה — לא חוק"** — recommendations, not law. Never present them as hard deadlines.

## How

Use the existing functions in `data_manager.py` — do not reimplement the offsets:

- `classify_task(text)` maps a task description to a category. Its `_CATEGORY_RULES` ordering is load-bearing (`אחרי` before `מרצים`, `לוגיסטיקה` before `תוכן`) — never reorder.
- `compute_due_date(category, gregorian_date)` applies `DEADLINE_OFFSETS_DAYS` (נושא −21, מרצים −14, הזמנה/כיבוד/קישוט −7, אחרי +7).
- `backfill_task_metadata()` fills category/due_date on tasks missing them and **never overwrites** values already set — this is the entry point for "fix all".

Run against live data with a short Python script through `data_manager` (credentials via env/`st.secrets`). In a sandbox with no Supabase, use the local-PG16 shim harness described in `.claude/rules/database.md`.

## Rules

- Never overwrite a due date a human set.
- `mishmarim.gregorian_date` is TEXT in d.m.Y (`15.10.2026`) — parse accordingly.
- After changing dates, report what changed per task; do not just say "updated".
- If a task's category is ambiguous, leave it and flag it rather than guessing.
