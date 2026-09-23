# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Hebrew Shabbat-preparation system for מדרשת עין פרת. Everything user-facing is Hebrew
and RTL. Work happens on the `Shabbat` branch. See `README.md` for the user-facing guide.

## Commands

```bash
python3 tools/guide.py                           # docs/מדריך לאחראי שבת.pdf|png (student checklist; exits 1 if not one page)
python3 tools/form_page.py                       # docs/index.html (the leaders' form; --demo separate|early|late --out X for a filled test page)
python3 tools/import_form.py < message.txt       # the form's message → attendance/preps/menu/weeks (--dry-run)
python3 tools/shabbat.py 2026-10-16              # the whole week: build → new_shabbat → assign → export → zip → checks (--check: checks only)
python3 tools/build_workbook.py                  # data/*.csv → shabbat-planner.xlsx (only when the schema changes)
python3 tools/new_shabbat.py 2026-09-18          # template → shabbatot/2026-09-18.xlsx
python3 tools/new_shabbat.py 2026-09-18 --from shabbatot/2026-09-04.xlsx   # carry last week's edits forward
python3 tools/attendance.py 2026-09-18 < names.txt   # paste-in roster matching (--all, --show, --file)
python3 tools/assign_groups.py 2026-09-18        # fills names (--dry-run, --seed, --max-stages, --file)
python3 tools/export_pdf.py 2026-09-18           # PDFs+PNGs (--only flyers|shadow, --no-png, --with-recipes adds the method)
python3 tools/zmanim.py 2026-09-01 2027-09-01    # regenerate data/zmanim.csv
python3 tools/fetch_fonts.py                     # refill assets/fonts/ (already committed)
```

There is no test suite and no linter. `tools/shabbat.py` runs the standing checks after every
pipeline run and exits 1 on any problem; see also "Verifying changes".

**Weekly input** comes from the student leaders through the **form page** — `docs/index.html`, a full
standalone document built by `tools/form_page.py` from `tools/form_page.html` (roster, the closed Shabbatot of
`data/shabbatot.csv` with their staff, book and computed schedule, and recipe names embedded as JSON) and served
by **GitHub Pages** from the `Shabbat` branch `/docs` folder: https://urishav464.github.io/Ein-Prat-work/ —
rebuild and push to update it. (A claude.ai Artifact was tried first: it does not open for people without a
Claude account; the old artifact now only points to the Pages URL.) The page composes one structured message
(`📋 טופס שבת v2 · <date>`, header lines `שנה א'` / `תנורים` / `מילא/ה`, then `— section —` blocks whose lines
are `key: value` pairs joined by ` · `) that the leader sends by WhatsApp. `tools/import_form.py` parses it with
no guessing into `data/attendance|preps|menu|schedule|recipes/<date>.csv`, `data/weeks.csv` and new dishes in
`data/recipes.csv`; «שינויים נוספים בלו"ז» free text is printed for manual handling. An old-format message
(no `v2`) still imports, with a warning. If the message format changes, change the page's `message()` and
`import_form.parse/build` together and re-run the end-to-end check (below). Staff names in the form (tish /
shiur) are the educators of `shabbatot.csv` «אנשי צוות» — never matched against the student roster (first
names collide); the student Shabbat team is the `צוות שבת` column of `data/students.csv`.
`docs/מדריך לאחראי שבת.png` (`tools/guide.py`) is the leaders' checklist.

**Per-date files keep old Shabbatot reproducible** — never edit another date's preps/menu/schedule to
change this week. `bw.task_rows(date)` / `bw.plan_rows(date)` / `bw.schedule_rows(date)` / `bw.recipe_rows(date)`
compose standing + weekly data; `new_shabbat.py` writes them into the Shabbat file, so `build_workbook` stays
date-free (the template is a separate week without optional events).

## Architecture

A pipeline where each stage owns one artifact and nothing reaches back upstream;
`tools/shabbat.py` runs the whole week in order and then checks it.

