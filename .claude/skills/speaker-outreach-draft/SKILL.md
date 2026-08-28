---
name: speaker-outreach-draft
description: Draft a polite Hebrew outreach message/email to a potential speaker for a specific Mishmar topic, and log the approach in the shared outreach journal once the user confirms it was sent. Use when a pair is ready to contact a speaker.
argument-hint: "[speaker-name] [mishmar-id]"
allowed-tools: Bash, Read
---

# Speaker outreach draft

## Before drafting — the shared-index check

Ten trainees search for speakers in parallel; an unupdated journal is how two pairs approach the same person without knowing.

1. `dm.get_speaker_status(name)` / `dm.get_outreach_for_speaker(id)` — has anyone already approached them this year? If yes, stop and surface it.
2. A refusal (`❌ לא יכול/ה`) is almost always for a specific date — worth trying again for a different evening; say so.
3. Several rows sharing the name = the ה7 situation — ask which person is meant, never merge.

## The draft

- Hebrew, warm and specific: who we are (מדרשת עין פרת, משמר — ערב לימוד של חמישי בלילה), the topic and why *they* fit it (their real expertise from the index row — nothing invented), the date (Hebrew + Gregorian) and time window, and an honest note about the modest budget.
- Titles rejoined for address (`dm.display_name`).
- **Never invent contact details.** If `contact` is TBD, point the user to the stored institutional URL where a human can find them — do not search for or guess emails/phones.

## After the user confirms it was sent

Log it with `dm.record_outreach("📩 נשלחה פנייה", name=..., mishmar_id=..., student_id=..., note=...)` — the ONLY writer to the journal. Handle `AmbiguousSpeaker` by asking, not choosing. Report exactly what was logged.
