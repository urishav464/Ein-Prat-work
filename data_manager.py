"""
data_manager.py — the single data seam for the Mishmar management app.

SCOPE IS HARDCODED: שנה ב' · תשפ"ז · 5787 · 2026-2027 · מדרשת עין פרת.
21 Mishmarim, 10 trainees. There is no year-switcher and there must not be one.

Everything that touches persistent state goes through this module. Nothing else
in the codebase opens the database or reads the Markdown sources directly.

Why SQLite rather than .md/.csv: Streamlit runs every user session in its own
thread and reruns the script on every interaction. Concurrent writes to a flat
file lose data. SQLite in WAL mode gives us concurrent readers alongside a
single writer, which is the actual access pattern here.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date as _date, timedelta as _timedelta
from typing import Any, Iterable, Iterator, Optional

# --------------------------------------------------------------------------
# Scope constants — do not generalise
# --------------------------------------------------------------------------

ACADEMIC_YEAR_HE = 'תשפ"ז'
ACADEMIC_YEAR_NUM = 5787
GREGORIAN_SPAN = "2026-2027"
PROGRAMME = "שנה ב'"
INSTITUTION = "מדרשת עין פרת"

TOTAL_MISHMARIM = 21
TOTAL_STUDENTS = 10
STAFF_BUILT_MISHMARIM = (1, 2)  # #01 משמר בוגרים, #02 — built by staff, not pairs

# Budget: ₪500 per Mishmar is an *average indication* covering speakers and
# refreshments together. Overspend on a single Mishmar is NOT an error — it is
# drawn from the season-wide Mishmar budget line and balanced by cheaper nights.
# Per the instructor's decision there is deliberately NO season ceiling here:
# we track cumulative spend, we do not compare it to a cap.
PER_MISHMAR_BUDGET_NIS = 500
SEASON_BUDGET_CEILING_NIS = None  # intentionally unset — tracking only

TASK_STATUSES = ("TO DO", "IN PROGRESS", "DONE")
SPEAKER_SOURCE_TYPES = ("original_44", "web_search", "manual")

# Task categories drive the recommended deadlines below. They come from the
# opening deck (binyat-mishmar-mifgash-peticha.pptx, slide "מתי כדאי לסגור מה").
TASK_CATEGORIES = (
    "נושא", "מרצים", "הזמנה", "כיבוד", "קישוט", "תוכן", "לוגיסטיקה", "אחרי",
)

# Days BEFORE the Mishmar that each category is recommended to be closed.
# A negative value means "after the Mishmar".
#
# The deck frames these as "המלצה — לא חוק", and that framing is load-bearing:
# a trainee sees a gentle nudge, never a failure state. Only the instructor
# dashboard treats a passed date as something to act on.
DEADLINE_OFFSETS_DAYS = {
    "נושא": 21,
    "מרצים": 14,
    "הזמנה": 7,
    "כיבוד": 7,
    "קישוט": 7,
    "תוכן": 7,
    "לוגיסטיקה": 0,
    "אחרי": -7,
}

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(REPO_ROOT, "mishmar.db")
TASKS_MD = os.path.join(REPO_ROOT, "students_tasks.md")
TASKS_MD_ARCHIVED = os.path.join(REPO_ROOT, "students_tasks_ARCHIVED.md")
SPEAKERS_MD = os.path.join(
    REPO_ROOT, "Mishmer-section", "speakers", "database.md"
)


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------


@contextmanager
def get_connection(db_path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a configured connection, committing on success, rolling back on error.

    The three settings below are what make this safe under Streamlit:
      * WAL              — readers do not block the writer, and vice versa.
                           Without it, concurrent sessions hit "database is locked".
      * check_same_thread=False — Streamlit serves each session on its own thread.
      * timeout=10       — wait for a held lock instead of failing instantly.
    """
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _query(sql: str, params: Iterable[Any] = (), db_path: str = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS Mishmarim (
    id              INTEGER PRIMARY KEY,           -- 1..21, matches the folder number
    gregorian_date  TEXT    NOT NULL,              -- '24.9.2026'
    hebrew_date     TEXT    NOT NULL,              -- 'י״ג תשרי תשפ״ז'
    mishmar_type    TEXT,                          -- 'פנימי' / 'חיצוני'
    topic           TEXT,                          -- NULL = TBD. Never guessed.
    note            TEXT,
    workfile_path   TEXT,
    is_staff_built  INTEGER NOT NULL DEFAULT 0     -- 1 for #01 and #02
);

CREATE TABLE IF NOT EXISTS Students (
    id           INTEGER PRIMARY KEY,              -- 1..10
    name         TEXT    NOT NULL UNIQUE,          -- 'חניך 1' until real names arrive
    role         TEXT    NOT NULL DEFAULT 'student' -- 'student' | 'instructor'
);

-- Ownership is a PAIR per Mishmar, so it is many-to-many. Without this table
-- there is no way to answer "which Mishmarim belong to חניך 4".
CREATE TABLE IF NOT EXISTS Assignments (
    mishmar_id  INTEGER NOT NULL REFERENCES Mishmarim(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES Students(id)  ON DELETE CASCADE,
    PRIMARY KEY (mishmar_id, student_id)
);

CREATE TABLE IF NOT EXISTS Tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    mishmar_id        INTEGER NOT NULL REFERENCES Mishmarim(id) ON DELETE CASCADE,
    -- NULL = the task belongs to the Mishmar, i.e. to BOTH owners in the pair.
    -- Non-NULL = personally assigned to one trainee.
    student_id        INTEGER REFERENCES Students(id) ON DELETE SET NULL,
    task_description  TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'TO DO'
                              CHECK (status IN ('TO DO', 'IN PROGRESS', 'DONE')),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS Budget (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mishmar_id   INTEGER NOT NULL REFERENCES Mishmarim(id) ON DELETE CASCADE,
    expense_type TEXT    NOT NULL,                 -- 'מרצה' / 'כיבוד' / 'אחר'
    description  TEXT,                             -- speaker name, what was bought
    amount       REAL    DEFAULT 0,                -- planned / quoted
    actual_cost  REAL    DEFAULT 0,                -- actually paid. 0 = came free.
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS Speakers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    expertise_topics TEXT,                         -- free text, searched with LIKE
    verification_url TEXT,                         -- faculty page, institute, podcast
    -- 'original_44'  seeded from Mishmer-section/speakers/database.md
    -- 'web_search'   discovered by speaker_search.py
    -- 'manual'       typed in by a user
    source_type      TEXT    NOT NULL DEFAULT 'manual'
                             CHECK (source_type IN ('original_44','web_search','manual')),
    status           TEXT    DEFAULT '⬜ לא פנינו',
    lesson_fit       TEXT,                         -- '1', '2-3', ... maps to the 4-lesson arc
    region           TEXT,                         -- '🟢 ירושלים' etc. A consideration, not a filter.
    contact          TEXT,                         -- TBD unless a human filled it in
    notes            TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name, source_type)
);

-- Web-search response cache. All trainees share one machine and therefore one
-- IP, so the same query typed by two people must cost one network call, not
-- two. Keyed by a hash of query+backend+region.
CREATE TABLE IF NOT EXISTS SearchCache (
    query_hash   TEXT PRIMARY KEY,
    query_text   TEXT NOT NULL,
    results_json TEXT NOT NULL,
    -- 0 = the call failed or came back empty. Cached too, but for an hour
    -- rather than for weeks: without this a single blocked afternoon would
    -- poison the cache with empty results for the rest of the season.
    ok           INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_mishmar  ON Tasks(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON Tasks(status);
CREATE INDEX IF NOT EXISTS idx_budget_mishmar ON Budget(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_speakers_src   ON Speakers(source_type);
CREATE INDEX IF NOT EXISTS idx_cache_created  ON SearchCache(created_at);

-- budget_used is deliberately NOT a stored column on Mishmarim. A stored copy
-- drifts from the Budget rows it is derived from the moment anyone edits an
-- expense. Computing it in a view keeps one source of truth.
CREATE VIEW IF NOT EXISTS v_mishmar_budget AS
SELECT
    m.id                                   AS mishmar_id,
    m.gregorian_date                       AS gregorian_date,
    COALESCE(SUM(b.actual_cost), 0)        AS budget_used,
    ?                                      AS budget_nominal
FROM Mishmarim m
LEFT JOIN Budget b ON b.mishmar_id = m.id
GROUP BY m.id;
"""


# --------------------------------------------------------------------------
# Versioned migrations
#
# `CREATE TABLE IF NOT EXISTS` creates missing TABLES but never adds a missing
# COLUMN to a table that already exists. Since the schema is changing weekly
# right now, every change past the base schema goes in the numbered list below
# and is applied exactly once, tracked in _meta.schema_version.
# --------------------------------------------------------------------------

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, list[str]] = {
    2: [
        # Recommended-deadline support.
        "ALTER TABLE Tasks ADD COLUMN category TEXT",
        "ALTER TABLE Tasks ADD COLUMN due_date TEXT",
        # Google identity, for when the app is deployed and 10 trainees sign in.
        "ALTER TABLE Students ADD COLUMN email TEXT",

        # The evening's actual running order. Deliberately NOT four fixed rows:
        # real Mishmarim in the 2025-26 archive run a ceremony plus two
        # lessons, or a song circle. slot_order is 1..N and lesson_role is free
        # text so a ceremonial evening fits without being called malformed.
        """CREATE TABLE IF NOT EXISTS Lessons (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            mishmar_id     INTEGER NOT NULL REFERENCES Mishmarim(id) ON DELETE CASCADE,
            slot_order     INTEGER NOT NULL,
            start_time     TEXT,
            title          TEXT,
            description    TEXT,
            lesson_role    TEXT,
            speaker_name   TEXT,
            speaker_status TEXT DEFAULT '⬜ לא פנינו',
            format         TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_lessons_mishmar ON Lessons(mishmar_id)",

        # Post-Mishmar feedback. This is what turns the speaker index from a
        # contact list into institutional memory: next year's trainee sees not
        # just that someone taught here, but how it went.
        """CREATE TABLE IF NOT EXISTS Feedback (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            mishmar_id   INTEGER NOT NULL REFERENCES Mishmarim(id) ON DELETE CASCADE,
            student_id   INTEGER REFERENCES Students(id) ON DELETE SET NULL,
            lesson_id    INTEGER REFERENCES Lessons(id)  ON DELETE SET NULL,
            speaker_name TEXT,
            rating       INTEGER CHECK (rating BETWEEN 1 AND 5),
            what_worked  TEXT,
            what_didnt   TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_feedback_mishmar ON Feedback(mishmar_id)",

        # Chat history, per trainee per Mishmar, so a planning conversation
        # survives a page refresh and the instructor can see how it went.
        """CREATE TABLE IF NOT EXISTS ChatMessages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            mishmar_id INTEGER REFERENCES Mishmarim(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES Students(id)  ON DELETE SET NULL,
            role       TEXT NOT NULL CHECK (role IN ('user','assistant')),
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_chat_lookup ON ChatMessages(mishmar_id, student_id, id)",
    ],
}


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_version'"
    ).fetchone()
    if row:
        return int(row["value"])
    # No marker: a database created before migrations existed. Its tables match
    # version 1, so start there rather than re-running the base schema blindly.
    return 1


def _apply_migrations(conn: sqlite3.Connection) -> list[int]:
    applied = []
    current = _current_version(conn)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        for statement in MIGRATIONS[version]:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                # A column added by hand, or a half-applied upgrade, should not
                # wedge the app on every start. Anything else is a real error.
                if "duplicate column name" not in str(exc).lower():
                    raise
        applied.append(version)
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    return applied


def init_db(db_path: str = DB_PATH) -> list[int]:
    """Create the schema and bring it up to SCHEMA_VERSION. Safe on every start.

    Returns the migration versions applied this call (empty when already current).
    """
    # The view carries the nominal figure; sqlite has no parameter binding in
    # DDL, so substitute it before executing.
    schema = SCHEMA.replace("?", str(PER_MISHMAR_BUDGET_NIS))
    with get_connection(db_path) as conn:
        conn.executescript(schema)
        return _apply_migrations(conn)


# --------------------------------------------------------------------------
# Markdown parsing (migration only — these run once, then never again)
# --------------------------------------------------------------------------

_RE_INDEX_ROW = re.compile(r"^\|\s*(חניך\s*\d+)\s*\|(.+?)\|\s*\d+\s*\|\s*$")
_RE_MISHMAR_HEAD = re.compile(r"^###\s*משמר\s*#(\d+)\s*·\s*([^·]+?)\s*·\s*(.+?)\s*$")
_RE_META = re.compile(r"^\*\*סוג:\*\*\s*(.+?)\s*·\s*\*\*אחראים:\*\*\s*(.+?)\s*$")
_RE_WORKFILE = re.compile(r"\*\*קובץ עבודה:\*\*\s*`([^`]+)`")
_RE_SECTION = re.compile(r"^\*\*\[(TO DO|IN PROGRESS|DONE)\]\*\*\s*$")
_RE_TASK = re.compile(r"^-\s*\[([ xX])\]\s*(.+?)\s*$")


def parse_tasks_md(path: str) -> dict:
    """Parse students_tasks.md into {students, mishmarim, assignments, tasks}.

    The file carries dates, type and ownership as well as the task lists, so it
    seeds the whole schema — no second parser for schedule.md is needed.
    """
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    students: list[str] = []
    mishmarim: list[dict] = []
    assignments: list[tuple[int, str]] = []
    tasks: list[dict] = []

    current: Optional[dict] = None
    section = "TO DO"

    for line in lines:
        m = _RE_INDEX_ROW.match(line)
        if m and "משמרים" not in m.group(1):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            if name not in students:
                students.append(name)
            continue

        m = _RE_MISHMAR_HEAD.match(line)
        if m:
            current = {
                "id": int(m.group(1)),
                "gregorian_date": m.group(2).strip(),
                "hebrew_date": m.group(3).strip(),
                "mishmar_type": None,
                "note": None,
                "workfile_path": None,
            }
            mishmarim.append(current)
            section = "TO DO"
            continue

        if current is None:
            continue

        m = _RE_META.match(line)
        if m:
            current["mishmar_type"] = m.group(1).strip()
            owners_raw = m.group(2)
            # trailing free-text note after the owners, separated by '·'
            if "·" in owners_raw:
                owners_raw, _, note = owners_raw.partition("·")
                current["note"] = note.strip().strip("*") or None
            for owner in owners_raw.split("+"):
                owner = owner.strip()
                if owner.startswith("חניך"):
                    assignments.append((current["id"], re.sub(r"\s+", " ", owner)))
            continue

        m = _RE_WORKFILE.search(line)
        if m:
            current["workfile_path"] = m.group(1)
            continue

        m = _RE_SECTION.match(line)
        if m:
            section = m.group(1)
            continue

        m = _RE_TASK.match(line)
        if m:
            done = m.group(1).lower() == "x"
            tasks.append(
                {
                    "mishmar_id": current["id"],
                    "task_description": m.group(2).strip(),
                    # A ticked box is DONE regardless of which block it sits in.
                    "status": "DONE" if done else section,
                }
            )

    return {
        "students": students,
        "mishmarim": mishmarim,
        "assignments": assignments,
        "tasks": tasks,
    }


_RE_SPEAKER_ROW = re.compile(r"^\|(.+)\|\s*$")


def parse_speakers_md(path: str) -> list[dict]:
    """Parse the 8-column speaker table out of Mishmer-section/speakers/database.md."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    # Only the main table, which sits between '## הטבלה' and the status legend.
    start = text.find("## הטבלה")
    end = text.find("**סטטוסים:**", start if start >= 0 else 0)
    if start < 0:
        return []
    block = text[start : end if end > 0 else len(text)]

    out: list[dict] = []
    for line in block.split("\n"):
        m = _RE_SPEAKER_ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 8:
            continue
        name = cells[0]
        if name in ("שם",) or set(name) <= set("-: "):
            continue
        out.append(
            {
                "name": name.strip("*_ "),
                "expertise_topics": cells[1],
                "lesson_fit": cells[2],
                "region": cells[3],
                "status": cells[4],
                "notes": " · ".join(x for x in (cells[5], cells[7]) if x and x != "—"),
                "contact": cells[6],
                "verification_url": None,
                "source_type": "original_44",
            }
        )
    return out


# --------------------------------------------------------------------------
# Migration & deprecation
# --------------------------------------------------------------------------


def _flag(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT value FROM _meta WHERE key = ?", (key,)).fetchone()
    return row is not None


def migrate_and_archive_md(
    db_path: str = DB_PATH,
    tasks_md: str = TASKS_MD,
    speakers_md: str = SPEAKERS_MD,
    archived_md: str = TASKS_MD_ARCHIVED,
) -> dict:
    """Migrate students_tasks.md into SQLite, then archive the file.

    After this runs, SQLite is the sole source of truth for tasks. The Markdown
    file is *renamed*, not deleted — it holds 193 hand-written task lines and a
    rename is reversible where a delete is not.

    Idempotent: guarded by a _meta flag, and a no-op once the file is gone.
    """
    init_db(db_path)
    result = {
        "migrated": False,
        "reason": "",
        "students": 0,
        "mishmarim": 0,
        "tasks": 0,
        "speakers": 0,
        "archived_to": None,
    }

    with get_connection(db_path) as conn:
        if _flag(conn, "md_migrated"):
            result["reason"] = "already migrated"
            return result

    if not os.path.exists(tasks_md):
        result["reason"] = f"{os.path.basename(tasks_md)} not found — nothing to migrate"
        return result

    parsed = parse_tasks_md(tasks_md)
    speakers = parse_speakers_md(speakers_md)

    with get_connection(db_path) as conn:
        for idx, name in enumerate(parsed["students"], start=1):
            conn.execute(
                "INSERT OR IGNORE INTO Students (id, name, role) VALUES (?,?,'student')",
                (idx, name),
            )
        # The instructor is a first-class row so tasks can be reassigned to Uri.
        conn.execute(
            "INSERT OR IGNORE INTO Students (id, name, role) VALUES (?,?,'instructor')",
            (100, "Uri"),
        )

        for m in parsed["mishmarim"]:
            conn.execute(
                """INSERT OR IGNORE INTO Mishmarim
                   (id, gregorian_date, hebrew_date, mishmar_type, note,
                    workfile_path, is_staff_built)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    m["id"],
                    m["gregorian_date"],
                    m["hebrew_date"],
                    m["mishmar_type"],
                    m["note"],
                    m["workfile_path"],
                    1 if m["id"] in STAFF_BUILT_MISHMARIM else 0,
                ),
            )

        name_to_id = {
            r["name"]: r["id"]
            for r in conn.execute("SELECT id, name FROM Students").fetchall()
        }
        for mishmar_id, student_name in parsed["assignments"]:
            sid = name_to_id.get(student_name)
            if sid:
                conn.execute(
                    "INSERT OR IGNORE INTO Assignments (mishmar_id, student_id) VALUES (?,?)",
                    (mishmar_id, sid),
                )

        for t in parsed["tasks"]:
            conn.execute(
                """INSERT INTO Tasks (mishmar_id, student_id, task_description, status)
                   VALUES (?, NULL, ?, ?)""",
                (t["mishmar_id"], t["task_description"], t["status"]),
            )

        for s in speakers:
            conn.execute(
                """INSERT OR IGNORE INTO Speakers
                   (name, expertise_topics, verification_url, source_type,
                    status, lesson_fit, region, contact, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    s["name"], s["expertise_topics"], s["verification_url"],
                    s["source_type"], s["status"], s["lesson_fit"],
                    s["region"], s["contact"], s["notes"],
                ),
            )

        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('md_migrated', datetime('now'))"
        )

        result.update(
            migrated=True,
            students=len(parsed["students"]),
            mishmarim=len(parsed["mishmarim"]),
            tasks=len(parsed["tasks"]),
            speakers=len(speakers),
        )

    # Archive only after the transaction above committed successfully.
    shutil.move(tasks_md, archived_md)
    result["archived_to"] = archived_md
    result["reason"] = "migrated and archived"
    return result


# --------------------------------------------------------------------------
# CRUD — everything the Streamlit layer needs
# --------------------------------------------------------------------------


def get_all_mishmarim(db_path: str = DB_PATH) -> list[dict]:
    return _query(
        """SELECT m.*, b.budget_used, b.budget_nominal
           FROM Mishmarim m
           LEFT JOIN v_mishmar_budget b ON b.mishmar_id = m.id
           ORDER BY m.id""",
        db_path=db_path,
    )


def get_mishmar(mishmar_id: int, db_path: str = DB_PATH) -> Optional[dict]:
    rows = _query(
        """SELECT m.*, b.budget_used, b.budget_nominal
           FROM Mishmarim m
           LEFT JOIN v_mishmar_budget b ON b.mishmar_id = m.id
           WHERE m.id = ?""",
        (mishmar_id,),
        db_path=db_path,
    )
    return rows[0] if rows else None


def get_students(db_path: str = DB_PATH) -> list[dict]:
    return _query("SELECT * FROM Students ORDER BY id", db_path=db_path)


def get_mishmarim_for_student(student_id: int, db_path: str = DB_PATH) -> list[dict]:
    return _query(
        """SELECT m.* FROM Mishmarim m
           JOIN Assignments a ON a.mishmar_id = m.id
           WHERE a.student_id = ? ORDER BY m.id""",
        (student_id,),
        db_path=db_path,
    )


def get_tasks_for_student(student_id: int, db_path: str = DB_PATH) -> list[dict]:
    """Every task on the Mishmarim this trainee owns.

    Includes shared pair tasks (student_id IS NULL) and tasks assigned to them
    personally — which together is what their Kanban board should show.
    """
    return _query(
        """SELECT t.*, m.gregorian_date, m.hebrew_date, m.topic
           FROM Tasks t
           JOIN Mishmarim m   ON m.id = t.mishmar_id
           JOIN Assignments a ON a.mishmar_id = t.mishmar_id
           WHERE a.student_id = ?
             AND (t.student_id IS NULL OR t.student_id = ?)
           ORDER BY m.id, t.id""",
        (student_id, student_id),
        db_path=db_path,
    )


def get_tasks_for_mishmar(mishmar_id: int, db_path: str = DB_PATH) -> list[dict]:
    return _query(
        "SELECT * FROM Tasks WHERE mishmar_id = ? ORDER BY id",
        (mishmar_id,),
        db_path=db_path,
    )


def update_task_status(task_id: int, new_status: str, db_path: str = DB_PATH) -> bool:
    if new_status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}, got {new_status!r}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE Tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, task_id),
        )
        return cur.rowcount > 0


def add_task(
    mishmar_id: int,
    task_description: str,
    student_id: Optional[int] = None,
    status: str = "TO DO",
    category: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}, got {status!r}")
    category = category or classify_task(task_description)
    mishmar = get_mishmar(mishmar_id, db_path=db_path)
    due = compute_due_date(mishmar["gregorian_date"], category) if mishmar else None
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO Tasks
               (mishmar_id, student_id, task_description, status, category, due_date)
               VALUES (?,?,?,?,?,?)""",
            (mishmar_id, student_id, task_description, status, category, due),
        )
        return int(cur.lastrowid)


def set_mishmar_topic(mishmar_id: int, topic: str, db_path: str = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE Mishmarim SET topic = ? WHERE id = ?", (topic, mishmar_id)
        )
        return cur.rowcount > 0


def add_budget_entry(
    mishmar_id: int,
    expense_type: str,
    amount: float = 0,
    actual_cost: float = 0,
    description: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """Record one expense line. actual_cost=0 is meaningful: the speaker came free."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO Budget (mishmar_id, expense_type, description, amount, actual_cost)
               VALUES (?,?,?,?,?)""",
            (mishmar_id, expense_type, description, amount, actual_cost),
        )
        return int(cur.lastrowid)


def get_budget_summary(db_path: str = DB_PATH) -> dict:
    """Season-wide spend. There is no ceiling to compare against — by decision.

    `over_nominal` flags Mishmarim above the ₪500 indication. That is
    information, not an alarm: overspend is drawn from the season-wide line and
    balanced out by the many cheap nights.
    """
    per = _query(
        """SELECT m.id, m.gregorian_date, m.topic,
                  COALESCE(SUM(b.actual_cost), 0) AS spent
           FROM Mishmarim m LEFT JOIN Budget b ON b.mishmar_id = m.id
           GROUP BY m.id ORDER BY m.id""",
        db_path=db_path,
    )
    total = sum(r["spent"] for r in per)
    return {
        "per_mishmar": per,
        "total_spent": total,
        "nominal_per_mishmar": PER_MISHMAR_BUDGET_NIS,
        "season_ceiling": SEASON_BUDGET_CEILING_NIS,  # None — tracking only
        "over_nominal": [r["id"] for r in per if r["spent"] > PER_MISHMAR_BUDGET_NIS],
    }


def add_new_speaker(
    name: str,
    expertise_topics: Optional[str] = None,
    verification_url: Optional[str] = None,
    source_type: str = "web_search",
    status: str = "⬜ לא פנינו",
    lesson_fit: Optional[str] = None,
    region: Optional[str] = None,
    contact: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> Optional[int]:
    """Write a discovered speaker back to the index.

    This is how the index grows past the original 44 toward a genuinely broad
    pool. Contact details are never fabricated — leave them None unless a human
    supplied them.
    """
    if source_type not in SPEAKER_SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {SPEAKER_SOURCE_TYPES}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO Speakers
               (name, expertise_topics, verification_url, source_type,
                status, lesson_fit, region, contact, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, expertise_topics, verification_url, source_type,
             status, lesson_fit, region, contact, notes),
        )
        return int(cur.lastrowid) if cur.rowcount else None


def search_speakers_by_topic(
    topic: str, lesson: Optional[str] = None, db_path: str = DB_PATH
) -> list[dict]:
    """Look up the local index. This is a STARTING POINT, not the candidate set.

    speaker_search.py must still run a live web search alongside this. If every
    name proposed came out of this function, the search was too narrow.
    """
    # `notes` is searched too, and that is load-bearing rather than generous:
    # the parser puts "מה העביר אצלנו" there, which is often the strongest
    # topical signal we hold. גדי תורג'מן is filed under "הלכה, מחשבת הרמב"ם"
    # but his notes read "הלכות תשובה ברמב״ם · מועמד טבעי לכל משמר תשובה" —
    # searching topics alone hides exactly the person we most wanted.
    sql = """SELECT * FROM Speakers
             WHERE (expertise_topics LIKE ? OR name LIKE ? OR notes LIKE ?)"""
    params: list[Any] = [f"%{topic}%", f"%{topic}%", f"%{topic}%"]
    if lesson:
        # An unrecorded lesson_fit means "we never wrote it down", not "not
        # suitable" — dropping those silently would bury real candidates.
        sql += " AND (lesson_fit LIKE ? OR lesson_fit IS NULL OR lesson_fit = 'TBD')"
        params.append(f"%{lesson}%")
    return _query(sql + " ORDER BY source_type, name", params, db_path=db_path)


# --------------------------------------------------------------------------
# Task categories and recommended deadlines
# --------------------------------------------------------------------------

# First match wins, so order matters. Two rules must stay at the top:
#   * "אחרי" before "מרצים", or "עדכון מאגר המרצים" (an after-the-night task)
#     would be filed as speaker work and get a due date two weeks too early.
#   * "לוגיסטיקה" before "תוכן", so "סידור חדרי חבורות (ביום המשמר)" is not
#     read as content work because it mentions חבורות.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("אחרי",       ("(אחרי)", "סיכום ולקחים", "תודות", "עדכון מאגר")),
    ("לוגיסטיקה",  ("ביום המשמר", "סידור חדר", "חדרים", "קבלת פני")),
    ("נושא",       ("סגירת נושא", "בחירת נושא", "נושא המשמר")),
    ("מרצים",      ("מרצים", "מרצה")),
    ("הזמנה",      ("הזמנה", "הזמנת", "קנבה", "הדפסה", "הפצה")),
    ("כיבוד",      ("כיבוד", "רשימת קניות", "ארוחת", "קניות")),
    ("קישוט",      ("קישוט",)),
    ("תוכן",       ("חברותות", "חבורות", "מקורות", "טקסט", "לוח זמנים", "לוז", "שיעור")),
)