```
form page ──message──▶ import_form ──▶ data/attendance|preps|menu|schedule|recipes/<date>.csv, weeks.csv
 (docs/index.html, Pages)                data/shabbatot.csv: closed Shabbatot, staff, book, site times
                                                        │
data/*.csv (standing) ──build_workbook──▶ shabbat-planner.xlsx (date-free template)
                                                        │
                    new_shabbat <date> ──▶ shabbatot/<date>.xlsx   (schedule, tasks, groups, menu, recipes, times)
                                                        │
                    assign_groups <date> ──▶ names + data/duty_history.csv rows for <date>
                                                        │
                    export_pdf <date> ──▶ shabbatot/<date>/*.pdf|png  ──shabbat.py──▶ zip + checks
```

**`tools/build_workbook.py` is the schema module.** Every other script does
`import build_workbook as bw` and addresses cells through its constants — sheet names
(`SH_TASKS`…), column indices (`T_*`, `G_*`, `S_*`, `H_*`, `L_*`), row origins
(`TASK_FIRST_ROW`…), header cells (`SCHED_DATE`, `SCHED_CANDLE`, `SCHED_HAVDALAH`), plus
`STAGES`, `HISTORY_FIELDS`, `read_history`, `write_history_row`, `read_schedule_template`,
`suggested_time`, `suggestion_formula`. It also composes each date's data — `read_week`, `read_shabbat`,
`tags_for`/`applies`/`week_tags`, `schedule_rows`/`active_events`/`event_times`, `task_rows(date, times)`,
`plan_rows(date)`, `recipe_rows`/`match_recipe`, `read_zmanim`/`zmanim_for`, `week_leaders`, `resolve_hour`,
`expand_catering` — and owns the writers (`write_task_row`, `write_group_row`, `write_menu_row`,
`write_schedule`, `write_recipes`) that both the template build and `new_shabbat` use. Changing a sheet's columns
means editing the constants there and nowhere else; never hard-code a column number in another
file. `data_cell` assigns `.value` explicitly because `ws.cell(value=None)` does **not** clear a
cell — writing a Shabbat's shorter task list over the template relies on that.

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
`ROUND`, `ROUNDUP`, `TIME`); round times with `ROUND(x*288)/288` rather than `CEILING` on a time
value; data validation from a **range** rather than an inline list (an inline list is
capped at 255 chars and Excel drops it silently); no hidden helper columns; sheet names
without quote characters. Cell fills carry meaning: yellow = user fills, turquoise = a
script writes, grey = computed.

### Scheduling model

- **The task is the unit.** A task row carries stage, day, hour, group, how many people
  («אנשים»), and the assigned names. Group size is *derived*: the peak number of people
  needed simultaneously (`peak`/`slots_of` in `assign_groups.py`). A task with no hour
  means the whole group.
- **Week kind.** `bw.tags_for(shared, ovens, …)` gives a week its tags: `נפרדת`/`משותפת`, `תנורים כל היום`
  (separate, or shared with no window — like 2026-09-18) / `תנורים עד 11:00` / `תנורים מ-11:00`, and for each
  optional event its name or `בלי <name>`. The `תנאי` column (`;` = OR) of `schedule_template.csv`,
  `task_library.csv` and `group_plan.csv` selects rows by tag — that is how the Friday בית מדרש / Friday
  dining-room group, the Motzash cleanings, the work start (08:00/11:00) and the קבלת שבת ישראלית place change
  per kind. `HELP_RULES` picks who joins the preps and when (בית מדרש 08:45 / 10:00, dining room +0);
  `LUNCH_RULES` starts Friday-lunch cooking at 09:00 when our ovens are from 11:00. `import_form` must call
  `tags_for` with the message's values, because `weeks.csv` is written after `build()`.
