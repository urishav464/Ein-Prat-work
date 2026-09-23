#!/usr/bin/env python3
"""The harness database: a local PostgreSQL 16 standing in for Supabase.

    python3 scripts/harness/db.py up            # start (initdb on first use) + build the fixture if stale
    python3 scripts/harness/db.py fresh NAME    # a throwaway copy of the fixture, printed as a DSN
    python3 scripts/harness/db.py down          # stop the server

Every command prints ONE JSON line — `{"ok": true, ...}` or `{"ok": false,
"blocked": "<why>"}` — so an agent reads the outcome instead of a log.

The fixture (`mishmar_fixture`, a template database) is built the way
production is: the Supabase roles, `supabase_schema.sql` applied TWICE (a file
that fails its second run blocks every future migration), then the app's own
first-run seed from `students_tasks.md` through the PostgREST shim, then a
small deterministic state so every screen has something to draw — two evenings
with a closed topic and the default timeline, one candidate, two DONE tasks.
It is rebuilt only when the schema or the seed file changed (their hash is
stored as the database comment).

Test-only. Nothing here touches Supabase or reads Streamlit secrets."""
import hashlib, json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PG_BIN = Path(os.environ.get("MISHMAR_PG_BIN", "/usr/lib/postgresql/16/bin"))
DATA = Path(os.environ.get("MISHMAR_PG_DATA", "/tmp/mishmar-pg"))
PORT = int(os.environ.get("MISHMAR_PG_PORT", "55432"))
SOCK = "/tmp"
FIXTURE = "mishmar_fixture"
LOGFILE = "/tmp/mishmar-pg.log"


def out(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False))


def dsn(db: str) -> str:
    return f"host={SOCK} port={PORT} dbname={db} user=postgres"


def _as_postgres(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run a PostgreSQL binary as the `postgres` user (initdb refuses root)."""
    if os.geteuid() == 0:
        cmd = ["su", "postgres", "-c", " ".join(_sh(a) for a in args)]
    else:
        cmd = args
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True)


def _sh(a: str) -> str:
    return "'" + a.replace("'", "'\\''") + "'"


def psql(sql: str, db: str = "postgres") -> str:
    r = _as_postgres([str(PG_BIN / "psql"), "-h", SOCK, "-p", str(PORT), "-d", db,
                      "-v", "ON_ERROR_STOP=1", "-q", "-tA", "-f", "-"], stdin=sql)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:400])
    return r.stdout.strip()


def running() -> bool:
    r = _as_postgres([str(PG_BIN / "pg_ctl"), "-D", str(DATA), "status"])
    return r.returncode == 0


def start() -> None:
    if not (PG_BIN / "pg_ctl").exists():
        raise SystemExit(out(ok=False, blocked=f"PostgreSQL 16 is not installed ({PG_BIN}); "
                                              "apt-get install -y postgresql-16") or 1)
    if not (DATA / "PG_VERSION").exists():
        r = _as_postgres([str(PG_BIN / "initdb"), "-D", str(DATA), "-A", "trust", "-E", "UTF8",
                          "--locale=C.UTF-8"])
        if r.returncode:
            raise SystemExit(out(ok=False, blocked="initdb failed: " + r.stderr.strip()[:300]) or 1)
    if not running():
        # `-l` matters: without a log file the postmaster keeps the caller's
        # stdout open and the command never returns
        r = _as_postgres([str(PG_BIN / "pg_ctl"), "-D", str(DATA), "-l", LOGFILE, "-w",
                          "-o", f"-p {PORT} -k {SOCK}", "start"])
        if r.returncode:
            raise SystemExit(out(ok=False, blocked="pg_ctl start failed: "
                                 + (r.stderr or r.stdout).strip()[:300]) or 1)


def fingerprint() -> str:
    h = hashlib.sha256()
    for f in ("supabase_schema.sql", "students_tasks.md", "scripts/harness/db.py"):
        h.update((ROOT / f).read_bytes())
    return h.hexdigest()[:16]


def exists(db: str) -> bool:
    return psql(f"SELECT 1 FROM pg_database WHERE datname = '{db}'") == "1"


def drop(db: str) -> None:
    if exists(db):
        psql(f"UPDATE pg_database SET datistemplate = false WHERE datname = '{db}';"
             f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db}';")
        psql(f'DROP DATABASE "{db}"')


ROLES = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END $$;
"""


def _seed(db: str) -> dict:
    """The app's own seed, then the fixture state — in a child process so the
    shim's DSN and the no-cache flag stay out of this one."""
    code = r'''
import json, os, sys
sys.path.insert(0, os.environ["ROOT"]); sys.path.insert(0, os.environ["HERE"])
import pgrest_shim, data_manager as dm
dm.set_client(pgrest_shim.FakeSupabase())
seed = dm.seed_from_markdown()
dm.backfill_speaker_domains()
state = {}
for mid, topic in ((3, "נושא בדיקה — זיכרון ושכחה"), (5, "נושא בדיקה — גבולות הסמכות")):
    dm.set_mishmar_topic(mid, topic)
    state[f"timeline_{mid}"] = dm.create_default_timeline(mid)
    dm.sync_lesson_tasks(mid)
slot = next(l for l in dm.get_lessons(5) if not l.get("is_break"))
dm.add_lesson_speaker(slot["id"], "מרצה בדיקה ה")
done = [t for t in dm.get_tasks_for_mishmar(3) if t.get("status") != "DONE"][:2]
for t in done:
    dm.update_task_status(t["id"], "DONE")
state["done"] = len(done)
print(json.dumps({"seeded": seed.get("seeded"), "tasks": seed.get("tasks"), **state}))
'''
    env = dict(os.environ, ROOT=str(ROOT), HERE=str(HERE), MISHMAR_NO_CACHE="1",
               MISHMAR_PG_DSN=dsn(db))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       cwd=str(ROOT))
    if r.returncode:
        raise RuntimeError("seed failed: " + (r.stderr.strip().splitlines() or ["?"])[-1][:300])
    return json.loads(r.stdout.strip().splitlines()[-1])