def classify_task(description: str) -> Optional[str]:
    """Map a free-text task line to one of TASK_CATEGORIES, or None if unclear.

    None is a legitimate answer: an unclassified task simply carries no
    recommended date, which is better than inventing a deadline for it.
    """
    text = description or ""
    for category, needles in _CATEGORY_RULES:
        if any(n in text for n in needles):
            return category
    return None


def parse_gregorian(date_str: str) -> Optional[_date]:
    """Parse the repo's 'D.M.YYYY' date format (e.g. '24.9.2026')."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", date_str or "")
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return _date(year, month, day)
    except ValueError:
        return None


def compute_due_date(gregorian_date: str, category: Optional[str]) -> Optional[str]:
    """Recommended closing date as ISO 'YYYY-MM-DD', or None if not derivable."""
    if not category or category not in DEADLINE_OFFSETS_DAYS:
        return None
    base = parse_gregorian(gregorian_date)
    if base is None:
        return None
    return (base - _timedelta(days=DEADLINE_OFFSETS_DAYS[category])).isoformat()


def backfill_task_metadata(db_path: str = DB_PATH) -> dict:
    """Fill category and due_date on tasks that have none. Never overwrites.

    Runs on every start. Tasks migrated from the Markdown carry neither field,
    and a trainee opening the app should see recommended dates immediately.
    """
    rows = _query(
        """SELECT t.id, t.task_description, t.category, m.gregorian_date
           FROM Tasks t JOIN Mishmarim m ON m.id = t.mishmar_id
           WHERE t.category IS NULL OR t.due_date IS NULL""",
        db_path=db_path,
    )
    filled, unclassified = 0, 0
    with get_connection(db_path) as conn:
        for r in rows:
            category = r["category"] or classify_task(r["task_description"])
            if not category:
                unclassified += 1
                continue
            due = compute_due_date(r["gregorian_date"], category)
            conn.execute(
                "UPDATE Tasks SET category = ?, due_date = ? WHERE id = ?",
                (category, due, r["id"]),
            )
            filled += 1
    return {"examined": len(rows), "filled": filled, "unclassified": unclassified}


def _he_days(n: int) -> str:
    """Hebrew day counts. '1 ימים' reads as broken Hebrew to every trainee."""
    if n == 1:
        return "יום"
    if n == 2:
        return "יומיים"
    return f"{n} ימים"


def annotate_deadline(task: dict, today: Optional[_date] = None) -> dict:
    """Attach days_left and a nudge label to a task row.

    The opening deck calls these dates "המלצה — לא חוק", so the wording here
    stays soft. `overdue` is a fact the instructor dashboard can act on; what
    the trainee sees is a nudge, never a failure state.
    """
    today = today or _date.today()
    out = dict(task)
    out["days_left"] = None
    out["overdue"] = False
    out["nudge"] = ""

    if task.get("status") == "DONE" or not task.get("due_date"):
        return out

    try:
        due = _date.fromisoformat(task["due_date"])
    except (ValueError, TypeError):
        return out

    days = (due - today).days
    out["days_left"] = days
    if days < 0:
        out["overdue"] = True
        out["nudge"] = f"מומלץ היה לסגור {_he_days(abs(days))} קודם"
    elif days == 0:
        out["nudge"] = "מומלץ לסגור היום"
    elif days <= 3:
        out["nudge"] = f"מומלץ לסגור בעוד {_he_days(days)}"
    return out


def get_speaker_by_name(name: str, db_path: str = DB_PATH) -> list[dict]:
    """Every index row matching this name.

    Returns a LIST, not a single row, and that is deliberate: flag ה7 in
    Mishmer-section/speakers/database.md records up to four different people
    called אורי, with the standing instruction "אל תאחד אותם על דעתך". Handing
    back one row would be exactly that merge. The caller shows all of them.
    """
    return _query(
        "SELECT * FROM Speakers WHERE name = ? OR name LIKE ? ORDER BY source_type",
        (name, f"%{name}%"),
        db_path=db_path,
    )


# --------------------------------------------------------------------------
# Search cache — used by speaker_search.py
# --------------------------------------------------------------------------

CACHE_TTL_DAYS_OK = 60      # speaker facts are stable for months
CACHE_TTL_HOURS_FAIL = 1    # a failure is transient; do not cache it for weeks


def _cache_key(query: str, backend: str = "", region: str = "") -> str:
    import hashlib

    return hashlib.sha256(f"{query}|{backend}|{region}".encode("utf-8")).hexdigest()


def cache_get(
    query: str,
    backend: str = "",
    region: str = "",
    db_path: str = DB_PATH,
) -> Optional[list[dict]]:
    """Return cached results, or None on a miss or an expired entry."""
    import json

    rows = _query(
        "SELECT results_json, ok, created_at FROM SearchCache WHERE query_hash = ?",
        (_cache_key(query, backend, region),),
        db_path=db_path,
    )
    if not rows:
        return None

    row = rows[0]
    # Two different lifetimes, chosen by whether the call actually worked.
    if row["ok"]:
        expiry = f"-{CACHE_TTL_DAYS_OK} days"
    else:
        expiry = f"-{CACHE_TTL_HOURS_FAIL} hours"

    fresh = _query(
        "SELECT 1 AS ok FROM SearchCache WHERE query_hash = ? AND created_at > datetime('now', ?)",
        (_cache_key(query, backend, region), expiry),
        db_path=db_path,
    )
    if not fresh:
        return None
    return json.loads(row["results_json"])


def cache_put(
    query: str,
    results: list[dict],
    ok: bool = True,
    backend: str = "",
    region: str = "",
    db_path: str = DB_PATH,
) -> None:
    import json

    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO SearchCache
               (query_hash, query_text, results_json, ok, created_at)
               VALUES (?,?,?,?, datetime('now'))""",
            (
                _cache_key(query, backend, region),
                query,
                json.dumps(results, ensure_ascii=False),
                1 if ok else 0,
            ),
        )


