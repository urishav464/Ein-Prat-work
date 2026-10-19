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

REVOKE ALL ON FUNCTION v2_private.caller() FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.caller() FROM anon;
REVOKE ALL ON FUNCTION v2_private.caller() FROM authenticated;


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

REVOKE ALL ON FUNCTION v2_private.home_of(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.home_of(integer) FROM anon;
REVOKE ALL ON FUNCTION v2_private.home_of(integer) FROM authenticated;


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

REVOKE ALL ON FUNCTION v2_private.owns_evening(integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.owns_evening(integer, integer) FROM anon;
REVOKE ALL ON FUNCTION v2_private.owns_evening(integer, integer) FROM authenticated;
REVOKE ALL ON FUNCTION v2_private.task_json(tasks) FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.task_json(tasks) FROM anon;
REVOKE ALL ON FUNCTION v2_private.task_json(tasks) FROM authenticated;
REVOKE ALL ON FUNCTION v2_private.classify_task(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.classify_task(text) FROM anon;
REVOKE ALL ON FUNCTION v2_private.classify_task(text) FROM authenticated;
REVOKE ALL ON FUNCTION v2_private.due_date(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v2_private.due_date(text, text) FROM anon;
REVOKE ALL ON FUNCTION v2_private.due_date(text, text) FROM authenticated;


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


-- One evening whole, as the workfile shows it. The people on a slot come with
-- their phones — the pair calls them — so this answers only the pair of that
-- evening, and the instructor.
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

    RETURN jsonb_build_object(
        'status', 'ok',
        'as_of', to_char(current_date, 'YYYY-MM-DD'),
        'viewer', CASE WHEN c.status = 'instructor' THEN 'instructor' ELSE 'trainee' END,
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
    );
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


-- Postgres grants EXECUTE on a new function to PUBLIC, and Supabase's default
-- privileges hand it to anon and authenticated as well: take it back from all
-- of them, then give each door to the signed-in role only.
REVOKE ALL ON FUNCTION public.v2_my_home() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_my_home() FROM anon;
REVOKE ALL ON FUNCTION public.v2_my_home() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_my_home() TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_my_home() TO service_role;

REVOKE ALL ON FUNCTION public.v2_set_task_status(bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_set_task_status(bigint, text) FROM anon;
REVOKE ALL ON FUNCTION public.v2_set_task_status(bigint, text) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_set_task_status(bigint, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_set_task_status(bigint, text) TO service_role;

REVOKE ALL ON FUNCTION public.v2_home_as(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_home_as(integer) FROM anon;
REVOKE ALL ON FUNCTION public.v2_home_as(integer) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_home_as(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_home_as(integer) TO service_role;

REVOKE ALL ON FUNCTION public.v2_workfile(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_workfile(integer) FROM anon;
REVOKE ALL ON FUNCTION public.v2_workfile(integer) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_workfile(integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_workfile(integer) TO service_role;

REVOKE ALL ON FUNCTION public.v2_add_task(integer, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_add_task(integer, text, text) FROM anon;
REVOKE ALL ON FUNCTION public.v2_add_task(integer, text, text) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_add_task(integer, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_add_task(integer, text, text) TO service_role;

REVOKE ALL ON FUNCTION public.v2_edit_task(bigint, text, text, date, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_edit_task(bigint, text, text, date, bigint) FROM anon;
REVOKE ALL ON FUNCTION public.v2_edit_task(bigint, text, text, date, bigint) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_edit_task(bigint, text, text, date, bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_edit_task(bigint, text, text, date, bigint) TO service_role;

REVOKE ALL ON FUNCTION public.v2_delete_task(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_delete_task(bigint) FROM anon;
REVOKE ALL ON FUNCTION public.v2_delete_task(bigint) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_delete_task(bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_delete_task(bigint) TO service_role;