def build_fixture() -> dict:
    drop(FIXTURE)
    psql(ROLES)
    psql(f'CREATE DATABASE "{FIXTURE}"')
    schema = (ROOT / "supabase_schema.sql").read_text(encoding="utf-8")
    psql(schema, FIXTURE)
    psql(schema, FIXTURE)                 # the second run must succeed too
    seeded = _seed(FIXTURE)
    psql(f"COMMENT ON DATABASE \"{FIXTURE}\" IS '{fingerprint()}';"
         f'ALTER DATABASE "{FIXTURE}" WITH IS_TEMPLATE true;')
    return seeded


def up() -> None:
    start()
    fp = fingerprint()
    have = psql(f"SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                f"WHERE datname = '{FIXTURE}'")
    if have == fp:
        out(ok=True, fixture=FIXTURE, rebuilt=False, dsn=dsn(FIXTURE))
        return
    try:
        seeded = build_fixture()
    except RuntimeError as exc:
        out(ok=False, blocked=f"fixture build failed: {exc}")
        sys.exit(1)
    out(ok=True, fixture=FIXTURE, rebuilt=True, dsn=dsn(FIXTURE), **seeded)


def fresh(name: str) -> None:
    if name == FIXTURE or not name.replace("_", "").isalnum():
        out(ok=False, blocked=f"bad database name {name!r}")
        sys.exit(1)
    up_quiet()
    drop(name)
    psql(f'CREATE DATABASE "{name}" TEMPLATE "{FIXTURE}"')
    out(ok=True, db=name, dsn=dsn(name))


def up_quiet() -> None:
    start()
    have = psql(f"SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                f"WHERE datname = '{FIXTURE}'")
    if have != fingerprint():
        build_fixture()


def down() -> None:
    if (DATA / "PG_VERSION").exists() and running():
        _as_postgres([str(PG_BIN / "pg_ctl"), "-D", str(DATA), "-m", "fast", "stop"])
    out(ok=True, running=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "up"
    try:
        if cmd == "up":
            up()
        elif cmd == "fresh" and len(sys.argv) > 2:
            fresh(sys.argv[2])
        elif cmd == "down":
            down()
        else:
            out(ok=False, blocked="usage: db.py up | fresh NAME | down")
            sys.exit(2)
    except RuntimeError as exc:
        out(ok=False, blocked=str(exc))
        sys.exit(1)