def cache_stats(db_path: str = DB_PATH) -> dict:
    rows = _query(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_rows,
                  MAX(created_at) AS newest
           FROM SearchCache""",
        db_path=db_path,
    )
    r = rows[0] if rows else {}
    return {
        "total": r.get("total") or 0,
        "ok": r.get("ok_rows") or 0,
        "newest": r.get("newest"),
    }


def get_speaker_stats(db_path: str = DB_PATH) -> dict:
    rows = _query(
        "SELECT source_type, COUNT(*) AS n FROM Speakers GROUP BY source_type",
        db_path=db_path,
    )
    return {r["source_type"]: r["n"] for r in rows}


# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# Lessons — the evening's running order
#
# Deliberately not fixed at four. The 2025-26 archive holds a ceremony plus two
# lessons, and a song circle; the four-lesson arc is the strong default the
# generator emits, not a constraint the data model should enforce.
# --------------------------------------------------------------------------


def get_lessons(mishmar_id: int, db_path: str = DB_PATH) -> list[dict]:
    return _query(
        "SELECT * FROM Lessons WHERE mishmar_id = ? ORDER BY slot_order",
        (mishmar_id,),
        db_path=db_path,
    )


def upsert_lesson(
    mishmar_id: int,
    slot_order: int,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    description: Optional[str] = None,
    lesson_role: Optional[str] = None,
    speaker_name: Optional[str] = None,
    speaker_status: Optional[str] = None,
    fmt: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """Insert or update one slot. Only non-None fields are written."""
    existing = _query(
        "SELECT id FROM Lessons WHERE mishmar_id = ? AND slot_order = ?",
        (mishmar_id, slot_order),
        db_path=db_path,
    )
    fields = {
        "start_time": start_time, "title": title, "description": description,
        "lesson_role": lesson_role, "speaker_name": speaker_name,
        "speaker_status": speaker_status, "format": fmt,
    }
    given = {k: v for k, v in fields.items() if v is not None}
    with get_connection(db_path) as conn:
        if existing:
            if given:
                sets = ", ".join(f"{k} = ?" for k in given)
                conn.execute(
                    f"UPDATE Lessons SET {sets} WHERE id = ?",
                    (*given.values(), existing[0]["id"]),
                )
            return int(existing[0]["id"])
        cols = ["mishmar_id", "slot_order", *given.keys()]
        cur = conn.execute(
            f"INSERT INTO Lessons ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            (mishmar_id, slot_order, *given.values()),
        )
        return int(cur.lastrowid)


def delete_lesson(lesson_id: int, db_path: str = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        return conn.execute("DELETE FROM Lessons WHERE id = ?", (lesson_id,)).rowcount > 0


# --------------------------------------------------------------------------
# Feedback — what turns the speaker index into institutional memory
# --------------------------------------------------------------------------


def add_feedback(
    mishmar_id: int,
    rating: Optional[int] = None,
    speaker_name: Optional[str] = None,
    lesson_id: Optional[int] = None,
    student_id: Optional[int] = None,
    what_worked: Optional[str] = None,
    what_didnt: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("rating must be between 1 and 5")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO Feedback
               (mishmar_id, student_id, lesson_id, speaker_name, rating,
                what_worked, what_didnt)
               VALUES (?,?,?,?,?,?,?)""",
            (mishmar_id, student_id, lesson_id, speaker_name, rating,
             what_worked, what_didnt),
        )
        return int(cur.lastrowid)


