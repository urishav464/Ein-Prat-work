# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Hebrew Shabbat-preparation system for מדרשת עין פרת. Everything user-facing is Hebrew
and RTL. Work happens on the `Shabbat` branch. See `README.md` for the user-facing guide.

## Commands

```bash
python3 tools/build_workbook.py                  # data/*.csv → shabbat-planner.xlsx (only when the schema changes)
python3 tools/new_shabbat.py 2026-09-18          # template → shabbatot/2026-09-18.xlsx
python3 tools/new_shabbat.py 2026-09-18 --from shabbatot/2026-09-04.xlsx   # carry last week's edits forward
python3 tools/attendance.py 2026-09-18 < names.txt   # paste-in roster matching (--all, --show, --file)
python3 tools/assign_groups.py 2026-09-18        # fills names (--dry-run, --seed, --max-stages, --file)
python3 tools/export_pdf.py 2026-09-18           # PDFs+PNGs (--only flyers|shadow, --no-png, --with-recipes adds the method)
python3 tools/zmanim.py 2026-09-01 2027-09-01    # regenerate data/zmanim.csv
python3 tools/fetch_fonts.py                     # refill assets/fonts/ (already committed)
```

There is no test suite and no linter. Verification is described under "Verifying changes".

## Architecture

A five-stage pipeline. Each stage owns one artifact; nothing reaches back upstream.

```
data/*.csv ──build_workbook──▶ shabbat-planner.xlsx ──new_shabbat──▶ shabbatot/<date>.xlsx
                                                                            │
   data/attendance/<date>.csv ──attendance──▶ ──assign_groups──▶ (names written back in)
                                                                            │
                                                          export_pdf ──▶ shabbatot/<date>/*.pdf|png
```

**`tools/build_workbook.py` is the schema module.** Every other script does
`import build_workbook as bw` and addresses cells through its constants — sheet names
(`SH_TASKS`…), column indices (`T_*`, `G_*`, `S_*`, `H_*`, `L_*`), row origins
(`TASK_FIRST_ROW`…), header cells (`SCHED_DATE`, `SCHED_CANDLE`, `SCHED_HAVDALAH`), plus
`STAGES`, `HISTORY_FIELDS`, `read_history`, `write_history_row`, `read_schedule_template`,
`suggested_time`, `suggestion_formula`. Changing a sheet's columns means editing the
constants there and nowhere else; never hard-code a column number in another file.

### The formula-value constraint (most important gotcha)

openpyxl writes formulas **without cached results**, so no script can ever read a formula
cell — it comes back as the formula string, or `None` with `data_only=True`. The design
works around this rather than fighting it:

- «לוז» column **שעה** holds *static* times that `new_shabbat.py` computes in Python from
  `data/schedule_template.csv`; column **הצעה** holds the equivalent *formula*, which only
  recalculates when the user changes the date inside Excel/Sheets.
- `export_pdf.py` and `assign_groups.py` read **only static cells** (שעה, אירוע, שמות,
  the recipe columns, group membership).
- Any new derived value that a script must read has to be written by a script, not by a
  formula. `data/schedule_template.csv` is the single source for the time rules so the
  Python path and the formula path cannot drift.

### Google Sheets compatibility

The workbook is meant to be imported into Google Sheets, which constrains formulas:
basic functions only (`IF`, `IFERROR`, `VLOOKUP`, `COUNTIF`, `SUMIF`, `LEN`, `SUBSTITUTE`,
`ROUND`, `TIME`); round times with `ROUND(x*288)/288` rather than `CEILING` on a time
value; data validation from a **range** rather than an inline list (an inline list is
capped at 255 chars and Excel drops it silently); no hidden helper columns; sheet names
without quote characters. Cell fills carry meaning: yellow = user fills, turquoise = a
script writes, grey = computed.

### Scheduling model

- **The task is the unit.** A task row carries stage, day, hour, group, how many people
  («אנשים»), and the assigned names. Group size is *derived*: the peak number of people
  needed simultaneously (`peak`/`slots_of` in `assign_groups.py`). A task with no hour
  means the whole group.
- **Three stages** (`bw.STAGES`) order the work. A person takes at most one group per
  stage and at most `--max-stages` stages overall, and `assign_all` additionally blocks
  any candidate whose already-assigned `(day, hour)` slots collide with the new group's —
  that is what keeps the 08:00 Friday preps and the 08:00 בית מדרש duty disjoint.
- **Points live on the group, not the task** (`ניקוד` in `data/group_plan.csv`): each duty
  is worth its points once. `data/duty_history.csv` stores one row per person per duty, and
  candidates are ranked by historical + already-earned-this-week points, lowest first.
- **Per-Shabbat overrides** all live in `data/attendance/<date>.csv`: `זמין לתורנות`,
  `לא זמין בשלב` (stage exclusions, `;`-separated), `שיבוץ ידני` (pins, `;`-separated),
  `צוות שבת` (staff who become the group's אחראי/ת, counted inside the group size and kept
  out of ordinary slots). Elul students are spread across groups by ratio.
- `shrink_to_fit` reduces the largest tasks when there are not enough available people.

### Rendering

`export_pdf.py` builds HTML and drives headless Chromium (`CHROME_CANDIDATES`, resolved
under `/opt/pw-browsers/`) with `--print-to-pdf` and `--screenshot`. Fonts are embedded as
base64 data URIs from `assets/fonts/` so rendering never touches the network.
`--virtual-time-budget` is required or Chromium captures before layout settles. The shadow
schedule first runs `measure_shadow` (a `--dump-dom` pass where an inline script sets
`document.title` to `FIT:<ratio>|AVAIL:<px>|CHROME:<px>|ROWS:<h,h,…>`). If the ratio is at
least `MIN_FIT` the whole schedule goes on one page, baking the ratio into a CSS
`transform: scale()`. Otherwise `split_pages` chunks the rows by their measured heights
into balanced `.page` divs — never cutting a row — the PDF carries them all, and each page
is re-rendered on its own into `לוז צל <n>.png` so a single page can be sent as an image.
Continuation pages repeat the day heading and are labelled «עמוד n מתוך m».

### Hebrew data conventions

CSV headers and dict keys are Hebrew strings (`row["קבוצה"]`, `row["ניקוד"]`). CSVs are
read and written as `utf-8-sig`. Name matching for pasted lists goes through
`roster.match_name` (exact → word containment → difflib 0.8) with hard-coded fixes in
`roster.CANONICAL`; add a mapping there when a recurring spelling variant fails.

## Verifying changes

- **Formulas:** LibreOffice does not work in this environment. Evaluate with the `formulas`
  package on a *reduced* copy of the workbook — drop unrelated sheets, unmerge cells, and
  blank unused rows first, or it hangs. Compare each computed value against the static
  value a script wrote for the same thing.
- **Layout:** render and actually look at the PNG. Count PDF pages by regexing the bytes
  for `/Type\s*/Page[^s]` (pypdf is broken here — its `cryptography` dependency fails).
- **Assignment:** re-run with the previous week's pins and confirm the roster is unchanged;
  then check no name appears twice in one `(day, hour)` slot, every group member has at
  least one task, and blocked people are absent from the stages they are blocked from.
