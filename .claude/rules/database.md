---
paths:
  - "data_manager.py"
  - "supabase_schema.sql"
---

# Data layer — Supabase through one seam

**`data_manager.py` is the only data seam.** Nothing else talks to storage. Storage is **Supabase** over its REST API (PostgREST).

**The two-file split is forced by the platform: the REST API reads and writes rows but cannot CREATE TABLE.** Structure lives in `supabase_schema.sql`, pasted once into the Supabase SQL Editor. A schema change means editing that file *and* telling the user to re-run it — it is idempotent, so re-running is safe.

**Anything needing a join or an aggregate is a VIEW in that file**, because PostgREST cannot express one: `v_speaker_status`, `v_mishmar_budget`, `v_overdue_tasks`, `v_student_progress`, `v_outreach_full`, `v_tasks_full`. Python reads views and never assembles a join itself.

**Fifteen tables.** `mishmarim`, `students`, `assignments`, `tasks`, `budget`, `speakers`, `speaker_outreach`, `lessons`, `lesson_speakers`, `logistics_items`, `speaker_searches`, `feedback`, `chat_messages`, `search_cache`, `app_meta`.

**Two schema-change rules, both learned the hard way.** (1) Adding a column to a table that a view reads via `t.*` requires `DROP VIEW IF EXISTS` before the recreation — `CREATE OR REPLACE VIEW` cannot insert a column mid-view, so the second (idempotent re-)run of the file fails. The view section drops all six before creating them. (2) **Every `ALTER TABLE … ADD COLUMN` lives in section 4ב, ABOVE the views.** A view built before the column exists silently omits it from `t.*` on a first run — `tasks.details` shipped that way and reached the app only after the file was run a second time. Proven on a fresh PG16: old order → no `details` in `v_tasks_full`; current order → `details` and `lesson_id` present on the first application.

**The read cache (why a click is one run and almost no network).** Every pure read in `data_manager` is wrapped in `st.cache_data(ttl=CACHE_TTL_SECONDS)` — 900 s; it was 120 until the reviewer measured the first click after every two-minute pause as a cold run (7 queries, 1.1 s → 2 queries, 0.33 s). In-app writes invalidate at once; only writes made outside the app (SQL Editor, a migration) wait up to 15 minutes, or a reboot — at the bottom of the module (`_READS`), and every write is wrapped to invalidate (`_WRITES`) — **by table**: each read declares the base tables it depends on (views expanded), each write the tables it touches, and a write clears only the intersecting reads. A ✓ on a task therefore refills `v_tasks_full` and nothing else (asserted in the harness: `[update tasks, select v_tasks_full]`). Rules that follow: (1) **no write may bypass the seam** — the raw `dm._t("lessons").update` calls that lived in app.py became `set_lesson_duration` / `add_lesson_slot` / `add_break` / `delete_lesson_candidate`; a new write function must be added to `_WRITES` or the UI shows stale rows for up to two minutes. (2) A write that reads first must invalidate first — `recompute_lesson_times` clears `lessons` before reading, because `create_default_timeline` inserts rows and then calls it. (3) Cached reads return copies, so mutating a returned dict is harmless. (4) `MISHMAR_NO_CACHE=1` switches it off for scripts that write around the seam (the seeding harness inserts through `_t` and calls `_invalidate()` by hand). Streamlit Cloud is one process, so invalidation is global across all trainees.

## Security decisions that are not obvious from the DDL

- **RLS is on for every table with no policies at all.** `anon` and `authenticated` get nothing; `service_role` is what the app uses. **This makes the key type load-bearing — an anon key produces a permission error, not an empty result.**
- **`GRANT` to `service_role` is explicit in the schema.** `BYPASSRLS` bypasses policies, NOT table privileges — without the GRANT block, even the right key gets `42501 permission denied for table`, which looks exactly like a wrong key. A `SELECT` blocked by RLS returns zero rows; an error means privileges.
- `storage_ready()` separates the failure modes because each needs a different fix: PGRST125 = URL carries `/rest/v1` (the client appends it itself); 42501 = missing GRANT or anon key; PGRST301 = rejected key; PGRST205 = schema never installed. `describe_key()` reads the role claim out of the key locally (legacy JWT payload, or `sb_secret_`/`sb_publishable_` prefix) so the message names the actual role instead of guessing.
- **Every view must carry `WITH (security_invoker = true)`** — a new view without it is flagged CRITICAL by Supabase's linter, and rightly so.

