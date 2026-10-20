-- ===========================================================================
-- Mishmar v2 — the ONLY doors from the browser into the database.
--
-- Run in Supabase → SQL Editor (idempotent: run the whole file again after
-- every change to it). It does not touch the Streamlit app: that app reads
-- and writes with the service_role key and never calls these functions.
--
-- Why functions and not table grants: the v2 front end runs in the browser
-- with the PUBLIC anon key, signed in through Supabase Auth (Google). The
-- tables stay exactly as locked as today — RLS on, nothing granted to `anon`
-- or `authenticated` — and a signed-in browser may call the functions below
-- and nothing else. Who is calling is the Google address, linked to a row of
-- `students` in the dashboard's «שיוך חשבונות»:
--
--   v2_my_home()                     a trainee: their evenings, their pair's
--                                    names, their tasks. Never a phone, an
--                                    e-mail, a contact field or a task's
--                                    free-text details. The instructor: the
--                                    trainees' names, to choose whom to view.
--   v2_set_task_status(task, status) ✓ on a task of one of the trainee's own
--                                    evenings — exactly what
--                                    dm.update_task_status writes.
--   v2_home_as(trainee)              the instructor only: exactly what that
--                                    trainee's v2_my_home() answers. Read-only —
--                                    the instructor cannot write through
--                                    v2_set_task_status.
--   v2_workfile(evening)             one evening whole — its slots, the people
--                                    on them (with their PHONES: the pair
--                                    calls them), logistics, every task with
--                                    its details. A trainee: their own
--                                    evenings only. The instructor: any.
--   v2_add_task / v2_edit_task /     the workfile's task board, with exactly
--   v2_delete_task                   dm.add_task / edit_task / delete_task's
--                                    rules; a trainee's own evenings only.
--   v2_set_topic / v2_add_slot /     the evening's STRUCTURE (stage 2ב): the
--   v2_save_slot / v2_delete_slot /  topic, the slots, the people on them —
--   v2_reopen_slot / v2_add_person / exactly what the Streamlit workfile's
--   v2_edit_person /                 «מבנה הערב» panel writes, through the
--   v2_set_person_status /           SQL twins below, and every one ends by
--   v2_remove_person                 reconciling the evening's task board
--                                    (sync_lesson_tasks) and answering with
--                                    the evening as v2_workfile shows it.
--
-- The instructor reads everything and writes nothing here: every write door
-- answers them «instructor». Phones and task details reach only the pair of
-- that evening and the instructor; an e-mail or a speakers.contact, nobody.
--
-- A write made here does not pass through the Streamlit app's read cache, so
-- that app shows it within CACHE_TTL_SECONDS (15 minutes) or at its next
-- restart. The other direction is immediate: v2 reads fresh on every load.
-- ===========================================================================

-- Who is calling — shared by every door, and unreachable from the browser:
-- PostgREST exposes only `public`, and nobody but the owner may use this schema.
CREATE SCHEMA IF NOT EXISTS v2_private;
REVOKE ALL ON SCHEMA v2_private FROM PUBLIC;
REVOKE ALL ON SCHEMA v2_private FROM anon;
REVOKE ALL ON SCHEMA v2_private FROM authenticated;

-- status: signed_out · wrong_provider · ok (a trainee) · instructor ·
-- not_linked. A trainee's row wins when one address is on both.
CREATE OR REPLACE FUNCTION v2_private.caller(OUT status text, OUT student_id integer, OUT email text)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    -- PostgREST puts the verified JWT's claims here (this is what auth.jwt() reads)
    claims   jsonb := coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb;
    provider text  := coalesce(claims -> 'app_metadata' ->> 'provider', '');
    -- a local, not the OUT `email`: inside the query below that name would be
    -- ambiguous with students.email
    em       text  := lower(trim(coalesce(claims ->> 'email', '')));
BEGIN
    email := em;
    IF em = '' THEN
        status := 'signed_out';
        RETURN;
    END IF;
    -- Google only: an address typed into an e-mail sign-up proves nothing
    IF provider <> 'google' THEN
        status := 'wrong_provider';
        RETURN;
    END IF;
    SELECT s.id INTO student_id FROM students s
     WHERE lower(trim(coalesce(s.email, ''))) = em AND s.role = 'student'
     LIMIT 1;
    IF student_id IS NOT NULL THEN
        status := 'ok';
        RETURN;
    END IF;
    -- the instructor is a row of its own (role 'instructor'), linked the same way
    SELECT s.id INTO student_id FROM students s
     WHERE lower(trim(coalesce(s.email, ''))) = em AND s.role = 'instructor'
     LIMIT 1;
    status := CASE WHEN student_id IS NULL THEN 'not_linked' ELSE 'instructor' END;
END
$$;


-- One trainee's home, built in one place: what the trainee reads, and what the
-- instructor's view of them reads — the two can never drift apart. Not a door:
-- called only from the SECURITY DEFINER functions below.
CREATE OR REPLACE FUNCTION v2_private.home_of(p_student_id integer)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT jsonb_build_object(
        'status', 'ok',
        'as_of', to_char(current_date, 'YYYY-MM-DD'),
        'me', jsonb_build_object('id', me.id, 'name', me.name),
        'mishmarim', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'id', m.id,
                       'gregorian_date', m.gregorian_date,
                       'hebrew_date', m.hebrew_date,
                       'mishmar_type', m.mishmar_type,
                       'topic', m.topic,
                       'is_staff_built', m.is_staff_built,
                       'owners', (SELECT coalesce(jsonb_agg(s.name ORDER BY s.name), '[]'::jsonb)
                                    FROM assignments a2 JOIN students s ON s.id = a2.student_id
                                   WHERE a2.mishmar_id = m.id))
                     ORDER BY m.id), '[]'::jsonb)
              FROM mishmarim m
              JOIN assignments a ON a.mishmar_id = m.id AND a.student_id = me.id),
        'tasks', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'id', t.id,
                       'mishmar_id', t.mishmar_id,
                       'task_description', t.task_description,
                       'status', t.status,
                       'category', t.category,
                       'due_date', t.due_date)
                     ORDER BY t.mishmar_id, t.id), '[]'::jsonb)
              FROM tasks t
              JOIN assignments a ON a.mishmar_id = t.mishmar_id AND a.student_id = me.id
             -- NULL = the pair's task; a task assigned to the partner is theirs
             WHERE t.student_id IS NULL OR t.student_id = me.id)
    )
      FROM students me
     WHERE me.id = p_student_id
$$;