def get_feedback_for_mishmar(mishmar_id: int, db_path: str = DB_PATH) -> list[dict]:
    return _query(
        "SELECT * FROM Feedback WHERE mishmar_id = ? ORDER BY id",
        (mishmar_id,),
        db_path=db_path,
    )


def get_feedback_for_speaker(name: str, db_path: str = DB_PATH) -> list[dict]:
    """Every past rating and note for a speaker — the 'how did it go' half.

    This is what a trainee two years from now gets that today's trainee does
    not: not just that someone taught here, but whether it worked.
    """
    return _query(
        """SELECT f.*, m.gregorian_date, m.topic
           FROM Feedback f JOIN Mishmarim m ON m.id = f.mishmar_id
           WHERE f.speaker_name = ? ORDER BY f.id DESC""",
        (name,),
        db_path=db_path,
    )


# --------------------------------------------------------------------------
# Chat history
# --------------------------------------------------------------------------


def add_chat_message(
    role: str, content: str, mishmar_id: Optional[int] = None,
    student_id: Optional[int] = None, db_path: str = DB_PATH,
) -> int:
    if role not in ("user", "assistant"):
        raise ValueError("role must be 'user' or 'assistant'")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO ChatMessages (mishmar_id, student_id, role, content)
               VALUES (?,?,?,?)""",
            (mishmar_id, student_id, role, content),
        )
        return int(cur.lastrowid)


def get_chat_history(
    mishmar_id: Optional[int] = None, student_id: Optional[int] = None,
    limit: int = 100, db_path: str = DB_PATH,
) -> list[dict]:
    sql = "SELECT * FROM ChatMessages WHERE 1=1"
    params: list[Any] = []
    if mishmar_id is not None:
        sql += " AND mishmar_id = ?"; params.append(mishmar_id)
    if student_id is not None:
        sql += " AND student_id = ?"; params.append(student_id)
    rows = _query(sql + " ORDER BY id DESC LIMIT ?", (*params, limit), db_path=db_path)
    return list(reversed(rows))


def clear_chat_history(
    mishmar_id: int, student_id: int, db_path: str = DB_PATH
) -> int:
    with get_connection(db_path) as conn:
        return conn.execute(
            "DELETE FROM ChatMessages WHERE mishmar_id = ? AND student_id = ?",
            (mishmar_id, student_id),
        ).rowcount


def bootstrap(db_path: str = DB_PATH) -> dict:
    """Call once at app start: create the schema, migrate the Markdown if present."""
    init_db(db_path)
    result = migrate_and_archive_md(db_path=db_path)
    result["deadlines"] = backfill_task_metadata(db_path=db_path)
    return result


if __name__ == "__main__":
    info = bootstrap()
    print(f"DB: {DB_PATH}")
    print(f"scope: {PROGRAMME} {ACADEMIC_YEAR_HE} ({ACADEMIC_YEAR_NUM}) — {INSTITUTION}")
    print(info)
