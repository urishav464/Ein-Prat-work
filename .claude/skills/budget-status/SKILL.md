---
name: budget-status
description: Report a Mishmar's (or the season's) spending against the ₪500-per-Mishmar indication, and suggest how to split between speakers and refreshments. Reports — never alarms. Use for any budget question.
argument-hint: "[mishmar-id | season]"
allowed-tools: Bash, Read
---

# Budget status

**The programme's principle, stated in the opening deck and `system_rules.md`: ₪500 per Mishmar is an average *indication* covering speakers AND refreshments together. There is deliberately no ceiling. Overrun is NOT an error** — it draws from the season-wide line and cheap evenings balance it.

So this skill **reports and never alarms**. The correct tone for an over-indication Mishmar is: "מעל האינדיקציה — לידיעה, לא לדאגה."

## How

Read through `data_manager` only:
- `get_budget_summary()` — season totals, per-Mishmar totals, `over_nominal` list.
- `get_budget_speaker_names(mishmar_id)` — speakers on budget lines (people who came but may never have entered the running order).
- `budget_used` is a **view**, never a stored column — do not try to write it.

## Output

- Per Mishmar: spent so far, split speakers/refreshments/other, position vs the ₪500 indication (neutral wording).
- Season: total spent vs `21 × 500` as context, list of over-indication evenings framed as information.
- Planning help, if asked: a reasonable default split is speaker travel/fee first, refreshments from the remainder — but note that many speakers come as volunteers (0 ₪ is common in the data).
- Never invent figures; missing amounts stay unknown, not estimated.
