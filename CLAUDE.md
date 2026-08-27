# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The educational toolkit for Midreshet Ein Prat.

**Direction (current):** the Mishmar programme is moving from local Markdown tracking to a **Streamlit web app** (Python frontend + backend), scoped strictly to **שנה ב' תשפ"ז (5787 / 2026-27)**. See `system_rules.md` for the app's architecture, roles, speaker-discovery mandate and budget model. No application code exists yet — the Markdown files below are still the live data, and are what the app will read and write through a single data seam.

Everything else here remains a **content and documentation repository** (Markdown work-files, a generator prompt, one self-contained HTML invitation, one PPTX deck). "Building" in those areas means composing Hebrew documents and rendering HTML/PPTX to images for visual QA.

## Operating layer

`system_rules.md` (repo root) is the operating layer for the Mishmar **web app** — hardcoded scope (תשפ"ז only), roles (Instructor `Uri` / Student), the 4-lesson pedagogy, the web-search speaker mandate, the budget model, and the tracking protocol. **Read it whenever someone interacts as a student or as the instructor**, rather than as a repo developer. `students_tasks.md` (root) is the single source of truth for tasks.

The split: this file guides whoever *builds* the repo; `system_rules.md` guides whoever *operates* the programme. Sibling to `Mishmer-section/generator/mishmar-generator-prompt.md`, which is the topic-design tool.

## Conventions

- **Language:** file/folder names in English, all content in Hebrew.
- **Dates:** always give Hebrew + Gregorian together (e.g. `כ״א אלול תשפ״ו | 3.9.2026`).
- **Never invent content.** Topics, speakers, texts, and dates come from the user. Unknown fields stay `TBD` — never filled in by guessing.
- **Never invent a speaker** — but never narrow to the database either. It is a growing index, not the candidate set; web search is a primary discovery path (see `system_rules.md` §4). Every proposed name needs a source. Existing entries live in `Mishmer-section/speakers/database.md`. A name from model knowledge must carry `⚠️ לאמת` plus the verification checklist (alive? still active? where do they live?) — never asserted as fact. **Never invent contact details**; unknown ones stay `TBD`. Watch the dead-thinker trap: the prompt is full of Spinoza, Levinas, Kafka, Agnon — those are texts to study, not candidates to invite.
- **Flag inconsistencies, don't silently fix them.** If source material contradicts itself, note it and ask — don't resolve it on your own judgment. See `Mishmer-section/2025-26/mishmarim/` for the pattern (each archived work-file has an inline note where the real document had a discrepancy).
- **Git:** all development happens on `claude/mishmer-generator-setup-h5gxqx`. `main` exists only as a base for Pull Requests — don't push work there directly.

## Repository structure

```
Mishmer-section/
├── generator/mishmar-generator-prompt.md   # "Mishmar Architect" prompt — idealized 4-lesson Logos→Pathos arc
├── templates/
│   ├── mishmar-template.md                 # blank output skeleton for the generator's idealized structure
│   └── mishmar-workfile-template.md        # the REAL per-Mishmar operating format (see below)
├── speakers/database.md                    # cross-year speaker database — 44 real people, the source the generator draws names from
├── 2025-26/mishmarim/                      # archive: 5 real work-files from last year, verbatim
└── 2026-27/                                # current season
    ├── schedule.md                         # source of truth: all 21 dates, type, responsible pair/status
    ├── students.md                         # round-robin pairing tracker (placeholder names until real ones arrive)
    ├── speakers.md                         # shared speaker pool for the season (avoid double-asking someone)
    ├── topic-ideas.md
    └── mishmarim/NN-slug/
        ├── workfile.md                     # the hub: schedule, speakers, decoration (tasks live in /students_tasks.md)
        ├── draft.md                        # optional: deep planning via the generator
        ├── brief.md                        # optional: this Mishmar's special constraints
        ├── invitation.md / invitation.html
        └── sources/

system_rules.md        # operating layer: roles, philosophy, tracking protocol
students_tasks.md      # SINGLE source of truth for tasks — work-files point here, they don't hold tasks

Invitations/
├── README.md          # measured house style (font sizes as %, the translucent-panel device, real font names)
├── prompt/             # base + per-topic watercolor image-generation prompts
└── examples/           # past posters (jpg/pdf), kept as visual reference
```

**Important architectural note:** `generator/mishmar-generator-prompt.md` describes an idealized 4-lesson Logos→Pathos structure (Foundation → Conflict → Twist → Soul, external speakers for lessons 1–2, mandatory interactive closing). In practice, real Mishmarim rarely follow this exactly — some have 3 lessons, some are ceremonial (יום הזכרון), some are song circles, schedules vary. The generator is one idea-generation tool, not a mandatory template. **The actual operating format is `templates/mishmar-workfile-template.md`**, reverse-engineered from five real 2025-26 work documents. Always build new Mishmarim against the work-file template, and treat the generator as optional input for `draft.md`.

## Image workflow (no image generation available)

Claude cannot generate images in this environment. The workflow is fixed:

1. User names the Mishmar's topic.
2. Claude writes an image-generation prompt, based on `Invitations/prompt/base-prompt.md` and the variants in `Invitations/prompt/variants/`.
3. User generates the image externally and uploads it to the repo (chat-pasted images are not persisted to disk and cannot be written into the repo — must come in via GitHub upload or `git push`).
4. Claude composes the invitation from the uploaded image.

**Exception:** if the user prefers an existing background from `Invitations/examples/`, skip steps 2–3 and use it directly.

Never suggest filters (sharpen, upscale, texture) as a substitute for actually generating watercolor artwork — those are for improving an existing file, not for producing the house style from scratch.

## Repeatable techniques used in this repo

**Hebrew/Gregorian date conversion** — use `pyluach`:
```python
from pyluach.dates import GregorianDate
GregorianDate(2026, 9, 3).to_heb().hebrew_date_string()
```

**Rendering a self-contained invitation HTML to PNG** — Playwright/Chromium is pre-installed (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, do not run `playwright install`). Invitation HTML files embed all fonts as base64 `woff2` (via `@font-face`, no external CDN) so they render identically anywhere.

**Building/QA'ing a `.pptx` deck** — built with `pptxgenjs` (+ `react-icons` → `ReactDOMServer.renderToStaticMarkup` → `sharp` for icon PNGs). Requires `libreoffice-impress` and `libreoffice-writer` (not just `libreoffice-core`/`libreoffice-common`, which alone fail with "source file could not be loaded" on every conversion) plus `poppler-utils`, installed via:
```
apt-get update && apt-get install -y libreoffice-impress libreoffice-writer poppler-utils
```
QA pipeline for any `.pptx`/`.docx`:
```
python scripts/office/validate.py <file>.pptx      # OOXML schema/relationship check
soffice --headless --convert-to pdf <file>.pptx     # render
pdftoppm -jpeg -r 120 <file>.pdf <prefix>            # slide-by-slide images for visual review
markitdown <file>.pptx                               # text-content dump, e.g. to grep for leftover placeholders
```

**RTL layout in `pptxgenjs`** — there is no native RTL mode. Right-align text manually; order table columns right-to-left in the source array; for two-column grids, fill the *right* column first, top-to-bottom, to match natural Hebrew reading order; never start a Hebrew title string with a leading digit (the bidi algorithm misplaces it to the wrong visual edge — rephrase instead, e.g. "כל 21 המשמרים" not "21 המשמרים").

**Round-robin pairing schedule** (N people × M slots, no repeated pairs, balanced load, max spacing) — 1-factorization of the complete graph K_N ("circle method"). Used for `2026-27/students.md`; reusable if the season's headcount or slot count changes again.