- **Four stages** (`bw.STAGES`, the last is תורנות מוצ"ש) order the work. A person takes at most one group per
  stage and at most `--max-stages` stages overall, and `assign_all` additionally blocks
  any candidate whose already-assigned `(day, hour)` slots collide with the new group's —
  that is what keeps the 08:00 Friday preps and the 08:00 בית מדרש duty disjoint.
- **Points live on the group, not the task** (`ניקוד` in `data/group_plan.csv`): each duty
  is worth its points once. `data/duty_history.csv` stores one row per person per duty, and
  candidates are ranked by historical + already-earned-this-week points, lowest first.
- **Per-Shabbat overrides** all live in `data/attendance/<date>.csv`: `זמין לתורנות`,
  `לא זמין בשלב` (stage exclusions, `;`-separated), `שיבוץ ידני` (pins, `;`-separated),
  `אחראי על` (pin + this group's אחראי/ת, student or staff — suppresses the automatic
  staff pick for that group), `צוות שבת` (extra staff for that week; standing staff is the
  `צוות שבת` column of `students.csv` — staff become a group's אחראי/ת, count inside the group
  size and stay out of ordinary slots unless pinned), `לא בקבוצה` (groups the ranking never puts
  this person in — the havurot presenters are kept out of ארוחת צהריים שבת; pins still win; automatic
  staff leads skip blocked groups, and the group with the fewest eligible staff picks first). A pin or leader
  role in a *later* stage is a commitment: its `(day, hour)` slots are reserved and its
  points are added to the person's ranking score in earlier stages, so stage order can't
  silently defeat a pin. Elul students are spread across groups by ratio.
- `shrink_to_fit` reduces the largest tasks when there are not enough available people.
- **Time rules chain.** A schedule row's `בסיס` may be another event's name *on the same day*
  (טיש = סעודת שבת + 90; the Motzash events therefore sit on day `שבת`), resolved in definition order by
  `bw.schedule_rows`, which then sorts by `event_sort_key` (day, time; before 05:00 counts as after
  midnight). `עיגול` rounds *up* to that many minutes (formula path: `ROUNDUP(ROUND(x*1440,0)/step,0)*step/1440`,
  never CEILING on a time); `לא לפני` is a floor (סעודת שבת ≥ 19:00; formula `IF(ref="","",MAX(TIME(…),core))`
  — the MAX must stay inside the IF). Candle/havdalah come from `bw.read_zmanim()`: `zmanim.csv` (computed for
  Jerusalem) overridden by the yeshiva.org.il Kfar Adumim times in `shabbatot.csv`; `new_shabbat` writes them
  into the file's «זמנים» row so export and formulas agree.
- **Weekly schedule** (`data/schedule/<date>.csv`): a row matching a template `(יום, אירוע)` turns an optional
  event on (סעודה שלישית, ערב חברה, ערב חמישי — the latter also turns on when a prep anchors to it) and
  overrides non-empty fields (a time override is always `בסיס=קבוע`, `היסט=HH:MM`); `פעולה=בטל` removes an
  event (an error if another event is based on it); an unknown name is a new event («שיעור של X»).
  `{ספר}` / `{שם}` in place/note come from `shabbatot.csv`. Rows with `מקור=טופס` belong to `import_form`,
  which replaces only those. With a date, a task whose anchor is a known event that is off this week is
  dropped (and `plan_rows` drops standing groups left with no tasks); unknown anchors are kept so the
  anchoring check still catches typos. A task's
  `שעה` may be relative to its anchor (`-30`, `+0`), resolved by `bw.resolve_hour` in
  `new_shabbat` from the static hours it just wrote — so pre-Shabbat tasks (oven at candle −60)
  stay before candle-lighting in winter.
- **Weekly preps** (`data/preps/<date>.csv`): a prep name that is not a standing group becomes a
  new group (stage הכנות שישי, `PREP_POINTS`), listed before the standing groups; a row for a
  standing group *replaces* that group's standing task with the same `(group, day, raw hour, anchor)` and
  inherits its empty fields (that is how the Motzash dinner menu or cleaning sizes change — `import_form`
  copies the library row's hour and anchor via `library_slot`). Defaults: day שישי, hour `+0` from
  «תחילת עבודה» (challot `-60`), anchor `bw.prep_anchor`, text «הכנה — כמות». `עזרה = N` (legacy column
  `עזרה מבית המדרש`) adds a join-the-prep task per `HELP_RULES`, placed right after that group's rows.
  `אחראי` becomes the group's leader (merged with attendance `אחראי על`).
- **Menu placeholders.** Task text may contain `{ארוחה}` or `{ארוחה|ברירת מחדל}`;
  `build_workbook.expand_catering` joins that meal's rows from `data/menu/<date>.csv`, falls back to
  the default, and otherwise warns and leaves the braces (which `shabbat.py` fails on).
  The `מתכון` column is expanded too (`sep=";"`) and then filtered to dishes that have a recipe this week
  (`recipe_rows(date)` = `recipes.csv` overlaid by `data/recipes/<date>.csv`; `match_recipe` = exact or unique
  containment), so an unknown salad stays in the text with a warning instead of failing the checks.
  Notes prefixed `[משותפת]` survive only when `weeks.csv` marks the Shabbat shared; shared
  Shabbatot also get `PREP_NOTE` (plus «התנורים שלנו …») on Friday prep rows.

### Rendering

`export_pdf.py` builds HTML and drives headless Chromium (`CHROME_CANDIDATES`, resolved
under `/opt/pw-browsers/`) with `--print-to-pdf` and `--screenshot`. Fonts are embedded as
base64 data URIs from `assets/fonts/` so rendering never touches the network.
`--virtual-time-budget` is required or Chromium captures before layout settles. Pages are
fitted by measuring first: `measure_page` is a `--dump-dom` pass where an inline script sets
`document.title` to `FIT:<ratio>|AVAIL:<px>|CHROME:<px>|ROWS:<h,h,…>`; the ratio is then
baked into a CSS `transform: scale()` on `.inner`. A flyer shrinks down to `FLYER_MIN_FIT`
to stay on one page. The shadow schedule goes on one page if the ratio is at least
`MIN_FIT`; otherwise `split_pages` chunks the rows by their measured heights into balanced
`.page` divs — never cutting a row, shrinking as far as `PAGE_SAVE_FIT` when that saves a
whole page — the PDF carries them all, and each page is re-rendered on its own into
`לוז צל <n>.png` so a single page can be sent as an image. Continuation pages repeat the
day heading and are labelled «עמוד n מתוך m». PNGs are shot with `ep.shot_binary()` (the
`headless_shell` build): the full `chrome` binary paints only ~1036 of a 1123px window, which silently
cut the bottom ~23mm (last rows, footer) off every image. The shabbat title («שבת סטודנטים», cell
`bw.SCHED_TITLE`) is prefixed to `when_line` on flyers and the shadow schedule.

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
- **Assignment:** `shabbat.py` (or `--check`) runs the standing invariants — no name twice in
  one `(day, hour)`, blocked people absent from their stages and blocked groups, every member has a
  task and every group has tasks, tasks only in planned groups, every staff-led group has a leader,
  every task anchored, no leftover `{…}` (task or recipe), every recipe dish in «מתכונים», one-page
  flyers; plus warnings (events without an hour / out of order, a closed Shabbat without tish leader or
  havurot presenters). Expected diff when re-running 2026-09-18 on a scratch copy: only ניקיונות
  19:40→19:45 and the two new Motzash events (ארוחת ערב מוצ"ש, כריכה לכריכה).
  To show a refactor changes nothing, snapshot the tasks/groups/events of an existing date via
  `export_pdf.read_workbook`, re-run that date and diff.
- **Re-running a past date is destructive.** It rewrites `shabbatot/<date>*` (already sent to
  the students) and replaces that date's rows in `data/duty_history.csv`. Test on a copy or
  restore afterwards: `git checkout -- shabbatot/<date>.xlsx shabbatot/<date>/ data/duty_history.csv`
  and `git clean -fd shabbatot/<date>/`. Test weeks for future dates must be removed again:
  `data/{attendance,preps,menu,schedule,recipes}/<date>.csv`, `shabbatot/<date>*`, and
  `git checkout -- data/weeks.csv data/recipes.csv data/duty_history.csv shabbat-planner.xlsx`
  (the import edits weeks.csv and recipes.csv in place — demo dishes would leak into the form's datalist).
- **`export_pdf` deletes every PDF/PNG in the output folder first**, so `--only flyers` also
  removes the shadow schedule — finish with a full export before committing.
- **Phone-width screenshots:** headless Chromium will not lay out narrower than ~485px whatever
  `--window-size` says; frame the page in a 390px `<iframe>` inside a wider window instead.
- **The form page** (`docs/index.html`) is checked end to end per week kind: `form_page.py --demo
  separate|early|late --out X`, `--dump-dom` (the demo writes `problems()` into `<pre id="check">`, which
  must be empty, and the message into `<textarea id="out">`), then `import_form.py` and `shabbat.py` on the
  demo date (2026-10-16 — it must still be a future closed Shabbat, or change `demo_state`).
