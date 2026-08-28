---
name: overdue-nudges
description: List open tasks past their recommended date and draft soft reminder messages for the pairs. Use when the instructor asks who is behind, or wants nudge messages to send.
argument-hint: "[mishmar-id | all]"
allowed-tools: Bash, Read
---

# Overdue nudges

**Deadlines here are "המלצה — לא חוק".** A reminder is a soft nudge from a partner, never a warning from a system. A DONE task never nags.

## How

- `dm.get_overdue_tasks()` — open tasks past their recommended date, evaluated in Postgres (`CURRENT_DATE`), so no server-clock drift. Includes Mishmar context and owners.
- `dm.annotate_deadline(task)` — adds `days_left` and the soft `nudge` wording; reuse its phrasing.
- Group by Mishmar, then by pair. `tasks.student_id` NULL means the task belongs to both partners.

## Drafting

- Hebrew, warm, second person plural to the pair. Frame: what would help the evening, not what is late — e.g. "שווה לסגור את הנושא השבוע כדי שיישאר זמן טוב למרצים", not "המשימה באיחור".
- One message per pair covering all their overdue items, shortest path first (the current build phase's items lead).
- Include the recommended dates as context, marked as recommendations.
- The instructor sends the messages — the skill only drafts. Never send anything anywhere.
