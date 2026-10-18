-- ===========================================================================
-- Mishmar v2 — the prototype's ONE door into the database.
--
-- Run once in Supabase → SQL Editor (idempotent; safe to run again). It does
-- not touch the Streamlit app: that app reads with the service_role key and
-- never calls this function.
--
-- Why a function and not table grants: the v2 front end runs in the browser
-- with the PUBLIC anon key, signed in through Supabase Auth (Google). The
-- tables stay exactly as locked as today — RLS on, nothing granted to `anon`
-- or `authenticated` — and the signed-in browser may call this function and
-- nothing else. It answers only for the trainee whose Google address is linked
-- in `students.email` (the dashboard's «שיוך חשבונות»), and returns only what
-- the trainee home shows: their evenings, their pair's names, their tasks.
-- Never a phone, an e-mail, a contact field or a task's free-text details
-- (`tasks.details` is free text and can hold a number someone typed).
-- ===========================================================================

CREATE OR REPLACE FUNCTION public.v2_my_home()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    -- PostgREST puts the verified JWT's claims here (this is what auth.jwt() reads)
    claims   jsonb := coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb;
    em       text  := lower(trim(coalesce(claims ->> 'email', '')));
    provider text  := coalesce(claims -> 'app_metadata' ->> 'provider', '');
    me       students%ROWTYPE;
BEGIN
    IF em = '' THEN
        RETURN jsonb_build_object('status', 'signed_out');
    END IF;
    -- Google only: an address typed into an e-mail sign-up proves nothing
    IF provider <> 'google' THEN
        RETURN jsonb_build_object('status', 'wrong_provider');
    END IF;
    SELECT * INTO me FROM students
     WHERE lower(trim(coalesce(email, ''))) = em AND role = 'student'
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'not_linked', 'email', em);
    END IF;

    RETURN jsonb_build_object(
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
    );
END
$$;

-- Postgres grants EXECUTE on a new function to PUBLIC, and Supabase's default
-- privileges hand it to anon and authenticated as well: take it back from all
-- of them, then give it to the signed-in role only.
REVOKE ALL ON FUNCTION public.v2_my_home() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v2_my_home() FROM anon;
REVOKE ALL ON FUNCTION public.v2_my_home() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.v2_my_home() TO authenticated;
GRANT EXECUTE ON FUNCTION public.v2_my_home() TO service_role;