## Names

- **A title is not part of a name.** `speakers.title` holds ד״ר / הרב / פרופ׳. `split_title()` separates on the way in, `display_name()` rejoins for display.
- **`name_norm` is a generated column, not Python.** A PostgREST filter cannot call `REPLACE`. Without the Hebrew-gershayim folding, a trainee typing `ד"ר` both misses `ד״ר` *and* causes a second row to be created for the same human.
- **`resolve_speaker()` raises `AmbiguousSpeaker` rather than guessing** when several rows share a name. Callers must ask which person is meant. (Flag ה7 was closed only because Uri identified himself; the principle stands.)

## Writes

- **Outreach is a log, not a field.** `speaker_outreach` records each approach; current status is derived by `v_speaker_status` from the newest row. **`record_outreach()` is the only writer** — `upsert_lesson()` delegates to it rather than setting `speaker_status` itself. Before this, closing a speaker wrote only to one Mishmar's lesson row, the shared index never learned, and the next pair got a stale answer.
- **Task deadlines are derived, never typed.** `classify_task()` maps text to a category and `compute_due_date()` offsets from the Mishmar date (topic −21d, speakers −14d, invitation/refreshments/decoration −7d). Two ordering rules in `_CATEGORY_RULES` carry weight: `אחרי` before `מרצים` (so "עדכון מאגר המרצים" is not dated two weeks early) and `לוגיסטיקה` before `תוכן`.
- **`tasks.student_id` is nullable** — NULL means the task belongs to the Mishmar, i.e. to both owners in the pair.
- **`lessons` is deliberately not four rows** — `slot_order` is 1..N, `lesson_role` free text (the archive holds ceremonies and song circles).
- **`budget_used` is a view**, never a stored column.
- **Seeding does not archive `students_tasks.md`** — the checkout is rebuilt from git on every deploy, so an `app_meta` flag guards the seed instead of a rename.
- **The season's pairs are generated, and the generator owns five files.** `scripts/assign_trainees.py` (seed 5787, fixed restart count → deterministic, re-running produces no diff) draws the 19 trainee Mishmarim (#03–#21, 38 seats) over the **eight** trainees as 6×5 + 2×4, and writes `migrations/2026-09-assign-trainees.sql` (one transaction; `UPDATE students` by a **frozen** name→id map, `DELETE` the retired ids, `DELETE FROM assignments` for #03–#21, `INSERT … ON CONFLICT DO NOTHING` ×38 — idempotent) **and** the owners in `Mishmer-section/2026-27/schedule.md`, `students.md`, and in `students_tasks.md` BOTH the «אחראים» lines and the index table, so the seed, the docs and the database agree. Four things about it are load-bearing:
  · **`STUDENT_IDS` is frozen, never re-derived.** The ids are already the live database's truth and `students.id` is referenced by assignments, outreach, feedback and tasks; re-shuffling them renames every row and quietly moves one person's history onto another. **id 4 (איתי בן יהודה, left in September) is retired and never reused.**
  · **The spacing rule is calendar days, not slot counts.** `MIN_BUILD_DAYS = 21`, measured on the dates **parsed out of `schedule.md`** — the evenings are not evenly spaced (#03→#04 and #15→#16 are a fortnight apart). 21 is the app's own topic deadline: at the old 14-day spacing a pair's next topic was due a week before their current evening happened, so they built one Mishmar out of the last week of another. Nothing above 21 has a solution for eight trainees.
  · **Human facts are declared, not patched in afterwards** — `AWAY` (a trainee who cannot take an evening) and `TOGETHER` (two who must share exactly one). The assertions re-check every rule on the result, so a constraint that breaks one fails the run.
  · **`PREFERRED` is the draw's preference, not a constraint**: the pairing the trainees were last told, so the evenings that can stay, stay. It is frozen in the script rather than read back out of `schedule.md`, or a second run would read its own output and could drift.
  **A fresh database needs no SQL**: `parse_tasks_md` takes any name from the index table's first cell and links an owner whenever it resolves to a student — it used to accept only `חניך N` in both places, so after the names were written in, a first-run seed produced ten placeholders and zero assignments (proven on a fresh PG16: the students, 38 links, 2 per Mishmar; the migration on top changes nothing).
- **The evening timeline is derived, never hand-typed.** `lessons.start_time` is computed by `recompute_lesson_times()` from **`mishmarim.start_time`** (schema 9; `EVENING_START` = 20:00 is only the default) plus cumulative `duration_minutes` (breaks are ordinary rows with `is_break`); every duration edit reflows the whole evening, so slots cannot overlap. **`first_start` defaults to `None`, meaning «this Mishmar's own hour»** — that is the entire start-time feature: all six callers that reflow the clock work from the right hour without knowing the column exists. `mishmar_start(mid)` is the single reader (labels, toasts, the invitation skill); `set_mishmar_start_time(mid, "HH:MM")` is the single writer, validates the stamp and **refuses** rather than silently falling back to 20:00, and is reachable **only from the instructor's dashboard** — the whole clock of an evening hangs on it, so it is not a field a pair nudges from inside their own workfile. `create_default_timeline()` builds the real skeleton — three 75-minute lessons, 30/30/15-minute breaks, an hour of חבורות — with titles/roles/formats EMPTY by design, and both topic-close paths (form and chat tool) call it when the evening is empty.
- **Candidate speakers** (`lesson_speakers`): `add_lesson_speaker()` also teaches the shared index the person exists (manual source, phone as contact, title auto-split); candidate statuses route through `record_outreach()`; `close_lesson_speaker()` implements «סגרתי את X» — X becomes `lessons.speaker_name` with one ✅ row, the other candidates are deleted, the journal logs the close. **Phones live only in `lesson_speakers.phone` and `speakers.contact` — never in chat context or the generator digest.**
- The status ladder merged in v2: `⏳ ממתין לתשובה` folded into `📩 נשלחה פנייה` — constants AND idempotent UPDATEs in the schema file; do not reintroduce it.
- **The schema is versioned, and the app checks it.** `supabase_schema.sql` stamps `app_meta.schema_version`; `data_manager.REQUIRED_SCHEMA_VERSION` is what the code expects; `storage_ready()` returns `schema_stale` and `main()` shows a banner naming both numbers. **Bump `REQUIRED_SCHEMA_VERSION` in the same commit as any `ALTER`/`CREATE TABLE`** — without it a database one version behind looks healthy and then throws a redacted `APIError` deep inside a screen. That is exactly how a missing `logistics_items` blanked the entire workfile: the panel raised inside the right column, so the tasks column and the reset button never rendered either.
- **A missing relation degrades; everything else stays loud.** `_missing_relation(exc)` recognises only PGRST205/204/106 and "does not exist"; `get_logistics` and `get_searches_for` return empty on it and re-raise anything else. In `app.py` the three evening panels are wrapped in `_safe()` so one broken panel can never blank a column.
- **Logistics** (`logistics_items`): the refreshments list and the חבורות room allocation are the same shape — label, optional detail, done — so they share one table and `kind` (`כיבוד`/`חלל`/`אחר`) separates them. The invitation lives on `mishmarim.invitation_text`/`invitation_url`: there is exactly one per evening.
- **`reset_mishmar(mid)`** wipes an evening back to «choose a topic» — lessons (cascading `lesson_speakers`), tasks, budget, feedback, logistics — and then calls `reseed_mishmar_tasks`, which rebuilds that Mishmar's task list from `students_tasks.md` with categories and derived due dates. It deliberately does **NOT** delete `speaker_outreach`: that journal is the shared memory of who has been approached this season, and erasing it would silently delete another pair's knowledge. `reopen_lesson_speaker` is the smaller sibling — closing a slot's speaker used to be one-way.
- **`speaker_searches`** stores a whole scan (`results_json`) per Mishmar: a thorough search costs a minute of network plus a model call, and without saving it every revisit pays again and a partner cannot see what was tried. `region_flag()` is the pure travel-band mapper (🟢/🟡/🔴/⚪) for the same reason distance matters here — the evening ends at 02:00.
- **`speakers.domains`** holds broad categories for the index filter, derived by the pure `classify_domains()` from the free-text tags and refreshed by `backfill_speaker_domains()` (idempotent; runs from `bootstrap`). 46 people carried 33 free-text tags, nearly all used once, so the old per-tag filter matched exactly one person. A speaker whose field was never recorded stays **unclassified** and lands in the «ללא תחום» bucket — never guessed into a domain. `v_speaker_status` must carry `s.domains`, or the column exists and the screen cannot see it.
- **Tasks ↔ slots**: `tasks.lesson_id` (nullable FK → `lessons`, ON DELETE SET NULL — deleting a slot unties its tasks, never deletes them) is an EXPLICIT link, written by the slot's «🎤 סגירת מרצה / 👥 מי מעביר / 📎 דף מקורות» buttons, the task editor's «שייך למקטע» picker, and the chat's `add_task(slot_order=…)`. `suggest_lesson_for_task(task, lessons)` is a PURE fallback (closed speaker's name > חבורות + סבב א׳/ב׳ > «שיעור/מקטע N» > slot title; ambiguity → None) used only to aim the «פתח» door — **never persisted**: a wrong door costs a click, a wrong stored link is wrong data. `add_task` never guesses (seeding would pay a lookup per row).
- `get_budget_summary(today)` → `avg_per_past` = spend on Mishmarim whose date has PASSED ÷ their count (d.m.Y via `parse_gregorian`, never string order); `None` when none has happened — «עוד לא התקיים משמר» is not «costs nothing».
- `upload_source_sheet()` uploads to Supabase Storage (auto-creates the `sources` bucket; returns None on ANY failure so the UI can fall back to a paste-a-link field). **Object keys are ASCII**: Storage answers `InvalidKey` to a Hebrew file name, and every sheet a pair uploads is named in Hebrew — `_safe_filename` rebuilds the stem from `[A-Za-z0-9_-]` (Python's `\w` matches Hebrew, which is how the first upload failed), falls back to `source`/`invitation`, and keeps the extension for the image check. The key also carries `_content_tag(data)` (8 hex chars of the bytes) so a re-upload gets a NEW public URL — the old one stays cached by the browser and Supabase's CDN for an hour. `edit_task`/`delete_task` exist; `tasks.details` is the free description; `feedback.lesson_title` carries per-slot feedback BY NAME so it survives slot deletion — submitting it closes the trainee's משוב task. Category `יום המשמר` (offset 0) took the day-of classifier needles from `לוגיסטיקה`.
- The phase model lives here too: `mishmar_progress()` derives a 4-phase build state (נושא → מרצים ותוכן → לוגיסטיקה → אחרי) from task categories; phase 1 completes when the topic is SET. It accepts preloaded rows so list views cost two queries, not one per Mishmar.

## Verifying changes — no live Supabase reachable from a sandbox

Run the schema against a local PostgreSQL 16 and drive `data_manager` through a PostgREST-shaped shim, so query construction is genuinely exercised. **All of it is committed in `scripts/harness/`:**

```bash
python3 scripts/harness/db.py up             # initdb on first use, Supabase roles, schema ×2, seed → template
python3 scripts/harness/db.py fresh mytest   # a throwaway copy; prints its DSN
MISHMAR_PG_DSN="host=/tmp port=55432 dbname=mytest user=postgres" python3 -c \
  "import sys; sys.path[:0]=['scripts/harness','.']; import pgrest_shim, data_manager as dm; dm.set_client(pgrest_shim.FakeSupabase()); ..."
```

The roles mirroring Supabase (`anon`, `authenticated`, `service_role`) exist before the schema, or the REVOKE/GRANT statements fail. The shim (`pgrest_shim.py`) **runs `SET ROLE service_role`** — connecting as the owner bypasses RLS and makes the test meaningless — and serializes like PostgREST (datetime→string, Decimal→float), or it would be more forgiving than production and hide real bugs. `db.py` rebuilds the fixture only when the schema, the seed file or itself changed. PostgreSQL missing → it prints `blocked` and the install command, never a silent pass.

**Reset restores a uniform template, not the Markdown.** `reset_mishmar` deletes the evening's own
rows (never `speaker_outreach`) and `reseed_mishmar_tasks` inserts `DEFAULT_TASK_TEMPLATE` — one
list by phase, the same for every Mishmar, categories given and due dates via `compute_due_date`.
It used to re-read `students_tasks.md`, which for some evenings carries leftovers of an earlier plan;
the first-run seed still comes from the Markdown. `delete_lesson_with_tasks(mishmar_id, lesson_id)`
is the row-delete that reflows the clock; bare `delete_lesson` leaves the later start times stale.

## Slots own their tasks (schema v6)

The evening's structure and the task board used to be two lists that only guessed at each other:
the timeline came from `create_default_timeline`, the tasks from a flat template, and nothing tied
a task to the slot it was about. Deleting the חבורות slot left its task behind; «פתח» landed on a
panel instead of on a slot.

- **`sync_lesson_tasks(mishmar_id)`** is the single place that reconciles them, and it is
  idempotent. Per ordinary slot: «סגירת מרצה — שיעור N» + «דף מקורות — שיעור N». Per חבורות slot:
  «מי מעביר את התוכן — חבורות», «דפי מקורות למעבירי החבורות», «חלוקת חללים למעבירי החבורות». Every
  row carries `lesson_id`. It creates what is missing, retires OUR OWN wording when a slot changes
  shape (`_is_generated` — a hand-written task linked to the slot is never touched), and clears
  open tasks whose slot is gone. **DONE rows are never touched.** `create_default_timeline` calls
  it, so a new Mishmar is born synced; an existing one catches up from «🔄 סנכרן משימות למקטעים».
- **Ownership is PROVENANCE, not wording: `tasks.generated` (schema 7).** `sync_lesson_tasks` is the
  only writer of `generated = true` (`add_task(..., generated=True)`), and `_is_generated(task)` is
  the only ownership test — every rename, retire, adopt and slot-delete goes through it. Before
  schema 7 ownership was a text match against the module's own vocabulary, which meant a task a
  trainee happened to word EXACTLY like a generated one could be silently retitled or deleted by
  the reconciler. The vocabulary still exists in one place (`_CHAVUROT_SLOT_TASKS` + `_slot_tasks`)
  and is repeated once in SQL — the **one-time** backfill in `supabase_schema.sql` that flags rows
  created before the column, guarded by `app_meta.tasks_generated_backfilled` so a re-run of the
  file can never flag a task written since. The seed's template rows (e.g. «סידור הבית מדרש») are
  NOT generated: they belong to the evening, not to a slot. A database one version behind cannot
  read the column — and cannot reach this code either, because the schema gate stops the app first.
- **The seed's generic speaker rows are gone (schema 8).** `students_tasks.md` carried, under every
  Mishmar #02–#21, «סגירת מרצים» and «סגירת חברותות/חבורות» — duplicates of the per-slot tasks the
  structure generates, `generated=false`, never satisfied by anything, so phase 2 «מרצים ותוכן» could
  never complete on a seeded evening. Removed from the Markdown; in the live DB a one-time,
  `app_meta.tasks_generic_retired`-guarded migration in the schema tail deletes the OPEN, unlinked,
  non-generated rows in those two exact wordings (DONE rows stay) and renames «סידור חדרים» to the
  template's «סידור הבית מדרש» — the row the חבורות room logic assumes. `REQUIRED_SCHEMA_VERSION = 8`.
- **Deleting a slot deletes only what the slot generated.** `delete_lesson_with_tasks` removes the
  slot's open GENERATED tasks; a task a human tied to that slot is left to the FK's
  `ON DELETE SET NULL` and goes back to being an ordinary task of the evening. It used to delete
  every open task on the slot, human ones included.
- **A shape change RENAMES, it does not delete and recreate.** `_rename_key(text)` strips both the
  round («— סבב ב׳») and the slot number («— שיעור 3»), so a row keeps its id, details, due date
  and status when the evening gains a round or a deletion renumbers it; the two generated texts of
  one slot never share a key, and a slot that changed KIND shares none, so it still retires. This
  is the only thing that touches a DONE row, and only its label — without it a DONE
  «דף מקורות — שיעור 3» sat forever beside a freshly created «— שיעור 2» for the same work.
- **Orphans are adopted.** A generated task with `lesson_id = NULL` (a slot deleted the bare
  way, an older sync) is adopted by the slot that still expects its text (`link_task_to_lesson`,
  same row, counted as `adopted`); open orphans nobody expects are retired. DONE rows and
  human-written tasks are never touched. The reconciler is index-free: a slot's number is never
  the test of what it owns.
- **A new row goes LAST: `_next_slot_order` = max + 1, and `recompute_lesson_times` renumbers.**
  `len(rows) + 1` collided after a deletion — orders 1,2,4,5 produced 5 again, and the new break
  sorted next to the old 5, mid-evening. `get_lessons` orders by `slot_order` then `id`; the
  recompute closes gaps (1..N) in the same pass that reflows the clock. `upsert_lesson` keys on
  `slot_order`, which is why callers must read fresh rows after any structural change.
- **An evening can hold more than one round of חבורות, and every round is its own.**
  `#01` and the alumni evening both do. `round_suffix(i, total)` appends «— סבב א׳ / ב׳ / ג׳ / ד׳»
  to the three חבורות texts **only when `total ≥ 2`** — a single round must keep reading
  «מי מעביר את התוכן — חבורות», and `_round_number` reads the suffix back, so
  `suggest_lesson_for_task` aims «פתח» at the right round. Ownership and satisfaction are decided
  on `_base_slot_text(text)` (the wording minus its suffix), so one rule covers both shapes.
  · **Rooms belong to a round**, not to the evening: the same room at 20:00 and at 21:15 is not a
  clash. · **A room is ARRANGED once**: the day-of «סידור <חלל>» goes to the first round that uses
  it (`rooms_taken` accumulates down the evening), because the tables are moved once for the night.
  · **Shape changes RENAME, never delete-and-recreate.** A round gained a sibling → its three rows
  keep their ids, details, due dates and status, and only their label moves (`renamed` in the
  result); the sibling goes away → they move back. This is the **one** thing that touches a DONE
  row, and it touches only its text: without it a DONE «… — סבב א׳» sat beside a freshly created
  bare copy of the same finished work. The base wording must match, so a rename can never reach
  across to a different task.
- **A slot's tasks complete themselves.** `_slot_task_satisfied(lesson, text, presenters)`: a
  closed `speaker_name` satisfies «סגירת מרצה», a `source_url` on the slot «דף מקורות», one
  presenter «מי מעביר», every presenter with a room / a sheet the other two. `sync_lesson_tasks`
  marks an open owned task DONE when its slot already shows the work, creates a satisfied task as
  DONE (the case that bit: the task was created by a later sync, after the speaker had been
  closed), and reports `completed`. It is called after every write that can satisfy one —
  `_close_candidate`, `_source_changed`, the slot editor's save, presenter add/room change.
  Never the reverse: a reopened speaker does not reopen a DONE task.
- **The roster can be applied from the app.** `roster_placeholders()` lists student rows still
  named «חניך N» — the one-time symptom of a database seeded before the names existed.
  **`roster_drift()` is the general question**: it diffs `students_tasks.md` against the live
  `students` + `assignments` **by name**, returning the evenings whose pair differs, the names the
  file added, the names it dropped, and the file's pairs for showing side by side.
  `apply_trainee_roster()` then brings the two in line — **matched by name, not by position**: a
  row whose name is in the file stays on its id, a missing name is inserted on **MAX(id)+1 — never
  on a gap**, because a gap is a retired id and the migration's name-guarded DELETE of that id is
  then all that protects the newcomer (the migration inserts new trainees by name on the same
  MAX(id)+1, so the two paths agree on the id),
  and a `role='student'` row absent from the file is **deleted** (assignments cascade, every other
  `student_id` ref goes NULL). The old positional version could only ever say «the placeholders got
  their names»: it could not express a departure, and with a retired id in the middle it would have
  renumbered everyone — renaming every row in a live database and silently moving one person's
  outreach and feedback onto another human. The trainee Mishmarim's pairs are replaced; staff
  evenings untouched; idempotent; identical result to the SQL migration.
  **A replacement is a delete plus an insert, never a rename** (יעל שם טוב → טליה קור, same four
  evenings): the leaver's row carries their Google `email` — renaming it would let the leaver log
  in as the newcomer — and their outreach and search history, which is not the newcomer's. The
  newcomer's email is linked afterwards in the dashboard's accounts form. In the script a
  replacement keeps the leaver's list position in `NAMES` (the seeded draw reads the index), so
  `kept` prints 38/38 and nobody else moves.
  **The dashboard shows it twice on purpose**: a loud card when there is drift, naming the
  Mishmarim and the people, *and* an always-present «👥 חניכים ושיבוץ» expander holding the same
  button. The card alone was the bug — it was gated on `placeholders or unowned`, so it vanished
  the moment it was first used, and every later change to the pairs had no route into the database
  at all. A control that can only be used once is a control that cannot be used.
- **`add_lesson_slot(mishmar_id, minutes, role=None)`** — `role="חבורות"` is how a second round
  of חבורות is added («➕ הוסף חבורות»); `is_chavurot` reads the role. `set_candidate_phone` edits
  a candidate's phone after the fact and, like `add_lesson_speaker`, fills the index's contact
  only when it is empty. `upload_invitation` puts the evening's one poster image next to the
  source sheets (`mishmar-XX/invitation-<file>`, images only) and the caller stores the URL with
  `set_invitation`; `_storage_upload` is the shared bucket helper.
- **`delete_lesson_with_tasks(mishmar_id, lesson_id)`** is how a slot (or a break) is removed:
  its OPEN tasks go with it, DONE ones stay as history, and the clock reflows. Bare `delete_lesson`
  leaves both the later start times and the tasks stale.
- **`is_chavurot(lesson)`** (public alias of `_is_chavurot`) reads role **or** format **or** title.
  The UI used to test `lesson_role == "חבורות"` alone, so a slot marked חבורות in the FORMAT field
  never grew a presenters list.
- **`CHAVUROT_ROOMS`** — בית מדרש · כיתת בית מדרש · כיתת שבייד · ספריית שבייד. Exactly four;
  `set_candidate_room` raises `ValueError` on anything else. A room used twice is flagged in the UI,
  never blocked. `set_candidate_source` holds one source sheet per presenter.
  Both live on `lesson_speakers` (`room`, `source_url` — schema v6).
- **`DEFAULT_TASK_TEMPLATE`** now holds only what the EVENING owns: נושא · «הזמנה — עיצוב והפצה»
  (one row) · כיבוד · יום המשמר ×2 · «מתנות למרצים אשר הגיעו בחינם» · משוב. Anything belonging to a
  slot is created by `sync_lesson_tasks` and dies with the slot.
- **`upload_source_sheet` returns `(url, error)`** — the old silent `None` turned a Storage
  misconfiguration into a button that looked broken.
- **Rooms drive day-of tasks.** `DEFAULT_ROOM` (בית מדרש) is where presenter #1 is assumed to sit,
  covered by the template's «סידור הבית מדרש». With **two or more** presenters, every distinct
  other room they chose yields a slot-owned «סידור <חלל>» (`יום המשמר`), created and retired by
  `sync_lesson_tasks` — which now reads the presenters in one query and is called by the UI after
  every room change, presenter add (`add_chavurot_presenter`) and presenter delete. One presenter →
  nothing extra. Across ROUNDS the room is deduped (see the round rule above), and both the
  presenter list and the logistics panel count a room's users **within its own round**. Closing a candidate (`_close_candidate` in `app.py`) also marks the slot's open
  «סגירת מרצה» task DONE, found by `lesson_id`.
- **Every sort/slice on a date column wraps it in `str()`** — `due_date` too: the shim returns a
  `date` where PostgREST returns text, and a task without a due date (the `or "9999"` fallback)
  then raised `'<' not supported between 'str' and 'datetime.date'` in `mishmar_progress` and
  in the workfile's `by_due` sort. Four sort keys now read `str(t.get("due_date") or "9999")`.
- `created_at` is an ISO string from PostgREST and a `datetime` from the local shim: slice it as
  `str(value)[:10]`, never `value[:10]` — the speaker index crashed on the harness over exactly this.
