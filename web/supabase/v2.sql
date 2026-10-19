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
    -- the rule v2_my_home() reads by: a task of one of the caller's evenings,
    -- never one assigned to the partner alone. A task that does not exist
    -- answers the same, so the answer says nothing about other evenings.
    SELECT * INTO t FROM tasks WHERE id = p_task_id;
    IF NOT FOUND
       OR NOT EXISTS (SELECT 1 FROM assignments a
                       WHERE a.mishmar_id = t.mishmar_id AND a.student_id = c.student_id)
       OR (t.student_id IS NOT NULL AND t.student_id <> c.student_id) THEN
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