-- Is this one of the trainee's evenings? The one question every workfile door asks.
CREATE OR REPLACE FUNCTION v2_private.owns_evening(p_student_id integer, p_mishmar_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (SELECT 1 FROM assignments a
                    WHERE a.mishmar_id = p_mishmar_id AND a.student_id = p_student_id)
$$;

-- A task as the workfile shows it — the same shape from every door.
CREATE OR REPLACE FUNCTION v2_private.task_json(t tasks)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT jsonb_build_object(
        'id', t.id, 'mishmar_id', t.mishmar_id, 'task_description', t.task_description,
        'details', t.details, 'status', t.status, 'category', t.category,
        'due_date', t.due_date, 'lesson_id', t.lesson_id)
$$;

-- TWIN of data_manager.classify_task / _CATEGORY_RULES: the first category
-- whose needle appears in the text, or NULL — never a guess. test_v2.py feeds
-- both every needle and every task text in the fixture: they must agree.
CREATE OR REPLACE FUNCTION v2_private.classify_task(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT r.category
      FROM (VALUES
        (1, 'אחרי',      ARRAY['(אחרי)', 'סיכום ולקחים', 'תודות', 'תודה', 'עדכון מאגר', 'משוב']),
        (2, 'יום המשמר', ARRAY['ביום המשמר', 'סידור חדר', 'חדרים', 'קבלת פני', 'הצעת שתי', 'מתנות']),
        (3, 'נושא',      ARRAY['סגירת נושא', 'בחירת נושא', 'נושא המשמר']),
        (4, 'מרצים',     ARRAY['מרצים', 'מרצה']),
        (5, 'הזמנה',     ARRAY['הזמנה', 'הזמנת', 'קנבה', 'הדפסה', 'הפצה']),
        (6, 'כיבוד',     ARRAY['כיבוד', 'רשימת קניות', 'ארוחת', 'קניות']),
        (7, 'קישוט',     ARRAY['קישוט']),
        (8, 'תוכן',      ARRAY['חברותות', 'חבורות', 'מקורות', 'טקסט', 'לוח זמנים', 'לוז', 'שיעור'])
      ) AS r(ord, category, needles)
     WHERE EXISTS (SELECT 1 FROM unnest(r.needles) AS n WHERE strpos(coalesce(p_text, ''), n) > 0)
     ORDER BY r.ord
     LIMIT 1
$$;

-- TWIN of data_manager.compute_due_date / DEADLINE_OFFSETS_DAYS: the evening's
-- d.m.Y date minus the category's offset; NULL when either is unknown.
CREATE OR REPLACE FUNCTION v2_private.due_date(p_gregorian text, p_category text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    parts text[];
    base  date;
    days  integer := CASE p_category
        WHEN 'נושא' THEN 21 WHEN 'מרצים' THEN 14 WHEN 'הזמנה' THEN 7 WHEN 'כיבוד' THEN 7
        WHEN 'קישוט' THEN 7 WHEN 'תוכן' THEN 7 WHEN 'לוגיסטיקה' THEN 0
        WHEN 'יום המשמר' THEN 0 WHEN 'אחרי' THEN -7 END;
BEGIN
    IF days IS NULL THEN
        RETURN NULL;
    END IF;
    parts := regexp_match(coalesce(p_gregorian, ''), '^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$');
    IF parts IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        base := make_date(parts[3]::int, parts[2]::int, parts[1]::int);
    EXCEPTION WHEN others THEN
        RETURN NULL;            -- «31.2.2027»: parse_gregorian answers None too
    END;
    RETURN base - days;
END
$$;


-- ===========================================================================
-- The evening's structure — TWINS of data_manager, rule for rule.
--
-- Both apps edit the same evenings, so the site must write exactly what the
-- Streamlit app writes: the same slots and clock, the same people, the same
-- shared speaker index and outreach journal, and — above all — the same task
-- board, which the slots own (dm.sync_lesson_tasks). Every function here
-- names its Python original; web/supabase/test_v2_structure.py runs the same
-- steps through both on two copies of one database and compares them after
-- every step. Change a rule in data_manager → change its twin here, in the
-- same commit.
-- ===========================================================================

-- str.strip(): whitespace off both ends — btrim alone takes only spaces
CREATE OR REPLACE FUNCTION v2_private.pystrip(p text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT regexp_replace(coalesce(p, ''), '^\s+|\s+$', '', 'g')
$$;

-- TWIN of dm.normalize_name: gershayim and geresh folded to ASCII, the way the
-- generated column speakers.name_norm folds them
CREATE OR REPLACE FUNCTION v2_private.norm_name(p text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT v2_private.pystrip(replace(replace(coalesce(p, ''), '״', '"'), '׳', ''''))
$$;

-- TWIN of dm.split_title / _TITLE_RE: a title is a credential, not a name
CREATE OR REPLACE FUNCTION v2_private.split_title(p text, OUT title text, OUT name text)
LANGUAGE plpgsql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    m text[] := regexp_match(coalesce(p, ''),
        '^\s*(ד[״"'']ר|דר[׳'']|פרופ[׳'']?|פרופסור|הרב(?:נית)?|עו[״"'']ד)\s+(.+)$');
BEGIN
    IF m IS NULL THEN
        title := NULL;
        name := v2_private.pystrip(p);
    ELSE
        title := m[1];
        name := v2_private.pystrip(m[2]);
    END IF;
END
$$;

-- dm.CHAVUROT_ROOMS / dm.SPEAKER_STATUSES — test_v2_structure.py compares both
CREATE OR REPLACE FUNCTION v2_private.rooms()
RETURNS text[]
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT ARRAY['בית מדרש', 'כיתת בית מדרש', 'כיתת שבייד', 'ספריית שבייד']
$$;

CREATE OR REPLACE FUNCTION v2_private.speaker_statuses()
RETURNS text[]
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT ARRAY['⬜ לא פנינו', '📩 נשלחה פנייה', '✅ סגור', '❌ לא יכול/ה', '⚠️ בתנאי']
$$;

-- a source sheet is a web link, nothing else (the site draws it as one)
CREATE OR REPLACE FUNCTION v2_private.is_http_url(p text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT coalesce(p, '') ~* '^https?://[^[:space:]]+$' AND length(p) <= 1000
$$;

-- ---- the shared speaker index and the outreach journal

-- TWIN of dm.resolve_speaker (without creating): THE index row whose
-- name_norm is this name's, its title split off. Several rows of the name →
-- «ambiguous» and no row — AmbiguousSpeaker: never pick one of the namesakes.
CREATE OR REPLACE FUNCTION v2_private.resolve_speaker(p_name text, OUT speaker_id bigint, OUT ambiguous boolean)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    norm text := v2_private.norm_name((v2_private.split_title(p_name)).name);
    n    integer;
BEGIN
    ambiguous := false;
    IF norm = '' THEN
        RETURN;
    END IF;
    SELECT count(*), min(s.id) INTO n, speaker_id FROM speakers s WHERE s.name_norm = norm;
    IF n > 1 THEN
        ambiguous := true;
        speaker_id := NULL;
    END IF;
END
$$;

-- TWIN of dm.add_new_speaker(name, source_type='manual', contact, notes): the
-- index learns a person, the title split off on the way in. (Python's upsert
-- would overwrite a row with the same name and source; it cannot meet one —
-- resolve_speaker found none — and here such a row is simply kept.)
CREATE OR REPLACE FUNCTION v2_private.add_manual_speaker(p_name text, p_contact text, p_notes text)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    st     record;
    new_id bigint;
BEGIN
    SELECT * INTO st FROM v2_private.split_title(p_name);
    INSERT INTO speakers (name, title, source_type, status, contact, notes)
    VALUES (st.name, st.title, 'manual', '⬜ לא פנינו', p_contact, p_notes)
    ON CONFLICT (name, source_type) DO NOTHING
    RETURNING id INTO new_id;
    IF new_id IS NULL THEN
        SELECT s.id INTO new_id FROM speakers s WHERE s.name = st.name AND s.source_type = 'manual';
    END IF;
    RETURN new_id;
END
$$;

-- TWIN of the index half of dm.add_lesson_speaker: a new candidate joins the
-- shared index («manual», the phone as its contact); a known one gets the
-- phone only while the index has none. Several rows of the name: nothing.
CREATE OR REPLACE FUNCTION v2_private.learn_speaker(p_name text, p_phone text)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    r  record;
    ph text := v2_private.pystrip(p_phone);
BEGIN
    SELECT * INTO r FROM v2_private.resolve_speaker(p_name);
    IF r.ambiguous THEN
        RETURN;
    END IF;
    IF r.speaker_id IS NULL THEN
        PERFORM v2_private.add_manual_speaker(p_name, nullif(ph, ''), 'נוסף כמועמד ממבנה הערב');
    ELSIF ph <> '' THEN
        UPDATE speakers SET contact = ph
         WHERE id = r.speaker_id AND btrim(coalesce(contact, ''), 'TBD ') = '';
    END IF;
END
$$;

-- TWIN of the index half of dm.set_candidate_phone: never a new index row,
-- never over a contact the index already has
CREATE OR REPLACE FUNCTION v2_private.learn_phone(p_name text, p_phone text)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    ph text := v2_private.pystrip(p_phone);
    r  record;
BEGIN
    IF ph = '' THEN
        RETURN;
    END IF;
    SELECT * INTO r FROM v2_private.resolve_speaker(p_name);
    IF r.ambiguous OR r.speaker_id IS NULL THEN
        RETURN;
    END IF;
    UPDATE speakers SET contact = ph
     WHERE id = r.speaker_id AND btrim(coalesce(contact, ''), 'TBD ') = '';
END
$$;

-- TWIN of dm.record_outreach — THE single writer of the outreach journal: the
-- person is resolved (a new name joins the index as «manual»), one row is
-- logged, and the evening's slots showing that name mirror the status.
-- Several index rows share the name → nothing logged, and false, for the
-- screen to say so.
CREATE OR REPLACE FUNCTION v2_private.record_outreach(p_status text, p_name text,
                                                      p_mishmar_id integer, p_student_id integer)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    r     record;
    sid   bigint;
    sname text;
BEGIN
    SELECT * INTO r FROM v2_private.resolve_speaker(p_name);
    IF r.ambiguous THEN
        RETURN false;
    END IF;
    sid := r.speaker_id;
    IF sid IS NULL THEN
        IF v2_private.norm_name((v2_private.split_title(p_name)).name) = '' THEN
            RETURN false;          -- no name at all: Python raises here; the doors never get here
        END IF;
        sid := v2_private.add_manual_speaker(p_name, NULL, NULL);
    END IF;
    SELECT s.name INTO sname FROM speakers s WHERE s.id = sid;
    INSERT INTO speaker_outreach (speaker_id, mishmar_id, student_id, status, note)
    VALUES (sid, p_mishmar_id, p_student_id, p_status, NULL);
    IF p_mishmar_id IS NOT NULL THEN
        UPDATE lessons SET speaker_status = p_status
         WHERE mishmar_id = p_mishmar_id AND speaker_name = sname;
    END IF;
    RETURN true;
END
$$;

-- ---- the slots and the tasks they own

-- TWIN of dm._is_chavurot: role OR format OR title says חבורות (חברותות in the title)
CREATE OR REPLACE FUNCTION v2_private.is_chavurot(p_role text, p_format text, p_title text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT strpos(coalesce(p_role, ''), 'חבורות') > 0
        OR strpos(coalesce(p_format, ''), 'חבורות') > 0
        OR strpos(coalesce(p_title, ''), 'חבורות') > 0
        OR strpos(coalesce(p_title, ''), 'חברותות') > 0
$$;

-- TWIN of dm.is_panel: «פאנל» in format, role or title — never a חבורות slot
CREATE OR REPLACE FUNCTION v2_private.is_panel(p_role text, p_format text, p_title text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT NOT v2_private.is_chavurot(p_role, p_format, p_title)
       AND (strpos(coalesce(p_format, ''), 'פאנל') > 0
            OR strpos(coalesce(p_role, ''), 'פאנל') > 0
            OR strpos(coalesce(p_title, ''), 'פאנל') > 0)
$$;

-- TWIN of dm.round_suffix: «— סבב ב׳» only when the evening holds 2+ rounds
CREATE OR REPLACE FUNCTION v2_private.round_suffix(p_index integer, p_total integer)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT CASE WHEN p_total < 2 OR p_index < 1 OR p_index > 4 THEN ''
                ELSE ' — סבב ' || (ARRAY['א׳', 'ב׳', 'ג׳', 'ד׳'])[p_index] END
$$;

-- TWIN of dm._base_slot_text: the wording without its round
CREATE OR REPLACE FUNCTION v2_private.base_slot_text(p text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT v2_private.pystrip(regexp_replace(v2_private.pystrip(p), '\s+—\s+סבב\s+\S+$', ''))
$$;

-- TWIN of dm._rename_key: … and without its slot number
CREATE OR REPLACE FUNCTION v2_private.rename_key(p text)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT v2_private.pystrip(regexp_replace(v2_private.base_slot_text(p), '\s+—\s+שיעור\s+\d+$', ''))
$$;

-- TWIN of dm._slot_tasks: the tasks a slot OWNS, in order. A lesson: its
-- speaker and its source sheet. A round of חבורות: presenters, their sheets,
-- their rooms — and with two or more presenters a day-of «סידור <חלל>» for
-- every other room no earlier round has claimed.
CREATE OR REPLACE FUNCTION v2_private.slot_tasks(p_lesson lessons, p_index integer, p_round_index integer,
                                                 p_round_total integer, p_rooms_taken text[])
RETURNS TABLE (st_ord integer, st_category text, st_text text)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    suffix text;
    rooms  text[] := '{}';
    p      record;
    n      integer;
BEGIN
    IF v2_private.is_chavurot(p_lesson.lesson_role, p_lesson.format, p_lesson.title) THEN
        suffix := v2_private.round_suffix(p_round_index, p_round_total);
        SELECT count(*) INTO n FROM lesson_speakers WHERE lesson_id = p_lesson.id;
        IF n >= 2 THEN
            FOR p IN SELECT ls.room FROM lesson_speakers ls WHERE ls.lesson_id = p_lesson.id ORDER BY ls.id LOOP
                IF coalesce(p.room, '') <> '' AND p.room <> 'בית מדרש'
                   AND p.room = ANY (v2_private.rooms())
                   AND NOT p.room = ANY (rooms)
                   AND NOT p.room = ANY (coalesce(p_rooms_taken, '{}')) THEN
                    rooms := rooms || p.room;
                END IF;
            END LOOP;
        END IF;
        st_ord := 1; st_category := 'תוכן'; st_text := 'מי מעביר את התוכן — חבורות' || suffix;
        RETURN NEXT;
        st_ord := 2; st_category := 'תוכן'; st_text := 'דפי מקורות למעבירי החבורות' || suffix;
        RETURN NEXT;
        st_ord := 3; st_category := 'לוגיסטיקה'; st_text := 'חלוקת חללים למעבירי החבורות' || suffix;
        RETURN NEXT;
        FOR n IN 1 .. coalesce(cardinality(rooms), 0) LOOP
            st_ord := 3 + n; st_category := 'יום המשמר'; st_text := 'סידור ' || rooms[n];
            RETURN NEXT;
        END LOOP;
        RETURN;
    END IF;
    st_ord := 1; st_category := 'מרצים'; st_text := 'סגירת מרצה — שיעור ' || p_index;
    RETURN NEXT;
    st_ord := 2; st_category := 'תוכן'; st_text := 'דף מקורות — שיעור ' || p_index;
    RETURN NEXT;
END
$$;

-- TWIN of dm._slot_task_satisfied: is the work a slot's task asks for already
-- visible on the slot? A closed speaker (a panel: every panelist still in
-- play), a sheet on the slot, a presenter, every presenter with a sheet / a room.
CREATE OR REPLACE FUNCTION v2_private.slot_task_satisfied(p_lesson lessons, p_text text)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    t        text := v2_private.base_slot_text(p_text);
    n        integer;
    n_live   integer;
    n_closed integer;
    n_sheet  integer;
    n_room   integer;
BEGIN
    SELECT count(*),
           count(*) FILTER (WHERE ls.status IS DISTINCT FROM '❌ לא יכול/ה'),
           count(*) FILTER (WHERE ls.status IS DISTINCT FROM '❌ לא יכול/ה' AND ls.status = '✅ סגור'),
           count(*) FILTER (WHERE v2_private.pystrip(ls.source_url) <> ''),
           count(*) FILTER (WHERE v2_private.pystrip(ls.room) <> '')
      INTO n, n_live, n_closed, n_sheet, n_room
      FROM lesson_speakers ls WHERE ls.lesson_id = p_lesson.id;
    IF starts_with(t, 'סגירת מרצה') THEN
        IF v2_private.is_panel(p_lesson.lesson_role, p_lesson.format, p_lesson.title) THEN
            RETURN n_live > 0 AND n_closed = n_live;
        END IF;
        RETURN v2_private.pystrip(p_lesson.speaker_name) <> '';
    END IF;
    IF starts_with(t, 'דף מקורות — שיעור') THEN
        RETURN v2_private.pystrip(p_lesson.source_url) <> '';
    END IF;
    IF t = 'מי מעביר את התוכן — חבורות' THEN
        RETURN n > 0;
    END IF;
    IF t = 'דפי מקורות למעבירי החבורות' THEN
        RETURN n > 0 AND n_sheet = n;
    END IF;
    IF t = 'חלוקת חללים למעבירי החבורות' THEN
        RETURN n > 0 AND n_room = n;
    END IF;
    RETURN false;
END
$$;

-- TWIN of dm.sync_lesson_tasks — the ONE reconciler of an evening's structure
-- and its task board, step for step in the same order. Per slot: rename our
-- rows whose round or number moved (the only change a DONE row ever gets),
-- complete what the slot already shows, adopt an orphan in the slot's wording,
-- create what is missing (generated), retire our open wording the slot no
-- longer asks for. Then the orphans nobody adopted, then our open tasks on
-- slots that are gone. A task a human wrote is never touched.
CREATE OR REPLACE FUNCTION v2_private.sync_lesson_tasks(p_mishmar_id integer)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    evening     text;
    l           lessons%ROWTYPE;
    i           integer := 0;
    rounds      bigint[];
    rooms_taken text[] := '{}';
    owned_cat   text[];
    owned_text  text[];
    have        text[];
    t           record;
    txt         text;
    target      text;
    done        boolean;
    orphan_id   bigint;
    j           integer;
    cnt         integer;
    created     integer := 0;
    removed     integer := 0;
    adopted     integer := 0;
    completed   integer := 0;
    renamed     integer := 0;
BEGIN
    SELECT m.gregorian_date INTO evening FROM mishmarim m WHERE m.id = p_mishmar_id;
    SELECT coalesce(array_agg(x.id ORDER BY x.slot_order, x.id), '{}') INTO rounds
      FROM lessons x
     WHERE x.mishmar_id = p_mishmar_id AND NOT x.is_break
       AND v2_private.is_chavurot(x.lesson_role, x.format, x.title);

    FOR l IN SELECT * FROM lessons x WHERE x.mishmar_id = p_mishmar_id AND NOT x.is_break
              ORDER BY x.slot_order, x.id LOOP
        i := i + 1;
        SELECT coalesce(array_agg(s.st_category ORDER BY s.st_ord), '{}'),
               coalesce(array_agg(s.st_text ORDER BY s.st_ord), '{}')
          INTO owned_cat, owned_text
          FROM v2_private.slot_tasks(l, i, coalesce(array_position(rounds, l.id), 1),
                                     cardinality(rounds), rooms_taken) AS s;
        FOR j IN 1 .. cardinality(owned_text) LOOP
            IF starts_with(owned_text[j], 'סידור ') THEN
                rooms_taken := rooms_taken || substr(owned_text[j], length('סידור ') + 1);
            END IF;
        END LOOP;
        SELECT coalesce(array_agg(v2_private.pystrip(x.task_description) ORDER BY x.id), '{}') INTO have
          FROM tasks x WHERE x.mishmar_id = p_mishmar_id AND x.lesson_id = l.id;

        -- the evening changed shape under the slot: same work, same row, new label
        FOR t IN SELECT x.id, x.task_description, x.generated FROM tasks x
                  WHERE x.mishmar_id = p_mishmar_id AND x.lesson_id = l.id ORDER BY x.id LOOP
            txt := v2_private.pystrip(t.task_description);
            CONTINUE WHEN txt = ANY (owned_text) OR NOT t.generated;
            SELECT o.w INTO target
              FROM unnest(owned_text) WITH ORDINALITY AS o(w, k)
             WHERE v2_private.rename_key(o.w) = v2_private.rename_key(txt)
             ORDER BY o.k LIMIT 1;
            IF target IS NOT NULL AND NOT target = ANY (have) THEN
                UPDATE tasks SET task_description = v2_private.pystrip(target), updated_at = now()
                 WHERE id = t.id;
                have := array_remove(have, txt) || target;
                renamed := renamed + 1;
            END IF;
        END LOOP;

        FOR j IN 1 .. cardinality(owned_text) LOOP
            txt := owned_text[j];
            done := v2_private.slot_task_satisfied(l, txt);
            IF txt = ANY (have) THEN
                -- the slot already shows the work: an open task for it is stale
                IF done THEN
                    UPDATE tasks SET status = 'DONE', updated_at = now()
                     WHERE mishmar_id = p_mishmar_id AND lesson_id = l.id AND status <> 'DONE'
                       AND v2_private.pystrip(task_description) = txt;
                    GET DIAGNOSTICS cnt = ROW_COUNT;
                    completed := completed + cnt;
                END IF;
                CONTINUE;
            END IF;
            orphan_id := NULL;
            SELECT x.id INTO orphan_id FROM tasks x
             WHERE x.mishmar_id = p_mishmar_id AND x.lesson_id IS NULL AND x.status <> 'DONE'
               AND x.generated AND v2_private.pystrip(x.task_description) = txt
             ORDER BY x.id LIMIT 1;
            IF orphan_id IS NOT NULL THEN
                UPDATE tasks SET lesson_id = l.id, updated_at = now() WHERE id = orphan_id;
                IF done THEN
                    UPDATE tasks SET status = 'DONE', updated_at = now() WHERE id = orphan_id;
                    completed := completed + 1;
                END IF;
                adopted := adopted + 1;
                CONTINUE;
            END IF;
            INSERT INTO tasks (mishmar_id, student_id, task_description, status, category,
                               lesson_id, details, generated, due_date)
            VALUES (p_mishmar_id, NULL, txt, CASE WHEN done THEN 'DONE' ELSE 'TO DO' END,
                    owned_cat[j], l.id, NULL, true, v2_private.due_date(evening, owned_cat[j]));
            created := created + 1;
        END LOOP;

        -- the slot changed shape: our open wording it no longer asks for retires
        DELETE FROM tasks
         WHERE mishmar_id = p_mishmar_id AND lesson_id = l.id AND status <> 'DONE' AND generated
           AND NOT v2_private.pystrip(task_description) = ANY (owned_text);
        GET DIAGNOSTICS cnt = ROW_COUNT;
        removed := removed + cnt;
    END LOOP;

    -- orphans nobody adopted: our wording, no slot that wants it
    DELETE FROM tasks
     WHERE mishmar_id = p_mishmar_id AND lesson_id IS NULL AND status <> 'DONE' AND generated;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    removed := removed + cnt;
    -- our open tasks naming a slot that no longer exists (or a break)
    DELETE FROM tasks
     WHERE mishmar_id = p_mishmar_id AND lesson_id IS NOT NULL AND status <> 'DONE' AND generated
       AND lesson_id NOT IN (SELECT x.id FROM lessons x WHERE x.mishmar_id = p_mishmar_id AND NOT x.is_break);
    GET DIAGNOSTICS cnt = ROW_COUNT;
    removed := removed + cnt;
    RETURN jsonb_build_object('created', created, 'removed', removed, 'adopted', adopted,
                              'completed', completed, 'renamed', renamed);
END
$$;

-- ---- the evening's clock

-- TWIN of dm.recompute_lesson_times: each slot starts at the evening's own
-- start time plus every duration before it (unset: a break 30, a lesson 75),
-- and slot_order closes the gaps (1..N) in the same pass. A start time that
-- does not read as H:M counts as 20:00, as Python's ValueError does.
CREATE OR REPLACE FUNCTION v2_private.recompute_times(p_mishmar_id integer)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_start text;
    hm      text[];
    minutes integer;
    r       record;
    i       integer := 0;
    stamp   text;
BEGIN
    SELECT v2_private.pystrip(m.start_time) INTO v_start FROM mishmarim m WHERE m.id = p_mishmar_id;
    IF coalesce(v_start, '') = '' THEN
        v_start := '20:00';              -- dm.EVENING_START
    END IF;
    hm := regexp_match(v_start, '^\s*(\d+)\s*:\s*(\d+)\s*$');
    minutes := CASE WHEN hm IS NULL THEN 20 * 60 ELSE hm[1]::int * 60 + hm[2]::int END;
    FOR r IN SELECT x.id, x.slot_order, x.start_time, x.duration_minutes, x.is_break FROM lessons x
              WHERE x.mishmar_id = p_mishmar_id ORDER BY x.slot_order, x.id LOOP
        i := i + 1;
        stamp := lpad(((minutes / 60) % 24)::text, 2, '0') || ':' || lpad((minutes % 60)::text, 2, '0');
        IF r.start_time IS DISTINCT FROM stamp OR r.slot_order IS DISTINCT FROM i THEN
            UPDATE lessons SET start_time = stamp, slot_order = i WHERE id = r.id;
        END IF;
        minutes := minutes + coalesce(nullif(r.duration_minutes, 0), CASE WHEN r.is_break THEN 30 ELSE 75 END);
    END LOOP;
END
$$;

-- TWIN of dm._next_slot_order: one past the LAST slot — never count + 1
CREATE OR REPLACE FUNCTION v2_private.next_slot_order(p_mishmar_id integer)
RETURNS integer
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT coalesce(max(x.slot_order), 0) + 1 FROM lessons x WHERE x.mishmar_id = p_mishmar_id
$$;

-- TWIN of dm.create_default_timeline (its sync is the door's): three 75-minute
-- lessons, 30/30/15-minute breaks, an hour of חבורות — titles, roles and
-- formats empty by design. 0, and nothing written, when the evening has rows.
CREATE OR REPLACE FUNCTION v2_private.create_default_timeline(p_mishmar_id integer)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM lessons x WHERE x.mishmar_id = p_mishmar_id) THEN
        RETURN 0;
    END IF;
    INSERT INTO lessons (mishmar_id, slot_order, is_break, duration_minutes, lesson_role)
    VALUES (p_mishmar_id, 1, false, 75, NULL), (p_mishmar_id, 2, true, 30, NULL),
           (p_mishmar_id, 3, false, 75, NULL), (p_mishmar_id, 4, true, 30, NULL),
           (p_mishmar_id, 5, false, 75, NULL), (p_mishmar_id, 6, true, 15, NULL),
           (p_mishmar_id, 7, false, 60, 'חבורות');
    PERFORM v2_private.recompute_times(p_mishmar_id);
    RETURN 7;
END
$$;

-- TWIN of dm.delete_lesson_with_tasks: the slot goes with the OPEN tasks it
-- generated; DONE ones stay as history, a human's is untied by the FK.
CREATE OR REPLACE FUNCTION v2_private.delete_slot(p_mishmar_id integer, p_lesson_id bigint)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    n integer;
BEGIN
    DELETE FROM tasks
     WHERE mishmar_id = p_mishmar_id AND lesson_id = p_lesson_id AND status <> 'DONE' AND generated;
    GET DIAGNOSTICS n = ROW_COUNT;
    DELETE FROM lessons WHERE id = p_lesson_id;
    PERFORM v2_private.recompute_times(p_mishmar_id);
    RETURN n;
END
$$;

-- ---- the people on a slot

-- TWIN of dm.close_lesson_speaker, by the row clicked: that person is the
-- slot's speaker, their row ✅, every other candidate deleted, ✅ logged.
CREATE OR REPLACE FUNCTION v2_private.close_speaker(p_lesson_id bigint, p_person_id bigint,
                                                    p_mishmar_id integer, p_student_id integer)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    who     text;
    removed text[];
    logged  boolean;
BEGIN
    SELECT p.name INTO who FROM lesson_speakers p WHERE p.id = p_person_id AND p.lesson_id = p_lesson_id;
    UPDATE lessons SET speaker_name = who WHERE id = p_lesson_id;
    SELECT coalesce(array_agg(p.name ORDER BY p.id), '{}') INTO removed
      FROM lesson_speakers p WHERE p.lesson_id = p_lesson_id AND p.id <> p_person_id;
    UPDATE lesson_speakers SET status = '✅ סגור' WHERE id = p_person_id;
    DELETE FROM lesson_speakers WHERE lesson_id = p_lesson_id AND id <> p_person_id;
    logged := v2_private.record_outreach('✅ סגור', who, p_mishmar_id, p_student_id);
    RETURN jsonb_build_object('closed', who, 'removed', to_jsonb(removed), 'logged', logged);
END
$$;

-- TWIN of dm.update_lesson_speaker_status: the row, then the journal
-- (false: several index rows share the name, nothing logged)
CREATE OR REPLACE FUNCTION v2_private.set_person_status(p_person_id bigint, p_status text,
                                                        p_mishmar_id integer, p_student_id integer)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    who text;
BEGIN
    UPDATE lesson_speakers SET status = p_status WHERE id = p_person_id RETURNING name INTO who;
    IF who IS NULL THEN
        RETURN true;
    END IF;
    RETURN v2_private.record_outreach(p_status, who, p_mishmar_id, p_student_id);
END
$$;

-- TWIN of dm.refresh_panel_speakers: a panel's speaker line is every ✅ row,
-- in the order they were added (dm.PANEL_SEP), or nothing
CREATE OR REPLACE FUNCTION v2_private.refresh_panel(p_lesson_id bigint)
RETURNS text
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    joined text;
BEGIN
    SELECT string_agg(p.name, ' · ' ORDER BY p.id) INTO joined
      FROM lesson_speakers p WHERE p.lesson_id = p_lesson_id AND p.status = '✅ סגור';
    UPDATE lessons SET speaker_name = nullif(joined, '') WHERE id = p_lesson_id;
    RETURN coalesce(joined, '');
END
$$;

-- TWIN of dm.adopt_panel_speaker: a slot that BECOMES a panel keeps the
-- speaker it had closed — their row turns ✅, or a ✅ row is added for them
CREATE OR REPLACE FUNCTION v2_private.adopt_panel_speaker(p_lesson_id bigint, p_speaker_name text)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    nm text := v2_private.pystrip(p_speaker_name);
    r  record;
BEGIN
    IF nm = '' OR strpos(nm, '·') > 0 THEN
        RETURN false;
    END IF;
    SELECT p.id, p.status INTO r FROM lesson_speakers p
     WHERE p.lesson_id = p_lesson_id AND v2_private.norm_name(p.name) = v2_private.norm_name(nm)
     ORDER BY p.id LIMIT 1;
    IF FOUND THEN
        IF r.status IS DISTINCT FROM '✅ סגור' THEN
            UPDATE lesson_speakers SET status = '✅ סגור' WHERE id = r.id;
        END IF;
        RETURN false;
    END IF;
    INSERT INTO lesson_speakers (lesson_id, name, status) VALUES (p_lesson_id, nm, '✅ סגור');
    RETURN true;
END
$$;

-- ---- what the doors share

-- One evening whole, as the workfile shows it — v2_workfile's answer, and the
-- answer of every structure door after its write. The people on a slot come
-- with their phones: only the pair of the evening and the instructor get here.
CREATE OR REPLACE FUNCTION v2_private.workfile_of(p_mishmar_id integer, p_viewer text)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT jsonb_build_object(
        'status', 'ok',
        'as_of', to_char(current_date, 'YYYY-MM-DD'),
        'viewer', p_viewer,
        'mishmar', (
            SELECT jsonb_build_object(
                       'id', m.id, 'gregorian_date', m.gregorian_date,
                       'hebrew_date', m.hebrew_date, 'mishmar_type', m.mishmar_type,
                       'topic', m.topic, 'note', m.note, 'is_staff_built', m.is_staff_built,
                       'start_time', m.start_time, 'invitation_url', m.invitation_url,
                       'owners', (SELECT coalesce(jsonb_agg(s.name ORDER BY s.name), '[]'::jsonb)
                                    FROM assignments a JOIN students s ON s.id = a.student_id
                                   WHERE a.mishmar_id = m.id))
              FROM mishmarim m WHERE m.id = p_mishmar_id),
        'lessons', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'id', l.id, 'slot_order', l.slot_order, 'start_time', l.start_time,
                       'duration_minutes', l.duration_minutes, 'is_break', l.is_break,
                       'title', l.title, 'description', l.description,
                       'lesson_role', l.lesson_role, 'format', l.format,
                       'speaker_name', l.speaker_name, 'source_url', l.source_url,
                       'people', (SELECT coalesce(jsonb_agg(jsonb_build_object(
                                             'id', p.id, 'name', p.name, 'status', p.status,
                                             'phone', p.phone, 'room', p.room,
                                             'source_url', p.source_url)
                                           ORDER BY p.id), '[]'::jsonb)
                                    FROM lesson_speakers p WHERE p.lesson_id = l.id))
                     ORDER BY l.slot_order, l.id), '[]'::jsonb)
              FROM lessons l WHERE l.mishmar_id = p_mishmar_id),
        'logistics', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'id', i.id, 'kind', i.kind, 'label', i.label,
                       'detail', i.detail, 'done', i.done)
                     ORDER BY i.kind, i.sort_order NULLS LAST, i.id), '[]'::jsonb)
              FROM logistics_items i WHERE i.mishmar_id = p_mishmar_id),
        'tasks', (
            SELECT coalesce(jsonb_agg(v2_private.task_json(t) ORDER BY t.id), '[]'::jsonb)
              FROM tasks t WHERE t.mishmar_id = p_mishmar_id)
    )
$$;

-- A structure door's first question: a trainee of this evening? (The
-- instructor writes nothing: their «instructor» passes straight through.)
-- Then the evening is locked to the end of the transaction, so the pair's two
-- phones cannot reconcile the same evening at once and create a task twice.
CREATE OR REPLACE FUNCTION v2_private.may_write(p_mishmar_id integer, OUT status text, OUT student_id integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    c record;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    student_id := c.student_id;
    IF c.status <> 'ok' THEN
        status := c.status;
        RETURN;
    END IF;
    IF p_mishmar_id IS NULL OR NOT v2_private.owns_evening(c.student_id, p_mishmar_id) THEN
        status := 'forbidden';
        RETURN;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('v2_evening'), p_mishmar_id);
    status := 'ok';
END
$$;

-- What a structure door answers once it has written and reconciled
CREATE OR REPLACE FUNCTION v2_private.answer(p_mishmar_id integer, p_result jsonb)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT jsonb_build_object('status', 'ok',
                              'workfile', v2_private.workfile_of(p_mishmar_id, 'trainee'),
                              'result', p_result)
$$;

-- Nothing in v2_private is anyone's but the owner's. Postgres hands EXECUTE on
-- a new function to PUBLIC; take it back from every function here, each run.
DO $$
DECLARE
    f regprocedure;
BEGIN
    FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = 'v2_private' LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', f);
    END LOOP;
END
$$;


-- ===========================================================================
-- The doors
-- ===========================================================================

CREATE OR REPLACE FUNCTION public.v2_my_home()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c record;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status = 'not_linked' THEN
        RETURN jsonb_build_object('status', c.status, 'email', c.email);
    ELSIF c.status = 'instructor' THEN
        -- no evenings of their own: the trainees to look at instead
        -- (v2_home_as) — names and ids, nothing else
        RETURN jsonb_build_object(
            'status', 'instructor',
            'me', (SELECT jsonb_build_object('id', s.id, 'name', s.name)
                     FROM students s WHERE s.id = c.student_id),
            'trainees', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', s.id, 'name', s.name)
                                                   ORDER BY s.name), '[]'::jsonb)
                           FROM students s WHERE s.role = 'student'));
    ELSIF c.status <> 'ok' THEN
        RETURN jsonb_build_object('status', c.status);
    END IF;
    RETURN v2_private.home_of(c.student_id);
END
$$;


CREATE OR REPLACE FUNCTION public.v2_set_task_status(p_task_id bigint, p_status text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c record;
    t tasks%ROWTYPE;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    -- a trainee only: the instructor's status is «instructor», refused here too
    IF c.status <> 'ok' THEN
        RETURN jsonb_build_object('status', c.status);
    END IF;
    -- the table's own CHECK, and dm.TASK_STATUSES
    IF p_status IS NULL OR p_status NOT IN ('TO DO', 'IN PROGRESS', 'DONE') THEN
        RETURN jsonb_build_object('status', 'invalid_status');
    END IF;
    -- a task of one of the caller's evenings — any of them, the partner's own
    -- included: both of the pair see it on the workfile, as in the Streamlit
    -- app. A task that does not exist answers the same, so the answer says
    -- nothing about other evenings.
    SELECT * INTO t FROM tasks WHERE id = p_task_id;
    IF NOT FOUND OR NOT v2_private.owns_evening(c.student_id, t.mishmar_id) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    -- exactly what dm.update_task_status writes
    UPDATE tasks SET status = p_status, updated_at = now() WHERE id = p_task_id;
    RETURN jsonb_build_object('status', 'ok',
                              'task', jsonb_build_object('id', p_task_id, 'status', p_status));
END
$$;


-- The instructor sees a trainee's screen before the trainee gets the link:
-- the very answer that trainee's own v2_my_home() gives, and nothing to write
-- with. Anyone else is refused, whoever they ask about.
CREATE OR REPLACE FUNCTION public.v2_home_as(p_student_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c record;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status IN ('signed_out', 'wrong_provider') THEN
        RETURN jsonb_build_object('status', c.status);
    ELSIF c.status <> 'instructor' THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM students WHERE id = p_student_id AND role = 'student') THEN
        RETURN jsonb_build_object('status', 'not_found');
    END IF;
    RETURN v2_private.home_of(p_student_id);
END
$$;


-- One evening whole, as the workfile shows it — for the pair of that evening,
-- and the instructor (v2_private.workfile_of).
CREATE OR REPLACE FUNCTION public.v2_workfile(p_mishmar_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c record;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status IN ('signed_out', 'wrong_provider') THEN
        RETURN jsonb_build_object('status', c.status);
    ELSIF c.status = 'ok' THEN
        IF NOT v2_private.owns_evening(c.student_id, p_mishmar_id) THEN
            RETURN jsonb_build_object('status', 'forbidden');
        END IF;
    ELSIF c.status <> 'instructor' THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM mishmarim WHERE id = p_mishmar_id) THEN
        RETURN jsonb_build_object('status', 'not_found');
    END IF;
    RETURN v2_private.workfile_of(p_mishmar_id,
                                  CASE WHEN c.status = 'instructor' THEN 'instructor' ELSE 'trainee' END);
END
$$;


-- «➕ הוסף משימה»: exactly what dm.add_task writes — the pair's task (no
-- student), the category given or classified, the due date derived from the
-- evening's date, not a slot's, not generated.
CREATE OR REPLACE FUNCTION public.v2_add_task(p_mishmar_id integer, p_text text,
                                              p_category text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c      record;
    txt    text := btrim(coalesce(p_text, ''));
    cat    text := nullif(btrim(coalesce(p_category, '')), '');
    evening text;
    new_id bigint;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status <> 'ok' THEN
        RETURN jsonb_build_object('status', c.status);
    END IF;
    IF NOT v2_private.owns_evening(c.student_id, p_mishmar_id) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF txt = '' OR length(txt) > 300 THEN
        RETURN jsonb_build_object('status', 'invalid_text');
    END IF;
    -- dm.TASK_CATEGORIES
    IF cat IS NOT NULL AND cat NOT IN ('נושא', 'מרצים', 'הזמנה', 'כיבוד', 'קישוט', 'תוכן',
                                       'לוגיסטיקה', 'יום המשמר', 'אחרי') THEN
        RETURN jsonb_build_object('status', 'invalid_category');
    END IF;
    cat := coalesce(cat, v2_private.classify_task(txt));
    SELECT gregorian_date INTO evening FROM mishmarim WHERE id = p_mishmar_id;
    INSERT INTO tasks (mishmar_id, student_id, task_description, status, category,
                       lesson_id, details, generated, due_date)
    VALUES (p_mishmar_id, NULL, txt, 'TO DO', cat, NULL, NULL, false,
            v2_private.due_date(evening, cat))
    RETURNING id INTO new_id;
    RETURN jsonb_build_object('status', 'ok',
                              'task', (SELECT v2_private.task_json(t) FROM tasks t WHERE t.id = new_id));
END
$$;


-- The task editor's «💾 שמור»: dm.edit_task + dm.link_task_to_lesson. An empty
-- title is not written, empty details clear them, an empty due date leaves it,
-- and a slot must be one of the same evening's (or none).
CREATE OR REPLACE FUNCTION public.v2_edit_task(p_task_id bigint, p_text text, p_details text,
                                               p_due_date date, p_lesson_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c   record;
    t   tasks%ROWTYPE;
    txt text := btrim(coalesce(p_text, ''));
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status <> 'ok' THEN
        RETURN jsonb_build_object('status', c.status);
    END IF;
    SELECT * INTO t FROM tasks WHERE id = p_task_id;
    IF NOT FOUND OR NOT v2_private.owns_evening(c.student_id, t.mishmar_id) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF length(txt) > 300 OR length(coalesce(p_details, '')) > 2000 THEN
        RETURN jsonb_build_object('status', 'invalid_text');
    END IF;
    IF p_lesson_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM lessons WHERE id = p_lesson_id AND mishmar_id = t.mishmar_id) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    UPDATE tasks
       SET task_description = CASE WHEN txt <> '' THEN txt ELSE task_description END,
           details          = nullif(btrim(coalesce(p_details, '')), ''),
           due_date         = coalesce(p_due_date, due_date),
           lesson_id        = p_lesson_id,
           updated_at       = now()
     WHERE id = p_task_id;
    RETURN jsonb_build_object('status', 'ok',
                              'task', (SELECT v2_private.task_json(x) FROM tasks x WHERE x.id = p_task_id));
END
$$;


-- 🗑 on a task card — any task of one of the trainee's evenings, as in the app.
CREATE OR REPLACE FUNCTION public.v2_delete_task(p_task_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    c       record;
    evening integer;
BEGIN
    SELECT * INTO c FROM v2_private.caller();
    IF c.status <> 'ok' THEN
        RETURN jsonb_build_object('status', c.status);
    END IF;
    SELECT mishmar_id INTO evening FROM tasks WHERE id = p_task_id;
    IF evening IS NULL OR NOT v2_private.owns_evening(c.student_id, evening) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    DELETE FROM tasks WHERE id = p_task_id;
    RETURN jsonb_build_object('status', 'ok', 'task', jsonb_build_object('id', p_task_id));
END
$$;


-- ---- the evening's structure (stage 2ב). Each door: the Streamlit callback
-- it stands for, then sync_lesson_tasks, then the evening as it is now.

-- «🎯 סגירת הנושא» / «עדכן נושא» — app._close_topic_clicked and
-- _update_topic_clicked. An evening without a topic gets one, its «נושא»
-- tasks close and the default skeleton is built (when it has no rows yet);
-- an evening with a topic is renamed.
CREATE OR REPLACE FUNCTION public.v2_set_topic(p_mishmar_id integer, p_topic text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    w       record;
    txt     text := v2_private.pystrip(p_topic);
    closing boolean;
    built   integer := 0;
    s       jsonb;
BEGIN
    SELECT * INTO w FROM v2_private.may_write(p_mishmar_id);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    IF txt = '' OR length(txt) > 200 THEN
        RETURN jsonb_build_object('status', 'invalid_text');
    END IF;
    SELECT coalesce(m.topic, '') = '' INTO closing FROM mishmarim m WHERE m.id = p_mishmar_id;
    UPDATE mishmarim SET topic = txt WHERE id = p_mishmar_id;
    IF closing THEN
        UPDATE tasks SET status = 'DONE', updated_at = now()
         WHERE mishmar_id = p_mishmar_id AND category = 'נושא' AND status <> 'DONE';
        built := v2_private.create_default_timeline(p_mishmar_id);
    END IF;
    s := v2_private.sync_lesson_tasks(p_mishmar_id);
    RETURN v2_private.answer(p_mishmar_id, jsonb_build_object('closed', closing, 'created', built, 'sync', s));
END
$$;


-- «➕ הוסף שיעור» / «➕ הוסף חבורות» / «➕ הוסף הפסקה» / «✨ צור את שלד הערב» —
-- app._add_slot_clicked (dm.add_lesson_slot, 60 minutes, «חבורות» for a
-- round), dm.add_break (15), dm.create_default_timeline. A new row goes LAST.
CREATE OR REPLACE FUNCTION public.v2_add_slot(p_mishmar_id integer, p_kind text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    w     record;
    built integer := 0;
    s     jsonb;
BEGIN
    SELECT * INTO w FROM v2_private.may_write(p_mishmar_id);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    IF p_kind IS NULL OR p_kind NOT IN ('lesson', 'chavurot', 'break', 'skeleton') THEN
        RETURN jsonb_build_object('status', 'invalid_kind');
    END IF;
    IF p_kind = 'skeleton' THEN
        built := v2_private.create_default_timeline(p_mishmar_id);
        IF built = 0 THEN
            RETURN jsonb_build_object('status', 'exists');
        END IF;
    ELSE
        IF (SELECT count(*) FROM lessons x WHERE x.mishmar_id = p_mishmar_id) >= 20 THEN
            RETURN jsonb_build_object('status', 'too_many');
        END IF;
        INSERT INTO lessons (mishmar_id, slot_order, is_break, duration_minutes, lesson_role)
        VALUES (p_mishmar_id, v2_private.next_slot_order(p_mishmar_id), p_kind = 'break',
                CASE WHEN p_kind = 'break' THEN 15 ELSE 60 END,
                CASE WHEN p_kind = 'chavurot' THEN 'חבורות' END);
        PERFORM v2_private.recompute_times(p_mishmar_id);
        built := 1;
    END IF;
    s := v2_private.sync_lesson_tasks(p_mishmar_id);
    RETURN v2_private.answer(p_mishmar_id, jsonb_build_object('created', built, 'sync', s));
END
$$;


-- The slot editor's «💾 שמור» — app._lesson_edit_dialog, by the slot's id:
-- title, description, role and format; a slot that becomes a panel keeps the
-- speaker it had closed and reads its line from the panel's rows; then the
-- duration (the clock reflows) and the source link. A break: its duration only.
CREATE OR REPLACE FUNCTION public.v2_save_slot(p_lesson_id bigint, p_title text, p_duration integer,
                                               p_role text, p_format text, p_description text,
                                               p_source_url text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid     integer;
    w       record;
    l       lessons%ROWTYPE;
    v_title text := v2_private.pystrip(p_title);
    v_role  text := v2_private.pystrip(p_role);
    v_fmt   text := v2_private.pystrip(p_format);
    v_desc  text := v2_private.pystrip(p_description);
    v_link  text := v2_private.pystrip(p_source_url);
    s       jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lessons x WHERE x.id = p_lesson_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    SELECT * INTO l FROM lessons x WHERE x.id = p_lesson_id;      -- fresh, under the lock
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF p_duration IS NULL OR p_duration < 5 OR p_duration > 240 THEN
        RETURN jsonb_build_object('status', 'invalid_duration');
    END IF;
    IF l.is_break THEN
        UPDATE lessons SET duration_minutes = p_duration WHERE id = l.id;
        PERFORM v2_private.recompute_times(mid);
    ELSE
        IF length(v_title) > 120 OR length(v_role) > 60 OR length(v_fmt) > 60 OR length(v_desc) > 2000 THEN
            RETURN jsonb_build_object('status', 'invalid_text');
        END IF;
        IF v_link <> '' AND NOT v2_private.is_http_url(v_link) THEN
            RETURN jsonb_build_object('status', 'invalid_url');
        END IF;
        UPDATE lessons SET title = v_title, description = v_desc, lesson_role = v_role, format = v_fmt
         WHERE id = l.id;
        IF v2_private.is_panel(v_role, v_fmt, v_title) THEN
            IF NOT v2_private.is_panel(l.lesson_role, l.format, l.title) THEN
                PERFORM v2_private.adopt_panel_speaker(l.id, l.speaker_name);
            END IF;
            PERFORM v2_private.refresh_panel(l.id);
        END IF;
        UPDATE lessons SET duration_minutes = p_duration WHERE id = l.id;
        PERFORM v2_private.recompute_times(mid);
        IF v_link <> coalesce(l.source_url, '') THEN
            UPDATE lessons SET source_url = nullif(v_link, '') WHERE id = l.id;
        END IF;
        PERFORM v2_private.recompute_times(mid);
    END IF;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, jsonb_build_object('sync', s));
END
$$;


-- «🗑 מחק מקטע» and a break's ✕ — dm.delete_lesson_with_tasks
CREATE OR REPLACE FUNCTION public.v2_delete_slot(p_lesson_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid integer;
    w   record;
    n   integer;
    s   jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lessons x WHERE x.id = p_lesson_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM lessons x WHERE x.id = p_lesson_id) THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    n := v2_private.delete_slot(mid, p_lesson_id);
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, jsonb_build_object('tasks', n, 'sync', s));
END
$$;


-- «🔄 החלף» — dm.reopen_lesson_speaker: the lesson's speaker is released and
-- its candidates come back; the journal keeps its history. A lesson only.
CREATE OR REPLACE FUNCTION public.v2_reopen_slot(p_lesson_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid integer;
    w   record;
    l   lessons%ROWTYPE;
    s   jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lessons x WHERE x.id = p_lesson_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    SELECT * INTO l FROM lessons x WHERE x.id = p_lesson_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF l.is_break OR v2_private.is_chavurot(l.lesson_role, l.format, l.title)
       OR v2_private.is_panel(l.lesson_role, l.format, l.title) THEN
        RETURN jsonb_build_object('status', 'invalid');
    END IF;
    UPDATE lessons SET speaker_name = NULL, speaker_status = '⬜ לא פנינו' WHERE id = l.id;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, jsonb_build_object('sync', s));
END
$$;


-- «➕ מועמד» / «✅ סגור מרצה» on a lesson, «➕ לפאנל» / «✅ הוסף וסגור» on a
-- panel, «➕ מעביר» on a round of חבורות — dm.add_lesson_speaker (the index
-- learns the person) or dm.add_chavurot_presenter (a room, no phone), then the
-- close the second button asks for. A lesson whose speaker is closed takes no
-- one new: «🔄 החלף» first.
CREATE OR REPLACE FUNCTION public.v2_add_person(p_lesson_id bigint, p_name text, p_phone text,
                                                p_room text, p_close boolean DEFAULT false)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid     integer;
    w       record;
    l       lessons%ROWTYPE;
    v_name  text := v2_private.pystrip(p_name);
    v_phone text := v2_private.pystrip(p_phone);
    v_room  text := v2_private.pystrip(p_room);
    pid     bigint;
    res     jsonb := '{}'::jsonb;
    logged  boolean;
    s       jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lessons x WHERE x.id = p_lesson_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    SELECT * INTO l FROM lessons x WHERE x.id = p_lesson_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF v_name = '' OR length(v_name) > 120 OR length(v_phone) > 40 THEN
        RETURN jsonb_build_object('status', 'invalid_text');
    END IF;
    IF v_room <> '' AND NOT v_room = ANY (v2_private.rooms()) THEN
        RETURN jsonb_build_object('status', 'invalid_room');
    END IF;
    IF l.is_break THEN
        RETURN jsonb_build_object('status', 'invalid');
    END IF;
    IF NOT v2_private.is_chavurot(l.lesson_role, l.format, l.title)
       AND NOT v2_private.is_panel(l.lesson_role, l.format, l.title)
       AND v2_private.pystrip(l.speaker_name) <> '' THEN
        RETURN jsonb_build_object('status', 'closed');
    END IF;
    IF (SELECT count(*) FROM lesson_speakers p WHERE p.lesson_id = l.id) >= 12 THEN
        RETURN jsonb_build_object('status', 'too_many');
    END IF;

    IF v2_private.is_chavurot(l.lesson_role, l.format, l.title) THEN
        INSERT INTO lesson_speakers (lesson_id, name, phone) VALUES (l.id, v_name, NULL)
        RETURNING id INTO pid;
        PERFORM v2_private.learn_speaker(v_name, '');
        IF v_room <> '' THEN
            UPDATE lesson_speakers SET room = v_room WHERE id = pid;
        END IF;
    ELSE
        INSERT INTO lesson_speakers (lesson_id, name, phone) VALUES (l.id, v_name, nullif(v_phone, ''))
        RETURNING id INTO pid;
        PERFORM v2_private.learn_speaker(v_name, v_phone);
        IF coalesce(p_close, false) THEN
            IF v2_private.is_panel(l.lesson_role, l.format, l.title) THEN
                -- dm.close_panelist: this one ✅, the panel's line re-derived
                logged := v2_private.set_person_status(pid, '✅ סגור', mid, w.student_id);
                PERFORM v2_private.refresh_panel(l.id);
                res := jsonb_build_object('closed', v_name, 'removed', '[]'::jsonb, 'logged', logged);
            ELSE
                res := v2_private.close_speaker(l.id, pid, mid, w.student_id);
            END IF;
        END IF;
    END IF;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, res || jsonb_build_object('person', pid, 'sync', s));
END
$$;


-- A person's phone (dm.set_candidate_phone: the index learns it only when it
-- has none), a presenter's room (dm.set_candidate_room) or own source sheet
-- (dm.set_candidate_source). NULL leaves a field as it is; '' clears it.
CREATE OR REPLACE FUNCTION public.v2_edit_person(p_person_id bigint, p_phone text, p_room text,
                                                 p_source_url text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid     integer;
    w       record;
    pr      lesson_speakers%ROWTYPE;
    v_phone text := v2_private.pystrip(p_phone);
    v_room  text := v2_private.pystrip(p_room);
    v_link  text := v2_private.pystrip(p_source_url);
    s       jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lesson_speakers p JOIN lessons x ON x.id = p.lesson_id
     WHERE p.id = p_person_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    SELECT * INTO pr FROM lesson_speakers p WHERE p.id = p_person_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    IF p_phone IS NOT NULL AND length(v_phone) > 40 THEN
        RETURN jsonb_build_object('status', 'invalid_text');
    END IF;
    IF p_room IS NOT NULL AND v_room <> '' AND NOT v_room = ANY (v2_private.rooms()) THEN
        RETURN jsonb_build_object('status', 'invalid_room');
    END IF;
    IF p_source_url IS NOT NULL AND v_link <> '' AND NOT v2_private.is_http_url(v_link) THEN
        RETURN jsonb_build_object('status', 'invalid_url');
    END IF;
    IF p_phone IS NOT NULL THEN
        UPDATE lesson_speakers SET phone = nullif(v_phone, '') WHERE id = pr.id;
        PERFORM v2_private.learn_phone(pr.name, v_phone);
    END IF;
    IF p_room IS NOT NULL THEN
        UPDATE lesson_speakers SET room = nullif(v_room, '') WHERE id = pr.id;
    END IF;
    IF p_source_url IS NOT NULL THEN
        UPDATE lesson_speakers SET source_url = nullif(v_link, '') WHERE id = pr.id;
    END IF;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, jsonb_build_object('sync', s));
END
$$;


-- A candidate's or a panelist's status, through the journal's single writer
-- (app._candidate_status_changed / _panelist_status_changed). «✅ סגור» on a
-- lesson IS the close — the slot's speaker, the other candidates removed
-- (app._close_candidate); on a panel it closes that one panelist and the
-- panel's line is re-derived. A presenter of חבורות has no status here.
CREATE OR REPLACE FUNCTION public.v2_set_person_status(p_person_id bigint, p_status text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid    integer;
    w      record;
    pr     lesson_speakers%ROWTYPE;
    l      lessons%ROWTYPE;
    res    jsonb;
    logged boolean;
    s      jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lesson_speakers p JOIN lessons x ON x.id = p.lesson_id
     WHERE p.id = p_person_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    IF p_status IS NULL OR NOT p_status = ANY (v2_private.speaker_statuses()) THEN
        RETURN jsonb_build_object('status', 'invalid_status');
    END IF;
    SELECT * INTO pr FROM lesson_speakers p WHERE p.id = p_person_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    SELECT * INTO l FROM lessons x WHERE x.id = pr.lesson_id;
    IF l.is_break OR v2_private.is_chavurot(l.lesson_role, l.format, l.title) THEN
        RETURN jsonb_build_object('status', 'invalid');
    END IF;
    IF v2_private.is_panel(l.lesson_role, l.format, l.title) THEN
        logged := v2_private.set_person_status(pr.id, p_status, mid, w.student_id);
        PERFORM v2_private.refresh_panel(l.id);
        res := jsonb_build_object('logged', logged);
    ELSE
        IF v2_private.pystrip(l.speaker_name) <> '' THEN
            RETURN jsonb_build_object('status', 'closed');
        END IF;
        IF p_status = '✅ סגור' THEN
            res := v2_private.close_speaker(l.id, pr.id, mid, w.student_id);
        ELSE
            logged := v2_private.set_person_status(pr.id, p_status, mid, w.student_id);
            res := jsonb_build_object('logged', logged);
        END IF;
    END IF;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, res || jsonb_build_object('sync', s));
END
$$;


-- 🗑 on a person — dm.delete_lesson_candidate (app._remove_panelist re-derives
-- the panel's line; app._remove_presenter syncs the rooms' tasks). A lesson
-- whose speaker is closed keeps its people: «🔄 החלף» first.
CREATE OR REPLACE FUNCTION public.v2_remove_person(p_person_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    mid integer;
    w   record;
    pr  lesson_speakers%ROWTYPE;
    l   lessons%ROWTYPE;
    s   jsonb;
BEGIN
    SELECT x.mishmar_id INTO mid FROM lesson_speakers p JOIN lessons x ON x.id = p.lesson_id
     WHERE p.id = p_person_id;
    SELECT * INTO w FROM v2_private.may_write(mid);
    IF w.status <> 'ok' THEN
        RETURN jsonb_build_object('status', w.status);
    END IF;
    SELECT * INTO pr FROM lesson_speakers p WHERE p.id = p_person_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'forbidden');
    END IF;
    SELECT * INTO l FROM lessons x WHERE x.id = pr.lesson_id;
    IF NOT v2_private.is_chavurot(l.lesson_role, l.format, l.title)
       AND NOT v2_private.is_panel(l.lesson_role, l.format, l.title)
       AND v2_private.pystrip(l.speaker_name) <> '' THEN
        RETURN jsonb_build_object('status', 'closed');
    END IF;
    DELETE FROM lesson_speakers WHERE id = pr.id;
    IF v2_private.is_panel(l.lesson_role, l.format, l.title) THEN
        PERFORM v2_private.refresh_panel(l.id);
    END IF;
    s := v2_private.sync_lesson_tasks(mid);
    RETURN v2_private.answer(mid, jsonb_build_object('removed', pr.name, 'sync', s));
END
$$;


-- Postgres grants EXECUTE on a new function to PUBLIC, and Supabase's default
-- privileges hand it to anon and authenticated as well: take it back from all
-- of them, then give each door to the signed-in role only. THE list of doors —
-- test_v2.py's EXPECTED_LEAKS is the same list, on purpose.
DO $$
DECLARE
    door text;
BEGIN
    FOREACH door IN ARRAY ARRAY[
        'public.v2_my_home()',
        'public.v2_set_task_status(bigint, text)',
        'public.v2_home_as(integer)',
        'public.v2_workfile(integer)',
        'public.v2_add_task(integer, text, text)',
        'public.v2_edit_task(bigint, text, text, date, bigint)',
        'public.v2_delete_task(bigint)',
        'public.v2_set_topic(integer, text)',
        'public.v2_add_slot(integer, text)',
        'public.v2_save_slot(bigint, text, integer, text, text, text, text)',
        'public.v2_delete_slot(bigint)',
        'public.v2_reopen_slot(bigint)',
        'public.v2_add_person(bigint, text, text, text, boolean)',
        'public.v2_edit_person(bigint, text, text, text)',
        'public.v2_set_person_status(bigint, text)',
        'public.v2_remove_person(bigint)'
    ] LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', door);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO authenticated, service_role', door);
    END LOOP;
END
$$;
