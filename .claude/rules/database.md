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

**The read cache (why a click is one run and almost no network).** Every pure read in `data_manager` is wrapped in `st.cache_data(ttl=120)` at the bottom of the module (`_READS`), and every write is wrapped to invalidate (`_WRITES`) — **by table**: each read declares the base tables it depends on (views expanded), each write the tables it touches, and a write clears only the intersecting reads. A ✓ on a task therefore refills `v_tasks_full` and nothing else (asserted in the harness: `[update tasks, select v_tasks_full]`). Rules that follow: (1) **no write may bypass the seam** — the raw `dm._t("lessons").update` calls that lived in app.py became `set_lesson_duration` / `add_lesson_slot` / `add_break` / `delete_lesson_candidate`; a new write function must be added to `_WRITES` or the UI shows stale rows for up to two minutes. (2) A write that reads first must invalidate first — `recompute_lesson_times` clears `lessons` before reading, because `create_default_timeline` inserts rows and then calls it. (3) Cached reads return copies, so mutating a returned dict is harmless. (4) `MISHMAR_NO_CACHE=1` switches it off for scripts that write around the seam (the seeding harness inserts through `_t` and calls `_invalidate()` by hand). Streamlit Cloud is one process, so invalidation is global across all trainees.

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
- **The evening timeline is derived, never hand-typed.** `lessons.start_time` is computed by `recompute_lesson_times()` from 20:00 plus cumulative `duration_minutes` (breaks are ordinary rows with `is_break`); every duration edit reflows the whole evening, so slots cannot overlap. `create_default_timeline()` builds the real skeleton — three 75-minute lessons, 30/30/15-minute breaks, an hour of חבורות ending 02:00 — with titles/roles/formats EMPTY by design, and both topic-close paths (form and chat tool) call it when the evening is empty.
- **Candidate speakers** (`lesson_speakers`): `add_lesson_speaker()` also teaches the shared index the person exists (manual source, phone as contact, title auto-split); candidate statuses route through `record_outreach()`; `close_lesson_speaker()` implements «סגרתי את X» — X becomes `lessons.speaker_name` with one ✅ row, the other candidates are deleted, the journal logs the close. **Phones live only in `lesson_speakers.phone` and `speakers.contact` — never in chat context or the generator digest.**
- The status ladder merged in v2: `⏳ ממתין לתשובה` folded into `📩 נשלחה פנייה` — constants AND idempotent UPDATEs in the schema file; do not reintroduce it.
- **The schema is versioned, and the app checks it.** `supabase_schema.sql` stamps `app_meta.schema_version`; `data_manager.REQUIRED_SCHEMA_VERSION` is what the code expects; `storage_ready()` returns `schema_stale` and `main()` shows a banner naming both numbers. **Bump `REQUIRED_SCHEMA_VERSION` in the same commit as any `ALTER`/`CREATE TABLE`** — without it a database one version behind looks healthy and then throws a redacted `APIError` deep inside a screen. That is exactly how a missing `logistics_items` blanked the entire workfile: the panel raised inside the right column, so the tasks column and the reset button never rendered either.
- **A missing relation degrades; everything else stays loud.** `_missing_relation(exc)` recognises only PGRST205/204/106 and "does not exist"; `get_logistics` and `get_searches` return empty on it and re-raise anything else. In `app.py` the three evening panels are wrapped in `_safe()` so one broken panel can never blank a column.
- **Logistics** (`logistics_items`): the refreshments list and the חבורות room allocation are the same shape — label, optional detail, done — so they share one table and `kind` (`כיבוד`/`חלל`/`אחר`) separates them. The invitation lives on `mishmarim.invitation_text`/`invitation_url`: there is exactly one per evening.
- **`reset_mishmar(mid)`** wipes an evening back to «choose a topic» — lessons (cascading `lesson_speakers`), tasks, budget, feedback, logistics — and then calls `reseed_mishmar_tasks`, which rebuilds that Mishmar's task list from `students_tasks.md` with categories and derived due dates. It deliberately does **NOT** delete `speaker_outreach`: that journal is the shared memory of who has been approached this season, and erasing it would silently delete another pair's knowledge. `reopen_lesson_speaker` is the smaller sibling — closing a slot's speaker used to be one-way.
- **`speaker_searches`** stores a whole scan (`results_json`) per Mishmar: a thorough search costs a minute of network plus a model call, and without saving it every revisit pays again and a partner cannot see what was tried. `region_flag()` is the pure travel-band mapper (🟢/🟡/🔴/⚪) for the same reason distance matters here — the evening ends at 02:00.
- **`speakers.domains`** holds broad categories for the index filter, derived by the pure `classify_domains()` from the free-text tags and refreshed by `backfill_speaker_domains()` (idempotent; runs from `bootstrap`). 46 people carried 33 free-text tags, nearly all used once, so the old per-tag filter matched exactly one person. A speaker whose field was never recorded stays **unclassified** and lands in the «ללא תחום» bucket — never guessed into a domain. `v_speaker_status` must carry `s.domains`, or the column exists and the screen cannot see it.
- **Tasks ↔ slots**: `tasks.lesson_id` (nullable FK → `lessons`, ON DELETE SET NULL — deleting a slot unties its tasks, never deletes them) is an EXPLICIT link, written by the slot's «🎤 סגירת מרצה / 👥 מי מעביר / 📎 דף מקורות» buttons, the task editor's «שייך למקטע» picker, and the chat's `add_task(slot_order=…)`. `suggest_lesson_for_task(task, lessons)` is a PURE fallback (closed speaker's name > חבורות + סבב א׳/ב׳ > «שיעור/מקטע N» > slot title; ambiguity → None) used only to aim the «פתח» door — **never persisted**: a wrong door costs a click, a wrong stored link is wrong data. `add_task` never guesses (seeding would pay a lookup per row).
- `get_budget_summary(today)` → `avg_per_past` = spend on Mishmarim whose date has PASSED ÷ their count (d.m.Y via `parse_gregorian`, never string order); `None` when none has happened — «עוד לא התקיים משמר» is not «costs nothing».
- `upload_source_sheet()` uploads to Supabase Storage (auto-creates the `sources` bucket; returns None on ANY failure so the UI can fall back to a paste-a-link field). `edit_task`/`delete_task` exist; `tasks.details` is the free description; `feedback.lesson_title` carries per-slot feedback BY NAME so it survives slot deletion — submitting it closes the trainee's משוב task. Category `יום המשמר` (offset 0) took the day-of classifier needles from `לוגיסטיקה`.
- The phase model lives here too: `mishmar_progress()` derives a 4-phase build state (נושא → מרצים ותוכן → לוגיסטיקה → אחרי) from task categories; phase 1 completes when the topic is SET. It accepts preloaded rows so list views cost two queries, not one per Mishmar.

