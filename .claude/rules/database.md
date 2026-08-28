---
paths:
  - "data_manager.py"
  - "supabase_schema.sql"
---

# Data layer — Supabase through one seam

**`data_manager.py` is the only data seam.** Nothing else talks to storage. Storage is **Supabase** over its REST API (PostgREST).

**The two-file split is forced by the platform: the REST API reads and writes rows but cannot CREATE TABLE.** Structure lives in `supabase_schema.sql`, pasted once into the Supabase SQL Editor. A schema change means editing that file *and* telling the user to re-run it — it is idempotent, so re-running is safe.

**Anything needing a join or an aggregate is a VIEW in that file**, because PostgREST cannot express one: `v_speaker_status`, `v_mishmar_budget`, `v_overdue_tasks`, `v_student_progress`, `v_outreach_full`, `v_tasks_full`. Python reads views and never assembles a join itself.

**Twelve tables.** `mishmarim`, `students`, `assignments`, `tasks`, `budget`, `speakers`, `speaker_outreach`, `lessons`, `feedback`, `chat_messages`, `search_cache`, `app_meta`.

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
- The phase model lives here too: `mishmar_progress()` derives a 4-phase build state (נושא → מרצים ותוכן → לוגיסטיקה → אחרי) from task categories; phase 1 completes when the topic is SET. It accepts preloaded rows so list views cost two queries, not one per Mishmar.

## Verifying changes — no live Supabase reachable from a sandbox

Run the schema against a local PostgreSQL 16 and drive `data_manager` through a PostgREST-shaped shim, so query construction is genuinely exercised:

```bash
apt-get install -y postgresql
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /tmp/pgd -A trust"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgd -o '-p 5433 -k /tmp' start"
```

Create roles mirroring Supabase (`anon`, `authenticated`, `service_role`) before applying the schema, or the REVOKE/GRANT statements fail. A shim turning `.select().eq().execute()` into SQL is ~150 lines; **have it `SET ROLE service_role`** — connecting as the owner bypasses RLS and makes the test meaningless. Also have it serialize like PostgREST does (datetime→string, Decimal→float), or the shim is more forgiving than production and hides real bugs. Inject with `dm.set_client(FakeSupabase())`.
