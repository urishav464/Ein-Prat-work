---
paths:
  - "Mishmer-section/**"
  - "Invitations/**"
  - "system_rules.md"
  - "students_tasks.md"
---

# The Mishmar — pedagogy, content rules, and their traps

A **Mishmar** is Midreshet Ein Prat's Thursday-night study seminar, 20:30–02:00. This repo is scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**: 21 Mishmarim, 10 trainees building them in pairs. `system_rules.md` is the operating layer — read it when acting as the programme's assistant rather than as a repo developer.

## Ideal vs. reality

**The generator prompt (`Mishmer-section/generator/mishmar-generator-prompt.md`) describes an idealized 4-lesson Logos→Pathos arc** — Foundation (20:30) → Conflict (22:00) → Twist (23:30) → Soul (01:00). Real Mishmarim rarely follow it: some have three lessons, some are ceremonial, some are song circles, and roughly half of a real work-file is logistics — decoration, shopping list, a themed dinner. **The actual operating format is `Mishmer-section/templates/mishmar-workfile-template.md`**, reverse-engineered from the five real 2025-26 documents. Help a student who wants to deviate; never tell them a three-lesson Mishmar is wrong. **The app's default evening skeleton is the real format** — 20:00, three 75-minute lessons with breaks, an hour of חבורות — while the generator prompt keeps the 4-lesson arc as the *pedagogical* ideal; the two coexist deliberately.

## Content rules — non-negotiable

- **Never invent content.** Topics, speakers, texts, dates, contact details, budget figures. Unknown stays `TBD`. Contact details are never scraped from search results — store the institutional URL where a human can find them.
- **Never invent a speaker — but never narrow to the database either.** The index is a growing set, not the candidate set. Every proposed name needs a source; a name from model knowledge carries `⚠️ לאמת` plus the checklist (alive? active? where? already approached this year?).
- **The dead-thinker trap:** the generator prompt is full of Spinoza, Levinas, Kafka, Agnon, Rav Kook — those are **texts to study, not people to invite**. Never propose someone who is not alive and active.
- **Flag inconsistencies, don't silently fix them.** Same-named people are never merged on our judgment (the ה1–ה7 collision flags; `AmbiguousSpeaker` enforces this in code). Three documents word the outreach ladder differently — the code follows the work-file template and the divergence stays flagged.
- **Deadlines are "המלצה — לא חוק"**, per the opening deck. Trainees see a soft nudge; a DONE task never nags; only the instructor treats a passed date as actionable.
- **Budget is tracking, not enforcement.** ₪500 per Mishmar is an average covering speakers *and* refreshments. Overrun draws from the season-wide line; there is deliberately no ceiling. Report — never alarm.

## Conventions

- **Language:** file and folder names in English, all content in Hebrew.
- **Dates:** always Hebrew + Gregorian together (`כ״א אלול תשפ״ו | 3.9.2026`).
- `Mishmer-section/2026-27/schedule.md` is the source of truth for the 21 dates, types and responsible pairs.

## The archive (`Mishmer-section/2025-26/`)

Cross-year memory — five real work-files, verbatim, plus feedback. Two traps already hit: **this season's (2026-27) folders are unfilled templates and must not be searched as history**, and every work-file inherits a status legend containing `ממתין לתשובה`, so an unfiltered search for a תשובה Mishmar matches all 21 templates — strip boilerplate before matching (`archive.py` does).

## Speaker search

The digest in the generator prompt must never contain phone numbers or emails — it travels to external chat windows. `speaker_search.py` has two first-class paths: `search_candidates()` **discovers** (mines new names from broad queries incl. `site:ac.il` — this is what surfaces a lecturer no model has heard of), `verify_speaker()` **verifies** one name against the `⚠️ לאמת` checklist. **The burst, not the volume, trips DuckDuckGo's limiter** (~25 queries in 3 minutes), hence: Supabase cache (60 days success, **1 hour failure** — or one blocked afternoon poisons the cache for the season), a 4s module-level throttle, a 60s→5m→15m cooldown ladder, backend rotation, and soft-fail to clickable manual-search links. Search the `notes` column, not just `expertise_topics` — "מה העביר אצלנו" lands in notes and is often the strongest topical signal.

## Images (no image generation available)

Claude cannot generate images here, and this cannot be automated away: Claude writes a prompt from `Invitations/prompt/base-prompt.md`; **the user generates the image externally and uploads it** (chat-pasted images are not persisted — GitHub upload or `git push` only); Claude composes the invitation from the uploaded file. Exception: an existing background from `Invitations/examples/`. Never suggest filters (sharpen, upscale) as a substitute for actually generating watercolor artwork. Invitation HTML embeds all fonts as base64 woff2; render to PNG with the pre-installed Playwright/Chromium (do not run `playwright install`).