## Verifying changes — no live Supabase reachable from a sandbox

Run the schema against a local PostgreSQL 16 and drive `data_manager` through a PostgREST-shaped shim, so query construction is genuinely exercised:

```bash
apt-get install -y postgresql
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /tmp/pgd -A trust"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgd -o '-p 5433 -k /tmp' start"
```

Create roles mirroring Supabase (`anon`, `authenticated`, `service_role`) before applying the schema, or the REVOKE/GRANT statements fail. A shim turning `.select().eq().execute()` into SQL is ~150 lines; **have it `SET ROLE service_role`** — connecting as the owner bypasses RLS and makes the test meaningless. Also have it serialize like PostgREST does (datetime→string, Decimal→float), or the shim is more forgiving than production and hides real bugs. Inject with `dm.set_client(FakeSupabase())`.

**Reset restores a uniform template, not the Markdown.** `reset_mishmar` deletes the evening's own
rows (never `speaker_outreach`) and `reseed_mishmar_tasks` inserts `DEFAULT_TASK_TEMPLATE` — one
list by phase, the same for every Mishmar, categories given and due dates via `compute_due_date`.
It used to re-read `students_tasks.md`, which for some evenings carries leftovers of an earlier plan;
the first-run seed still comes from the Markdown. `delete_break(mishmar_id, lesson_id)` is the
row-delete that reflows the clock; bare `delete_lesson` leaves the later start times stale.

## Slots own their tasks (schema v6)

The evening's structure and the task board used to be two lists that only guessed at each other:
the timeline came from `create_default_timeline`, the tasks from a flat template, and nothing tied
a task to the slot it was about. Deleting the חבורות slot left its task behind; «פתח» landed on a
panel instead of on a slot.

- **`sync_lesson_tasks(mishmar_id)`** is the single place that reconciles them, and it is
  idempotent. Per ordinary slot: «סגירת מרצה — שיעור N» + «דף מקורות — שיעור N». Per חבורות slot:
  «מי מעביר את התוכן — חבורות», «דפי מקורות למעבירי החבורות», «חלוקת חללים למעבירי החבורות». Every
  row carries `lesson_id`. It creates what is missing, retires OUR OWN wording when a slot changes
  shape (`_slot_owned_texts` — a hand-written task linked to the slot is never touched), and clears
  open tasks whose slot is gone. **DONE rows are never touched.** `create_default_timeline` calls
  it, so a new Mishmar is born synced; an existing one catches up from «🔄 סנכרן משימות למקטעים».
- **`delete_lesson_with_tasks(mishmar_id, lesson_id)`** is how a slot (or a break) is removed:
  its OPEN tasks go with it, DONE ones stay as history, and the clock reflows. Bare `delete_lesson`
  leaves both the later start times and the tasks stale.
- **`is_chavurot(lesson)`** (public alias of `_is_chavurot`) reads role **or** format **or** title.
  The UI used to test `lesson_role == "חבורות"` alone, so a slot marked חבורות in the FORMAT field
  never grew a presenters list.
- **`CHAVUROT_ROOMS`** — בית מיכאל · כיתת בית מדרש · כיתת שבייד · ספריית שבייד. Exactly four;
  `set_candidate_room` raises `ValueError` on anything else. A room used twice is flagged in the UI,
  never blocked. `set_candidate_source` holds one source sheet per presenter.
  Both live on `lesson_speakers` (`room`, `source_url` — schema v6).
- **`DEFAULT_TASK_TEMPLATE`** now holds only what the EVENING owns: נושא · «הזמנה — עיצוב והפצה»
  (one row) · כיבוד · יום המשמר ×2 · «מתנות למרצים אשר הגיעו בחינם» · משוב. Anything belonging to a
  slot is created by `sync_lesson_tasks` and dies with the slot.
- **`upload_source_sheet` returns `(url, error)`** — the old silent `None` turned a Storage
  misconfiguration into a button that looked broken.
