"""Prove v2's doors leak nothing — against the harness's local PostgreSQL 16.

    python3 scripts/harness/db.py up
    python3 web/supabase/test_v2.py [--on N] [--export web/src/demo.json]

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
  v2_set_task_status(task, status)
    anon, signed out, e-mail sign-up, unknown address → refused, nothing changes
    the linked trainee, a pair task of their evening  → «ok»: status and
        updated_at change, and no other column
    the partner's own task, another evening's task, a task that does not
        exist → «forbidden»; a status outside the table's three → «invalid_status»
  the catalog
    anon / authenticated hold no privilege on any table, view or sequence in
    `public`; EXECUTE on exactly the two doors, for `authenticated` only; and
    no way into `v2_private`, the schema behind them

`--on N` picks a trainee of evening N. `--export PATH` writes the «ok» answer,
names replaced by placeholders, as the front end's demo data. Prints one JSON
line; exit 1 on any failed check."""
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
EXPECTED_LEAKS = [["function", "public.v2_my_home", "authenticated"],
                  ["function", "public.v2_set_task_status", "authenticated"]]


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
    export = argv[argv.index("--export") + 1] if "--export" in argv else None
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
    for name, tid in (("partner's own task", partner_task), ("another evening's task", foreign_task),
                      ("a task that does not exist", 2_000_000_000)):
        if tid is None:
            continue
        was = row(tid)
        guarded[name] = (write(me, tid, "DONE") or {}).get("status") == "forbidden" and row(tid) == was
    checks["write: partner's / other evening's / missing task → forbidden, unchanged"] = \
        bool(guarded) and all(guarded.values())
    was = row(pair_task)
    checks["write: a status outside the three → invalid_status, unchanged"] = \
        (write(me, pair_task, "FINISHED") or {}).get("status") == "invalid_status" and row(pair_task) == was

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
    cur.execute("SET ROLE authenticated")
    try:
        cur.execute("SELECT * FROM v2_private.caller()")
        checks["authenticated cannot call v2_private.caller()"] = False
    except psycopg2.errors.InsufficientPrivilege:
        checks["authenticated cannot call v2_private.caller()"] = True
    finally:
        cur.execute("RESET ROLE")
    cur.execute(LEAKS)
    leaks = [list(r) for r in cur.fetchall()]
    checks["catalog: only the two doors, only for authenticated"] = leaks == EXPECTED_LEAKS

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

    print(json.dumps({"ok": all(checks.values()), "checks": checks,
                      "public_role_privileges": leaks,
                      "trainee_evenings": my_mids,
                      "tasks_returned": len(ok["tasks"]) if isinstance(ok, dict) and "tasks" in ok else None},
                     ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
