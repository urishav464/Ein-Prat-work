"""Prove v2's doors leak nothing — against the harness's local PostgreSQL 16.

    python3 scripts/harness/db.py up
    python3 web/supabase/test_v2.py [--on N] [--export web/src/demo.json]
                                    [--export-workfile web/src/demo_workfile.json]

Builds a throwaway copy of the fixture (`db.py fresh v2test`), gives it the
grants a Supabase project hands out by itself — every table, sequence and new
function open to `anon` and `authenticated` — then runs supabase_schema.sql
over that (its REVOKEs are what stands between the public anon key and the
data) and v2.sql TWICE (it must be idempotent), links one trainee's Google
address, and checks, as the roles Supabase gives a browser:

  v2_my_home()
    anon                              → may not even call it
    authenticated, no claims          → «signed_out»
    authenticated, an e-mail sign-up  → «wrong_provider» (Google only)
    authenticated, unknown address    → «not_linked»
    authenticated, the linked address → «ok», case-insensitively, with ONLY
        that trainee's evenings and tasks — never the partner's own task —
        and no phone / contact / e-mail / details key anywhere in the answer
    the instructor's address (on the role='instructor' row) → «instructor»
        and the trainees to choose from — ids and names, nothing else; an
        address on a trainee's row AND the instructor's → the trainee
  v2_home_as(trainee)
    the instructor → exactly that trainee's own v2_my_home() answer
    anon, signed out, e-mail sign-up, a trainee, unknown address → refused
    the instructor's own row, an id that does not exist → «not_found»
  v2_set_task_status(task, status)
    anon, signed out, e-mail sign-up, unknown address, the instructor →
        refused, nothing changes
    the linked trainee, a pair task of their evening  → «ok»: status and
        updated_at change, and no other column; the partner's own task too
        (both of the pair see it on the workfile, as in the Streamlit app)
    another evening's task, a task that does not exist → «forbidden»; a
        status outside the table's three → «invalid_status»
  v2_workfile(evening)
    the pair's own evening → every task of it, its slots and their people;
        a phone ONLY inside lessons[].people[], no e-mail / contact anywhere
    another evening, unknown address → «forbidden»; anon cannot call
    the instructor → any evening, «viewer: instructor»; a missing one → not_found
  v2_add_task / v2_edit_task / v2_delete_task
    add: category and due date exactly what dm.add_task writes for the same
        text (dm.classify_task / dm.compute_due_date), a pair task, not
        generated; a bad category / empty or long text / another evening /
        the instructor → refused, nothing inserted
    edit: title, details, due date and slot change and nothing else; empty
        title kept, empty details cleared, no date kept; a slot of another
        evening, another evening's task, the instructor → refused, unchanged
    delete: another evening's task, the instructor → refused, still there
  the structure doors (v2_set_topic … v2_remove_person, stage 2ב)
    anon, signed out, e-mail sign-up, unknown address, another evening's
        slot or person, one that does not exist, the instructor → refused at
        every one of the nine, and nothing anywhere changes
    an empty topic, an unknown kind of slot, 4 minutes, a javascript: link,
        a fifth room, an invented status → refused by name
    a person added → «ok», and the answer IS a fresh v2_workfile (a phone only
        on a slot's people, no e-mail / contact); a status → one journal line
        in the trainee's name; removed → gone. What the doors write is
        test_v2_structure.py's: step for step against data_manager
  the twins
    every needle of dm._CATEGORY_RULES and every task text in the fixture
    classifies the same in SQL; every category × date gets the same due date
  the catalog
    anon / authenticated hold no privilege on any table, view or sequence in
    `public`; EXECUTE on exactly the sixteen doors, for `authenticated` only;
    and no way into `v2_private`, the schema behind them

`--on N` picks a trainee of evening N. `--export PATH` writes the «ok» answer,
names replaced by placeholders, as the front end's demo data, and
`--export-workfile PATH` that trainee's workfile of evening N the same way —
every person's name and phone replaced, links, notes and task details
dropped. Prints one JSON line; exit 1 on any failed check."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = Path(__file__).with_name("v2.sql")
EMAIL = "trainee.test@example.org"
FORBIDDEN_KEYS = {"phone", "contact", "email", "details", "notes"}
GOOGLE = {"app_metadata": {"provider": "google"}}

# What a new Supabase project grants before any SQL of ours runs (its own
# setup migration): the public roles get everything, now and for every object
# created later. The local fixture never had these, so without them a
# «permission denied» below would prove nothing.
SUPABASE_DEFAULTS = """
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
"""

# every privilege the public roles still hold in `public` and `v2_private`,
# one row each
LEAKS = """
SELECT 'relation', c.relname, r.role
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 CROSS JOIN (VALUES ('anon'), ('authenticated')) AS r(role)
 WHERE n.nspname IN ('public', 'v2_private') AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
   AND has_table_privilege(r.role, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
UNION ALL
SELECT 'sequence', c.relname, r.role
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 CROSS JOIN (VALUES ('anon'), ('authenticated')) AS r(role)
 WHERE n.nspname IN ('public', 'v2_private') AND c.relkind = 'S'
   AND has_sequence_privilege(r.role, c.oid, 'USAGE, SELECT, UPDATE')
UNION ALL
SELECT 'function', n.nspname || '.' || p.proname, r.role
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 CROSS JOIN (VALUES ('anon'), ('authenticated')) AS r(role)
 WHERE n.nspname IN ('public', 'v2_private') AND has_function_privilege(r.role, p.oid, 'EXECUTE')
UNION ALL
SELECT 'schema', 'v2_private', r.role
  FROM (VALUES ('anon'), ('authenticated')) AS r(role)
 WHERE has_schema_privilege(r.role, 'v2_private', 'USAGE')
 ORDER BY 1, 2, 3
"""
EXPECTED_LEAKS = [["function", "public.v2_add_person", "authenticated"],
                  ["function", "public.v2_add_slot", "authenticated"],
                  ["function", "public.v2_add_task", "authenticated"],
                  ["function", "public.v2_delete_slot", "authenticated"],
                  ["function", "public.v2_delete_task", "authenticated"],
                  ["function", "public.v2_edit_person", "authenticated"],
                  ["function", "public.v2_edit_task", "authenticated"],
                  ["function", "public.v2_home_as", "authenticated"],
                  ["function", "public.v2_my_home", "authenticated"],
                  ["function", "public.v2_remove_person", "authenticated"],
                  ["function", "public.v2_reopen_slot", "authenticated"],
                  ["function", "public.v2_save_slot", "authenticated"],
                  ["function", "public.v2_set_person_status", "authenticated"],
                  ["function", "public.v2_set_task_status", "authenticated"],
                  ["function", "public.v2_set_topic", "authenticated"],
                  ["function", "public.v2_workfile", "authenticated"]]
INSTRUCTOR = "instructor.test@example.org"


def dsn_for(name: str) -> str:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/harness/db.py"), "fresh", name],
                       capture_output=True, text=True, cwd=ROOT)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if not out.get("ok"):
        raise SystemExit(json.dumps(out))
    return out["dsn"]


def keys_in(obj) -> set:
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= keys_in(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= keys_in(v)
    return found


def main(argv: list[str]) -> int:
    import psycopg2
    sys.path.insert(0, str(ROOT))
    import logging
    import streamlit                   # noqa: F401 — creates its loggers, then quiet them:
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    import data_manager as dm          # the twins are checked against the real rules
    export = argv[argv.index("--export") + 1] if "--export" in argv else None
    export_wf = argv[argv.index("--export-workfile") + 1] if "--export-workfile" in argv else None
    conn = psycopg2.connect(dsn_for("v2test"))
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(SUPABASE_DEFAULTS)
    cur.execute((ROOT / "supabase_schema.sql").read_text(encoding="utf-8"))
    sql = SQL.read_text(encoding="utf-8")
    cur.execute(sql)
    cur.execute(sql)                                  # idempotent

    # the trainee: the first student with evenings (or on evening N with --on N —
    # the fixture's #05 has a timeline, so its demo carries slot tasks); the
    # partner on their first evening
    on = int(argv[argv.index("--on") + 1]) if "--on" in argv else None
    cur.execute("""SELECT s.id, s.name FROM students s
                    WHERE s.role = 'student'
                      AND EXISTS (SELECT 1 FROM assignments a WHERE a.student_id = s.id
                                     AND (%s::int IS NULL OR a.mishmar_id = %s::int))
                    ORDER BY s.id LIMIT 1""", (on, on))
    me_id, me_name = cur.fetchone()
    cur.execute("UPDATE students SET email = %s WHERE id = %s", (EMAIL, me_id))
    cur.execute("SELECT mishmar_id FROM assignments WHERE student_id = %s ORDER BY 1", (me_id,))
    my_mids = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT a.student_id FROM assignments a
                    WHERE a.mishmar_id = %s AND a.student_id <> %s LIMIT 1""", (my_mids[0], me_id))
    partner = cur.fetchone()
    # a task that belongs to the PARTNER alone must not reach this trainee
    partner_task = None
    if partner:
        cur.execute("""UPDATE tasks SET student_id = %s
                        WHERE id = (SELECT id FROM tasks WHERE mishmar_id = %s ORDER BY id LIMIT 1)
                        RETURNING id""", (partner[0], my_mids[0]))
        partner_task = cur.fetchone()[0]

    checks: dict[str, bool] = {}

    def call(role: str, claims: dict | None, sql: str = "SELECT public.v2_my_home()", args=()):
        cur.execute("RESET ROLE")
        cur.execute("SELECT set_config('request.jwt.claims', %s, false)",
                    (json.dumps(claims) if claims is not None else "",))
        cur.execute(f"SET ROLE {role}")
        try:
            cur.execute(sql, args)
            return cur.fetchone()[0]
        except psycopg2.errors.InsufficientPrivilege:
            return "denied"
        finally:
            cur.execute("RESET ROLE")

    # ---- reading: v2_my_home()
    checks["anon cannot call"] = call("anon", {"email": EMAIL, **GOOGLE}) == "denied"
    checks["no claims → signed_out"] = (call("authenticated", None) or {}).get("status") == "signed_out"
    checks["e-mail sign-up → wrong_provider"] = (call("authenticated", {
        "email": EMAIL, "app_metadata": {"provider": "email"}}) or {}).get("status") == "wrong_provider"
    checks["unknown address → not_linked"] = (call("authenticated", {
        "email": "someone@example.org", **GOOGLE}) or {}).get("status") == "not_linked"
    ok = call("authenticated", {"email": EMAIL.upper(), **GOOGLE})
    checks["linked address → ok (case-insensitive)"] = isinstance(ok, dict) and ok.get("status") == "ok"
    if checks["linked address → ok (case-insensitive)"]:
        got_mids = sorted(m["id"] for m in ok["mishmarim"])
        checks["only my evenings"] = got_mids == my_mids
        checks["only tasks of my evenings"] = all(t["mishmar_id"] in my_mids for t in ok["tasks"])
        checks["not the partner's own task"] = all(t["id"] != partner_task for t in ok["tasks"])
        checks["no phone/contact/email/details key"] = not (keys_in(ok) & FORBIDDEN_KEYS)
        checks["has tasks"] = len(ok["tasks"]) > 0

    # ---- the instructor: a list to choose from, then each trainee's own answer
    cur.execute("SELECT id FROM students WHERE role = 'instructor' ORDER BY id LIMIT 1")
    inst_id = (cur.fetchone() or [None])[0]
    checks["the fixture has an instructor row"] = inst_id is not None
    cur.execute("UPDATE students SET email = %s WHERE id = %s", (INSTRUCTOR, inst_id))
    cur.execute("SELECT id, name FROM students WHERE role = 'student'")
    roster = sorted(cur.fetchall())
    cur.execute("SELECT id FROM students WHERE role = 'student' AND id <> %s ORDER BY id LIMIT 1", (me_id,))
    other_id = cur.fetchone()[0]
    boss = {"email": INSTRUCTOR.upper(), **GOOGLE}
    trainee = {"email": EMAIL, **GOOGLE}

    lst = call("authenticated", boss)
    checks["instructor → the trainees to choose from, ids and names only"] = (
        isinstance(lst, dict) and lst.get("status") == "instructor" and lst["me"]["id"] == inst_id
        and sorted((t["id"], t["name"]) for t in lst["trainees"]) == roster
        and all(set(t) == {"id", "name"} for t in lst["trainees"])
        and not (keys_in(lst) & FORBIDDEN_KEYS))

    def view(claims: dict | None, student_id: int, role: str = "authenticated"):
        return call(role, claims, "SELECT public.v2_home_as(%s)", (student_id,))

    checks["v2_home_as(trainee) = that trainee's own answer"] = view(boss, me_id) == ok
    refused_view = {
        "anon": view(boss, me_id, role="anon") == "denied",
        "signed out": (view(None, me_id) or {}).get("status") == "signed_out",
        "e-mail sign-up": (view({"email": INSTRUCTOR, "app_metadata": {"provider": "email"}},
                                me_id) or {}).get("status") == "wrong_provider",
        "a trainee": (view(trainee, other_id) or {}).get("status") == "forbidden",
        "unknown address": (view({"email": "someone@example.org", **GOOGLE},
                                 me_id) or {}).get("status") == "forbidden",
    }
    checks["v2_home_as: anon / signed out / e-mail / a trainee / unknown refused"] = all(refused_view.values())
    checks["v2_home_as: the instructor's own row or a missing id → not_found"] = \
        (view(boss, inst_id) or {}).get("status") == "not_found" \
        and (view(boss, 2_000_000) or {}).get("status") == "not_found"

    # one address on both rows: the trainee's row wins, as it did before this door
    cur.execute("UPDATE students SET email = %s WHERE id = %s", (EMAIL, inst_id))
    checks["an address on a trainee and the instructor → the trainee"] = \
        (call("authenticated", trainee) or {}).get("status") == "ok"
    cur.execute("UPDATE students SET email = %s WHERE id = %s", (INSTRUCTOR, inst_id))

    # ---- writing: v2_set_task_status()
    def row(task_id: int):
        cur.execute("SELECT to_jsonb(t) FROM tasks t WHERE id = %s", (task_id,))
        r = cur.fetchone()
        return r[0] if r else None

    def write(claims: dict | None, task_id: int, status: str, role: str = "authenticated"):
        return call(role, claims, "SELECT public.v2_set_task_status(%s, %s)", (task_id, status))

    me = {"email": EMAIL, **GOOGLE}
    cur.execute("""SELECT id FROM tasks WHERE mishmar_id = %s AND student_id IS NULL
                    AND status <> 'DONE' ORDER BY id LIMIT 1""", (my_mids[0],))
    pair_task = cur.fetchone()[0]
    cur.execute("SELECT id FROM tasks WHERE mishmar_id <> ALL(%s) ORDER BY id LIMIT 1", (my_mids,))
    foreign_task = cur.fetchone()[0]

    before = row(pair_task)
    refused = {
        "anon": write(me, pair_task, "DONE", role="anon") == "denied",
        "signed out": (write(None, pair_task, "DONE") or {}).get("status") == "signed_out",
        "e-mail sign-up": (write({"email": EMAIL, "app_metadata": {"provider": "email"}},
                                 pair_task, "DONE") or {}).get("status") == "wrong_provider",
        "unknown address": (write({"email": "someone@example.org", **GOOGLE},
                                  pair_task, "DONE") or {}).get("status") == "not_linked",
    }
    checks["write: anon / signed out / e-mail / unknown refused"] = all(refused.values())
    checks["write: a refused call changes nothing"] = row(pair_task) == before

    res = write({"email": EMAIL.upper(), **GOOGLE}, pair_task, "DONE")
    after = row(pair_task)
    checks["write: the pair's task → ok"] = (res or {}).get("status") == "ok" \
        and after["status"] == "DONE" and after["updated_at"] != before["updated_at"]
    checks["write: no other column changes"] = \
        {k: v for k, v in after.items() if k not in ("status", "updated_at")} == \
        {k: v for k, v in before.items() if k not in ("status", "updated_at")}
    write(me, pair_task, before["status"])            # back as it was

    guarded = {}
    for name, tid in (("another evening's task", foreign_task),
                      ("a task that does not exist", 2_000_000_000)):
        was = row(tid)
        guarded[name] = (write(me, tid, "DONE") or {}).get("status") == "forbidden" and row(tid) == was
    checks["write: other evening's / missing task → forbidden, unchanged"] = all(guarded.values())
    if partner_task is not None:
        was = row(partner_task)
        res = write(me, partner_task, "DONE")
        checks["write: the partner's own task → ok (both see it on the workfile)"] = \
            (res or {}).get("status") == "ok" and row(partner_task)["status"] == "DONE"
        write(me, partner_task, was["status"])        # back as it was
    was = row(pair_task)
    checks["write: a status outside the three → invalid_status, unchanged"] = \
        (write(me, pair_task, "FINISHED") or {}).get("status") == "invalid_status" and row(pair_task) == was
    was = row(pair_task)
    checks["write: the instructor (view-only) → refused, unchanged"] = \
        (write(boss, pair_task, "DONE") or {}).get("status") == "instructor" and row(pair_task) == was

    # ---- the workfile: one evening whole, for its pair and the instructor
    # The trainee's evening with the most slots (the one --on picked, if any).
    # An evening without any gets one slot and one person with a phone, in this
    # throwaway copy, so the phone rule is always exercised.
    cur.execute("""SELECT a.mishmar_id FROM assignments a
                    LEFT JOIN lessons l ON l.mishmar_id = a.mishmar_id
                    WHERE a.student_id = %s GROUP BY a.mishmar_id
                    ORDER BY (a.mishmar_id = %s) DESC, count(l.id) DESC, a.mishmar_id LIMIT 1""",
                (me_id, on or 0))
    wf_mid = cur.fetchone()[0]
    cur.execute("SELECT id FROM lessons WHERE mishmar_id = %s AND NOT is_break ORDER BY slot_order LIMIT 1",
                (wf_mid,))
    got = cur.fetchone()
    if got:
        slot = got[0]
    else:
        cur.execute("INSERT INTO lessons (mishmar_id, slot_order, title) VALUES (%s, 1, 'מקטע בדיקה') "
                    "RETURNING id", (wf_mid,))
        slot = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM lesson_speakers WHERE lesson_id = %s", (slot,))
    if not cur.fetchone()[0]:
        cur.execute("INSERT INTO lesson_speakers (lesson_id, name, phone) VALUES (%s, 'מועמד בדיקה', '050-1234567')",
                    (slot,))
    cur.execute("SELECT id FROM mishmarim WHERE id <> ALL(%s) ORDER BY id LIMIT 1", (my_mids,))
    other_mid = cur.fetchone()[0]
    cur.execute("SELECT id FROM lessons WHERE mishmar_id = %s ORDER BY id LIMIT 1", (other_mid,))
    other_slot = (cur.fetchone() or [None])[0]
    if other_slot is None:
        cur.execute("INSERT INTO lessons (mishmar_id, slot_order, title) VALUES (%s, 1, 'מקטע זר') RETURNING id",
                    (other_mid,))
        other_slot = cur.fetchone()[0]

    def wf(claims: dict | None, mid: int, role: str = "authenticated"):
        return call(role, claims, "SELECT public.v2_workfile(%s)", (mid,))

    def phone_paths(obj, path=()):
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "phone":
                    out.append(path)
                out += phone_paths(v, path + (k,))
        elif isinstance(obj, list):
            for v in obj:
                out += phone_paths(v, path + ("[]",))
        return out

    mine = wf(trainee, wf_mid)
    cur.execute("SELECT count(*) FROM tasks WHERE mishmar_id = %s", (wf_mid,))
    n_tasks = cur.fetchone()[0]
    ok_wf = isinstance(mine, dict) and mine.get("status") == "ok"
    checks["workfile: the pair's own evening → ok, every task of it, its slots"] = ok_wf \
        and mine["viewer"] == "trainee" and mine["mishmar"]["id"] == wf_mid \
        and len(mine["tasks"]) == n_tasks and any(l["people"] for l in mine["lessons"])
    checks["workfile: a phone only on a slot's people; no e-mail / contact anywhere"] = ok_wf \
        and bool(phone_paths(mine)) and all(p == ("lessons", "[]", "people", "[]") for p in phone_paths(mine)) \
        and not (keys_in(mine) & {"email", "contact"})
    refused_wf = {
        "anon": wf(trainee, wf_mid, role="anon") == "denied",
        "signed out": (wf(None, wf_mid) or {}).get("status") == "signed_out",
        "e-mail sign-up": (wf({"email": EMAIL, "app_metadata": {"provider": "email"}}, wf_mid)
                           or {}).get("status") == "wrong_provider",
        "another evening": (wf(trainee, other_mid) or {}).get("status") == "forbidden",
        "unknown address": (wf({"email": "someone@example.org", **GOOGLE}, wf_mid)
                            or {}).get("status") == "forbidden",
    }
    checks["workfile: anon / signed out / e-mail / another evening / unknown refused"] = all(refused_wf.values())
    seen = wf(boss, other_mid)
    checks["workfile: the instructor → any evening, as the instructor; a missing one → not_found"] = \
        (seen or {}).get("status") == "ok" and seen["viewer"] == "instructor" \
        and (wf(boss, 2_000_000) or {}).get("status") == "not_found"

    # ---- the task board's writes
    def count_tasks(mid: int) -> int:
        cur.execute("SELECT count(*) FROM tasks WHERE mishmar_id = %s", (mid,))
        return cur.fetchone()[0]

    def add(claims, mid, text, cat=None, role="authenticated"):
        return call(role, claims, "SELECT public.v2_add_task(%s, %s, %s)", (mid, text, cat))

    def edit(claims, tid, text, details, due, lesson, role="authenticated"):
        return call(role, claims, "SELECT public.v2_edit_task(%s, %s, %s, %s, %s)",
                    (tid, text, details, due, lesson))

    def delete(claims, tid, role="authenticated"):
        return call(role, claims, "SELECT public.v2_delete_task(%s)", (tid,))

    cur.execute("SELECT gregorian_date FROM mishmarim WHERE id = %s", (wf_mid,))
    evening = cur.fetchone()[0]
    parity = {}
    added = []
    for text, cat in (("לקנות כיבוד לערב", None), ("לתאם עם המרצה", None),
                      ("משימה בלי שום מילת מפתח", None), ("לסדר פרחים", "קישוט")):
        res = add(trainee, wf_mid, text, cat)
        t = (res or {}).get("task") or {}
        want_cat = cat or dm.classify_task(text)
        parity[text] = (res or {}).get("status") == "ok" and t.get("category") == want_cat \
            and t.get("due_date") == dm.compute_due_date(evening, want_cat)
        if t.get("id"):
            added.append(t["id"])
    checks["add: category and due date exactly as dm.add_task"] = all(parity.values())
    new = row(added[0]) if added else {}
    checks["add: a pair task, open, not generated, no slot"] = bool(new) and new["student_id"] is None \
        and new["status"] == "TO DO" and new["generated"] is False and new["lesson_id"] is None
    before_n = count_tasks(wf_mid), count_tasks(other_mid)
    refused_add = {
        "bad category": (add(trainee, wf_mid, "x", "המצאה") or {}).get("status") == "invalid_category",
        "empty text": (add(trainee, wf_mid, "   ") or {}).get("status") == "invalid_text",
        "long text": (add(trainee, wf_mid, "א" * 301) or {}).get("status") == "invalid_text",
        "another evening": (add(trainee, other_mid, "x") or {}).get("status") == "forbidden",
        "the instructor": (add(boss, wf_mid, "x") or {}).get("status") == "instructor",
        "anon": add(trainee, wf_mid, "x", role="anon") == "denied",
        "signed out": (add(None, wf_mid, "x") or {}).get("status") == "signed_out",
    }
    checks["add: bad category / empty / long / another evening / instructor / anon refused, nothing in"] = \
        all(refused_add.values()) and (count_tasks(wf_mid), count_tasks(other_mid)) == before_n

    tid = added[0] if added else 0
    was = row(tid)
    res = edit(trainee, tid, "  כותרת חדשה  ", "פרטים חדשים", "2026-12-01", slot)
    now = row(tid)
    changed = {k for k in now if now[k] != was[k]} if was and now else {"?"}
    checks["edit: title, details, due date and slot — and nothing else"] = \
        (res or {}).get("status") == "ok" and now["task_description"] == "כותרת חדשה" \
        and now["details"] == "פרטים חדשים" and now["due_date"] == "2026-12-01" \
        and now["lesson_id"] == slot \
        and changed <= {"task_description", "details", "due_date", "lesson_id", "updated_at"}
    edit(trainee, tid, "", "", None, None)
    now = row(tid)
    checks["edit: empty title kept, empty details cleared, no date kept, slot cleared"] = \
        now["task_description"] == "כותרת חדשה" and now["details"] is None \
        and now["due_date"] == "2026-12-01" and now["lesson_id"] is None
    was = row(tid)
    was_foreign = row(foreign_task)
    refused_edit = {
        "a slot of another evening": (edit(trainee, tid, "x", "", None, other_slot) or {}).get("status") == "forbidden",
        "another evening's task": (edit(trainee, foreign_task, "x", "", None, None) or {}).get("status") == "forbidden",
        "the instructor": (edit(boss, tid, "x", "", None, None) or {}).get("status") == "instructor",
        "anon": edit(trainee, tid, "x", "", None, None, role="anon") == "denied",
    }
    checks["edit: another evening's slot / task, the instructor, anon refused — unchanged"] = \
        all(refused_edit.values()) and row(tid) == was and row(foreign_task) == was_foreign

    refused_del = {
        "another evening's task": (delete(trainee, foreign_task) or {}).get("status") == "forbidden",
        "the instructor": (delete(boss, tid) or {}).get("status") == "instructor",
        "anon": delete(trainee, tid, role="anon") == "denied",
    }
    checks["delete: another evening's task, the instructor, anon refused — still there"] = \
        all(refused_del.values()) and row(foreign_task) is not None and row(tid) is not None
    gone = all((delete(trainee, t) or {}).get("status") == "ok" for t in added)
    checks["delete: the pair's own task → gone"] = gone and all(row(t) is None for t in added)

    # ---- the evening's structure (stage 2ב): who may write, and what comes back.
    # What each door WRITES is test_v2_structure.py's: every step against
    # data_manager, on two copies of the fixture.
    cur.execute("SELECT id FROM lesson_speakers WHERE lesson_id = %s ORDER BY id LIMIT 1", (slot,))
    my_person = cur.fetchone()[0]
    cur.execute("INSERT INTO lesson_speakers (lesson_id, name, phone) VALUES (%s, 'מועמד זר', '050-0000000') "
                "RETURNING id", (other_slot,))
    other_person = cur.fetchone()[0]

    def state() -> str:
        """Everything a structure door may touch, as one value."""
        cur.execute("RESET ROLE")
        cur.execute("""SELECT md5(concat_ws('|',
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM lessons x),
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM lesson_speakers x),
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM tasks x),
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM speakers x),
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM speaker_outreach x),
                         (SELECT string_agg(to_jsonb(x)::text, ',' ORDER BY x.id) FROM mishmarim x)))""")
        return cur.fetchone()[0]

    # each door: (the call on the pair's own evening, the same on another evening's)
    doors = {
        "v2_set_topic": ("SELECT public.v2_set_topic(%s, %s)", (wf_mid, "נושא"), (other_mid, "נושא")),
        "v2_add_slot": ("SELECT public.v2_add_slot(%s, %s)", (wf_mid, "lesson"), (other_mid, "lesson")),
        "v2_save_slot": ("SELECT public.v2_save_slot(%s, %s, %s, %s, %s, %s, %s)",
                         (slot, "כותרת", 75, "", "", "", ""), (other_slot, "כותרת", 75, "", "", "", "")),
        "v2_delete_slot": ("SELECT public.v2_delete_slot(%s)", (slot,), (other_slot,)),
        "v2_reopen_slot": ("SELECT public.v2_reopen_slot(%s)", (slot,), (other_slot,)),
        "v2_add_person": ("SELECT public.v2_add_person(%s, %s, %s, %s, %s)",
                          (slot, "מועמד", "", "", False), (other_slot, "מועמד", "", "", False)),
        "v2_edit_person": ("SELECT public.v2_edit_person(%s, %s, %s, %s)",
                           (my_person, "050-1", None, None), (other_person, "050-1", None, None)),
        "v2_set_person_status": ("SELECT public.v2_set_person_status(%s, %s)",
                                 (my_person, "📩 נשלחה פנייה"), (other_person, "📩 נשלחה פנייה")),
        "v2_remove_person": ("SELECT public.v2_remove_person(%s)", (my_person,), (other_person,)),
    }
    missing = {"v2_set_topic": (2_000_000, "נושא"), "v2_add_slot": (2_000_000, "lesson")}
    before = state()
    refused_structure = {}
    for name, (q, mine_args, other_args) in doors.items():
        gone_args = missing.get(name, (2_000_000_000,) + mine_args[1:])
        refused_structure[name] = {
            "anon": call("anon", trainee, q, mine_args) == "denied",
            "signed out": (call("authenticated", None, q, mine_args) or {}).get("status") == "signed_out",
            "e-mail sign-up": (call("authenticated", {"email": EMAIL, "app_metadata": {"provider": "email"}},
                                    q, mine_args) or {}).get("status") == "wrong_provider",
            "unknown address": (call("authenticated", {"email": "someone@example.org", **GOOGLE}, q, mine_args)
                                or {}).get("status") == "not_linked",
            "another evening": (call("authenticated", trainee, q, other_args) or {}).get("status") == "forbidden",
            "missing": (call("authenticated", trainee, q, gone_args) or {}).get("status") == "forbidden",
            "the instructor": (call("authenticated", boss, q, mine_args) or {}).get("status") == "instructor",
        }
    bad = {name: [k for k, v in r.items() if not v] for name, r in refused_structure.items()
           if not all(r.values())}
    checks["structure: anon / signed out / e-mail / unknown / another evening / missing / instructor "
           "refused, at every one of the nine doors"] = not bad
    if bad:
        checks[f"structure refusals that failed: {bad}"] = False
    invalid = {
        "an empty topic": (doors["v2_set_topic"][0], (wf_mid, "   "), "invalid_text"),
        "a kind of slot": (doors["v2_add_slot"][0], (wf_mid, "אולם"), "invalid_kind"),
        "four minutes": (doors["v2_save_slot"][0], (slot, "", 4, "", "", "", ""), "invalid_duration"),
        "a javascript: link": (doors["v2_save_slot"][0], (slot, "", 75, "", "", "", "javascript:alert(1)"),
                               "invalid_url"),
        "a fifth room": (doors["v2_add_person"][0], (slot, "מעביר", "", "חדר אוכל", False), "invalid_room"),
        "a status of one's own": (doors["v2_set_person_status"][0], (my_person, "סגרנו בערך"), "invalid_status"),
    }
    wrong_answers = [k for k, (q, args, want) in invalid.items()
                     if (call("authenticated", trainee, q, args) or {}).get("status") != want]
    checks["structure: empty topic / unknown kind / 4 minutes / javascript: / a fifth room / "
           "an invented status → refused by name"] = not wrong_answers
    checks["structure: no refused call changed anything"] = state() == before

    # one write all the way: the answer is the evening as v2_workfile shows it now
    res = call("authenticated", trainee, doors["v2_add_person"][0], (slot, "מועמד בדיקה ב", "050-7654321", "", False))
    fresh = wf(trainee, wf_mid)
    ok_struct = (res or {}).get("status") == "ok"
    checks["structure: a person added → ok, and the answer IS a fresh v2_workfile"] = ok_struct \
        and res["workfile"] == fresh and any(p["name"] == "מועמד בדיקה ב" for l in fresh["lessons"]
                                             for p in l["people"])
    checks["structure: the answer — a phone only on a slot's people; no e-mail / contact"] = ok_struct \
        and all(p == ("workfile", "lessons", "[]", "people", "[]") for p in phone_paths(res)) \
        and not (keys_in(res) & {"email", "contact"})
    added_person = (res or {}).get("result", {}).get("person")
    cur.execute("RESET ROLE")
    cur.execute("SELECT count(*) FROM speaker_outreach WHERE student_id = %s", (me_id,))
    journal_before = cur.fetchone()[0]
    res = call("authenticated", trainee, doors["v2_set_person_status"][0], (added_person, "📩 נשלחה פנייה"))
    cur.execute("RESET ROLE")
    cur.execute("SELECT count(*) FROM speaker_outreach WHERE student_id = %s", (me_id,))
    checks["structure: a status → ok, one line in the journal, in the trainee's name"] = \
        (res or {}).get("status") == "ok" and cur.fetchone()[0] == journal_before + 1
    res = call("authenticated", trainee, doors["v2_remove_person"][0], (added_person,))
    cur.execute("RESET ROLE")
    cur.execute("SELECT count(*) FROM lesson_speakers WHERE id = %s", (added_person or 0,))
    checks["structure: the person removed → ok, gone"] = (res or {}).get("status") == "ok" \
        and cur.fetchone()[0] == 0

    # ---- the twins: the SQL copies of dm's rules must give the same answers
    cur.execute("RESET ROLE")
    texts = [n for _, needles in dm._CATEGORY_RULES for n in needles]
    cur.execute("SELECT DISTINCT task_description FROM tasks")
    texts += [r[0] for r in cur.fetchall()] + ["", "לשלוח תודה למרצים", "משימה בלי שום מילת מפתח"]
    cur.execute("SELECT t, v2_private.classify_task(t) FROM unnest(%s::text[]) AS t", (texts,))
    sql_cls = dict(cur.fetchall())
    wrong_cls = [t for t in texts if sql_cls.get(t) != dm.classify_task(t)]
    checks[f"twin: classify_task agrees on {len(set(texts))} texts (every needle, every task)"] = not wrong_cls
    wrong_due = []
    for d in ("15.10.2026", "1.1.2027", " 5.11.2026 ", "31.2.2027", "", "2026-10-15"):
        for c in [*dm.DEADLINE_OFFSETS_DAYS, None, "אחר"]:
            cur.execute("SELECT v2_private.due_date(%s, %s)::text", (d, c))
            if cur.fetchone()[0] != dm.compute_due_date(d, c):
                wrong_due.append((d, c))
    checks["twin: due_date agrees on every category × date (incl. bad dates)"] = not wrong_due

    # ---- the catalog
    for table in ("tasks", "students", "speakers", "v_tasks_full"):
        cur.execute("SET ROLE authenticated")
        try:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            checks[f"authenticated cannot read {table}"] = False
        except psycopg2.errors.InsufficientPrivilege:
            checks[f"authenticated cannot read {table}"] = True
        finally:
            cur.execute("RESET ROLE")
    for inner in ("SELECT * FROM v2_private.caller()", f"SELECT v2_private.home_of({me_id})",
                  f"SELECT v2_private.sync_lesson_tasks({wf_mid})",
                  "SELECT v2_private.record_outreach('✅ סגור', 'x', 1, 1)"):
        name = inner.split("v2_private.")[1].split("(")[0]
        cur.execute("SET ROLE authenticated")
        try:
            cur.execute(inner)
            checks[f"authenticated cannot call v2_private.{name}()"] = False
        except psycopg2.errors.InsufficientPrivilege:
            checks[f"authenticated cannot call v2_private.{name}()"] = True
        finally:
            cur.execute("RESET ROLE")
    cur.execute(LEAKS)
    leaks = [list(r) for r in cur.fetchall()]
    checks["catalog: only the sixteen doors, only for authenticated"] = leaks == EXPECTED_LEAKS

    if export and checks.get("linked address → ok (case-insensitive)"):
        # placeholders for people: the demo must not carry real names
        names = {me_name: "חניך/ה לדוגמה"}
        for m in ok["mishmarim"]:
            for n in m["owners"]:
                names.setdefault(n, f"שותף/ה {len(names)}")
        demo = json.loads(json.dumps(ok, ensure_ascii=False))
        demo["me"]["name"] = names[me_name]
        # what the live app shows: an evening before as_of has had its tasks
        # closed by the daily close (dm.close_past_mishmar_tasks) — all but the
        # feedback. The fixture exempts #05 from it for the sweep's sake.
        from datetime import date
        def _d(s):
            d, m, y = (int(x) for x in s.split("."))
            return date(y, m, d)
        as_of = date.fromisoformat(demo["as_of"])
        past = {m["id"] for m in demo["mishmarim"] if _d(m["gregorian_date"]) < as_of}
        for t in demo["tasks"]:
            if t["mishmar_id"] in past and "משוב" not in t["task_description"]:
                t["status"] = "DONE"
        for m in demo["mishmarim"]:
            m["owners"] = [names.get(n, n) for n in m["owners"]]
        Path(export).write_text(json.dumps(demo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if export_wf and ok_wf and checks.get("linked address → ok (case-insensitive)"):
        # the same placeholders as the home export, and the people on the slots
        # replaced too: a speaker's name and phone are real people's
        names = {me_name: "חניך/ה לדוגמה"}
        for m in ok["mishmarim"]:
            for n in m["owners"]:
                names.setdefault(n, f"שותף/ה {len(names)}")
        people: dict[str, str] = {}

        def person(n: str) -> str:
            return people.setdefault(n, f"מרצה {len(people) + 1}")

        demo = json.loads(json.dumps(wf(trainee, wf_mid), ensure_ascii=False))
        m = demo["mishmar"]
        m["owners"] = [names.get(n, n) for n in m["owners"]]
        m["note"] = m["invitation_url"] = None
        for l in demo["lessons"]:
            for p in l["people"]:
                p["name"] = person(p["name"])
                p["phone"] = f"050-000000{len(people) % 10}" if p.get("phone") else None
                p["source_url"] = None
            if l.get("speaker_name"):
                l["speaker_name"] = " · ".join(person(n) for n in l["speaker_name"].split(" · "))
            l["source_url"] = None
        for i in demo["logistics"]:
            i["detail"] = None
        # as the live app shows it: the home export's past-evening close, so
        # the two demos agree about the same evening
        from datetime import date
        d, mo, y = (int(x) for x in m["gregorian_date"].split("."))
        past = date(y, mo, d) < date.fromisoformat(demo["as_of"])
        for t in demo["tasks"]:
            t["details"] = None
            if past and "משוב" not in t["task_description"]:
                t["status"] = "DONE"
        Path(export_wf).write_text(json.dumps(demo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(json.dumps({"ok": all(checks.values()), "checks": checks,
                      "public_role_privileges": leaks,
                      "trainee_evenings": my_mids,
                      "tasks_returned": len(ok["tasks"]) if isinstance(ok, dict) and "tasks" in ok else None},
                     ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
