---
name: feedback-compiler
description: Aggregate post-Mishmar feedback and fold it into the shared speaker index (what they taught, how it went), so next year's pair sees not just that someone taught but how it landed. Use after an evening's feedback is collected.
argument-hint: "[mishmar-id]"
allowed-tools: Bash, Read
---

# Feedback compiler

Feedback is what turns the speaker index from a list of names into institutional memory.

## How

All through `data_manager`:
- `get_feedback_for_mishmar(mishmar_id)` — ratings + what worked / what didn't, per speaker and for the evening.
- Speakers recorded only on budget lines (`get_budget_speaker_names`) must be included — someone who came but never entered the running order still needs their feedback reachable.
- **Status updates go ONLY through `record_outreach()`** — the single writer to the shared log. Never set a status field directly; that is exactly the bug that once left the shared index stale.
- Statuses are the Hebrew ladder in `data_manager.SPEAKER_STATUSES` (`⬜ לא פנינו` · `📩 נשלחה פנייה` · `✅ סגור` · `❌ לא יכול/ה` · `⚠️ בתנאי`) — never English labels like "Do not invite". `⏳ ממתין לתשובה` was merged into `📩` in schema v2; do not reintroduce it.

## Rules

- Summaries quote the feedback's substance ("החבורה התפזרה אחרי 20 דקות") rather than flattening to a score.
- Negative feedback is recorded factually in the speaker's notes, not as a verdict — the decision to re-invite belongs to humans.
- If several index rows share the speaker's name, `resolve_speaker` raises `AmbiguousSpeaker` — ask which person is meant; never merge.
- Report exactly what was written where.
