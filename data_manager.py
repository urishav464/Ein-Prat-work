"""
data_manager.py — the single data seam for the Mishmar management app.

SCOPE IS HARDCODED: שנה ב' · תשפ"ז · 5787 · 2026-2027 · מדרשת עין פרת.
21 Mishmarim, 10 trainees. There is no year-switcher and there must not be one.

STORAGE IS SUPABASE. Nothing else in the codebase talks to it. Credentials come
from Streamlit Secrets (SUPABASE_URL, SUPABASE_KEY) — there is no .env file and
no local database, because the app runs on Streamlit Cloud where the container
disk is wiped on every redeploy.

TWO HALVES, and the split is forced by the platform: the REST API can read and
write rows but CANNOT create tables. Structure therefore lives in
`supabase_schema.sql`, pasted once into the Supabase SQL Editor, and this module
only uses it. Anything needing a join or an aggregate is a VIEW in that file,
because PostgREST cannot express one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from typing import Any, Optional

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
STAFF_BUILT_MISHMARIM = (1, 2)

# ₪500 per Mishmar is an *average indication* covering speakers and refreshments
# together. Overspend on one night is NOT an error — it is drawn from the
# season-wide line and balanced by the many cheap nights. Deliberately no ceiling.
PER_MISHMAR_BUDGET_NIS = 500
SEASON_BUDGET_CEILING_NIS = None

TASK_STATUSES = ("TO DO", "IN PROGRESS", "DONE")
SPEAKER_SOURCE_TYPES = ("original_44", "web_search", "manual")

# The outreach ladder, from templates/mishmar-workfile-template.md.
# ⚠️ Three documents word this differently ("✅ אישר/לימד" vs "✅ אישר" vs
# "✅ סגור"). The code follows the work-file template; reconciling the prose is
# Uri's call, so it is flagged rather than silently rewritten.
# «⏳ ממתין לתשובה» מוזג לתוך «📩 נשלחה פנייה» (סכימה v2) — היו אותו מצב.
SPEAKER_STATUSES = (
    "⬜ לא פנינו", "📩 נשלחה פנייה",
    "✅ סגור", "❌ לא יכול/ה", "⚠️ בתנאי",
)

TASK_CATEGORIES = (
    "נושא", "מרצים", "הזמנה", "כיבוד", "קישוט", "תוכן", "לוגיסטיקה",
    "יום המשמר", "אחרי",
)

# Days BEFORE the Mishmar each category is recommended to close. Negative = after.
# The opening deck calls these "המלצה — לא חוק", and that framing is load-bearing:
# a trainee sees a nudge; only the instructor view treats a passed date as action.
DEADLINE_OFFSETS_DAYS = {
    "נושא": 21, "מרצים": 14, "הזמנה": 7, "כיבוד": 7,
    "קישוט": 7, "תוכן": 7, "לוגיסטיקה": 0, "יום המשמר": 0, "אחרי": -7,
}

CACHE_TTL_DAYS_OK = 60
CACHE_TTL_HOURS_FAIL = 1

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
TASKS_MD = os.path.join(REPO_ROOT, "students_tasks.md")
SPEAKERS_MD = os.path.join(REPO_ROOT, "Mishmer-section", "speakers", "database.md")

# Titles are NOT part of a name. Split out on the way in, joined for display.
_TITLE_RE = re.compile(
    r"^\s*(ד[״\"']ר|דר[׳']|פרופ[׳']?|פרופסור|הרב(?:נית)?|עו[״\"']ד)\s+(.+)$"
)


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------


class StorageUnavailable(RuntimeError):
    """No credentials, no client library, or the schema was never installed.

    Raised rather than returning empty so the UI can say what to fix instead of
    rendering a convincingly empty app.
    """


_client = None
_key_info: dict = {}


def normalize_supabase_url(url: str) -> str:
    """Accept what a person actually pastes, not only the canonical form.

    The client appends `/rest/v1` itself, so a URL that already ends in it
    builds `/rest/v1/rest/v1/<table>` and PostgREST answers PGRST125 "Invalid
    path specified in request URL" — which looks nothing like a credentials
    problem and reads, wrongly, as a missing schema. Supabase's dashboard does
    display that REST endpoint, so pasting it is the obvious mistake to make.
    Surrounding whitespace is stripped too: the client rejects it outright, and
    a trailing newline is easy to carry into a secrets box.
    """
    clean = (url or "").strip().rstrip("/")
    for suffix in ("/rest/v1", "/rest"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)].rstrip("/")
    # The dashboard URL cannot be repaired by trimming — it is a different host
    # entirely — and it is the other easy paste, since it is what the browser
    # address bar shows while you are copying the keys.
    if "supabase.com/dashboard" in clean or "supabase.com/project" in clean:
        raise StorageUnavailable(
            "ה-`SUPABASE_URL` הוא כתובת הדשבורד, לא כתובת ה-API. צריך "
            "`https://<project-ref>.supabase.co` — Supabase → Project Settings "
            "→ API → Project URL."
        )
    return clean


def describe_key(key: str) -> dict:
    """Which Supabase role does this key actually carry?

    Worth doing locally, because "wrong key type" is otherwise diagnosed by
    guesswork: a legacy key is a JWT whose payload names the role outright, and
    the current keys announce themselves by prefix. Reading it turns "it might
    be the anon key" into "your key says role=anon", which is the difference
    between a hint and an answer. Signature is NOT verified and must not be —
    this only reads a claim in order to explain an error.
    """
    key = (key or "").strip()
    if not key:
        return {"role": None, "kind": "missing"}
    # Current-generation keys: the role is the prefix.
    if key.startswith("sb_secret_"):
        return {"role": "service_role", "kind": "secret"}
    if key.startswith("sb_publishable_"):
        return {"role": "anon", "kind": "publishable"}
    parts = key.split(".")
    if len(parts) == 3:
        try:
            import base64
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return {"role": claims.get("role"), "kind": "legacy_jwt"}
        except Exception:
            pass
    return {"role": None, "kind": "unrecognised"}


def get_client():
    """The Supabase client, built once per process from Streamlit Secrets."""
    global _client
    if _client is not None:
        return _client

    try:
        from supabase import create_client
    except ImportError as exc:
        raise StorageUnavailable(
            "החבילה `supabase` לא מותקנת. הוסיפו אותה ל-requirements.txt."
        ) from exc

    url = key = None
    try:
        import streamlit as st

        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        pass
    # Env vars are a fallback for scripts and tests only. The deployed app is
    # expected to use Streamlit Secrets.
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise StorageUnavailable(
            "חסרים SUPABASE_URL / SUPABASE_KEY ב-Secrets של Streamlit. "
            "ראו DEPLOY.md."
        )
    global _key_info
    _key_info = describe_key(key)
    _client = create_client(normalize_supabase_url(url), (key or "").strip())
    return _client


def set_client(client) -> None:
    """Inject a client. Used by tests; the app never calls this."""
    global _client
    _client = client


def _t(table: str):
    return get_client().table(table)


def _rows(resp) -> list[dict]:
    return list(getattr(resp, "data", None) or [])


def _one(resp) -> Optional[dict]:
    rows = _rows(resp)
    return rows[0] if rows else None


def _now_iso() -> str:
    return _datetime.utcnow().isoformat()


def storage_ready() -> dict:
    """Cheap probe: are the credentials good and has the schema been installed?"""
    try:
        get_client()
    except StorageUnavailable as exc:
        return {"ok": False, "reason": str(exc)}
    try:
        _rows(_t("app_meta").select("key").limit(1).execute())
        return {"ok": True, "reason": ""}
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        low = detail.lower()

        # Each of these needs a DIFFERENT fix, and they are indistinguishable
        # from the client unless the code is read. Guessing "the tables are
        # missing" for all of them sends someone to the SQL Editor to re-run a
        # schema that was never the problem.
        if "pgrst125" in low or "invalid path" in low:
            reason = (
                "ה-`SUPABASE_URL` שגוי. הוא צריך להיות **כתובת הפרויקט בלבד** — "
                "`https://<project-ref>.supabase.co` — בלי `/rest/v1` בסוף. "
                "Supabase → Project Settings → API → Project URL."
            )
        elif any(k in low for k in ("permission denied", "42501", "row-level security")):
            # A SELECT blocked by RLS returns no rows, not an error — so 42501
            # "permission denied for table" is a missing table GRANT, which is
            # what the schema's REVOKE leaves anon with. The key names its own
            # role, so say which one arrived rather than guessing.
            role = (_key_info or {}).get("role")
            need = (
                "האפליקציה דורשת את מפתח ה-**service_role** (או מפתח "
                "`sb_secret_...`) — Supabase → Project Settings → API."
            )
            if role == "service_role":
                # The key is right, so the GRANTs really are missing.
                reason = (
                    "המפתח אכן `service_role`, ולכן חסרות ההרשאות על הטבלאות "
                    "עצמן. **הריצו שוב את `supabase_schema.sql`** — הגרסה "
                    "העדכנית מוסיפה `GRANT` מפורש ל-service_role, שחסר היה קודם."
                )
            elif role:
                reason = f"המפתח שהוגדר הוא **`{role}`**, והרשאותיו נשללו במכוון. " + need
            else:
                reason = "לא הצלחתי לזהות את סוג המפתח. " + need
        elif any(k in low for k in ("pgrst301", "jwt", "invalid api key", "401")):
            reason = (
                "המפתח `SUPABASE_KEY` נדחה. ודאו שהעתקתם את מפתח ה-**service_role** "
                "במלואו. Supabase → Project Settings → API."
            )
        elif any(k in low for k in ("pgrst205", "pgrst106", "could not find the table",
                                    "does not exist")):
            reason = (
                "ההתחברות ל-Supabase עובדת אבל הטבלאות חסרות. הריצו את "
                "`supabase_schema.sql` ב-SQL Editor."
            )
        else:
            reason = (
                "ההתחברות ל-Supabase נכשלה, והסיבה לא מזוהה. בדקו את "
                "`SUPABASE_URL` ו-`SUPABASE_KEY` ב-Secrets, ושה-"
                "`supabase_schema.sql` רץ ב-SQL Editor."
            )
        return {"ok": False, "reason": f"{reason} ({detail[:160]})"}


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

GERSHAYIM = "״"
GERESH = "׳"


def normalize_name(name: Optional[str]) -> str:
    """Fold Hebrew gershayim/geresh to ASCII, matching the name_norm column.

    Without this a trainee typing ד"ר fails to find ד״ר — and then the write
    path creates a SECOND row for the same human, splitting one person in two.
    """
    return (name or "").replace(GERSHAYIM, '"').replace(GERESH, "'").strip()


def split_title(full: str) -> tuple[Optional[str], str]:
    """('ד״ר', 'חגי בן ארצי') — a title is a credential, not part of the name."""
    m = _TITLE_RE.match(full or "")
    return (m.group(1), m.group(2).strip()) if m else (None, (full or "").strip())


def display_name(row: dict) -> str:
    title = (row or {}).get("title")
    name = (row or {}).get("name") or ""
    return f"{title} {name}".strip() if title else name


# --------------------------------------------------------------------------
# Markdown parsing — seeding only
# --------------------------------------------------------------------------

_RE_INDEX_ROW = re.compile(r"^\|\s*(חניך\s*\d+)\s*\|(.+?)\|\s*\d+\s*\|\s*$")
_RE_MISHMAR_HEAD = re.compile(r"^###\s*משמר\s*#(\d+)\s*·\s*([^·]+?)\s*·\s*(.+?)\s*$")
_RE_META = re.compile(r"^\*\*סוג:\*\*\s*(.+?)\s*·\s*\*\*אחראים:\*\*\s*(.+?)\s*$")
_RE_WORKFILE = re.compile(r"\*\*קובץ עבודה:\*\*\s*`([^`]+)`")
_RE_SECTION = re.compile(r"^\*\*\[(TO DO|IN PROGRESS|DONE)\]\*\*\s*$")
_RE_TASK = re.compile(r"^-\s*\[([ xX])\]\s*(.+?)\s*$")
_RE_SPEAKER_ROW = re.compile(r"^\|(.+)\|\s*$")


def parse_tasks_md(path: str = TASKS_MD) -> dict:
    """students_tasks.md carries dates, type, ownership AND tasks, so it seeds
    the whole schema — there is no second parser for schedule.md."""
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
                "mishmar_type": None, "note": None, "workfile_path": None,
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
            tasks.append({
                "mishmar_id": current["id"],
                "task_description": m.group(2).strip(),
                # A ticked box is DONE regardless of which block it sits in.
                "status": "DONE" if done else section,
            })

    return {"students": students, "mishmarim": mishmarim,
            "assignments": assignments, "tasks": tasks}


def parse_speakers_md(path: str = SPEAKERS_MD) -> list[dict]:
    """Parse the 8-column speaker table, splitting titles out of names."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    start = text.find("## הטבלה")
    if start < 0:
        return []
    end = text.find("**סטטוסים:**", start)
    block = text[start: end if end > 0 else len(text)]

    out: list[dict] = []
    for line in block.split("\n"):
        m = _RE_SPEAKER_ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 8:
            continue
        raw = cells[0].strip("*_ ")
        if raw in ("שם",) or set(raw) <= set("-: "):
            continue
        title, name = split_title(raw)
        out.append({
            "name": name, "title": title,
            "expertise_topics": cells[1], "lesson_fit": cells[2],
            "region": cells[3], "status": cells[4],
            "notes": " · ".join(x for x in (cells[5], cells[7]) if x and x != "—"),
            "contact": cells[6], "verification_url": None,
            "source_type": "original_44",
        })
    return out


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


def seed_from_markdown(force: bool = False) -> dict:
    """Load students_tasks.md and the speaker database into Supabase, once.

    Guarded by app_meta so it is safe on every start. Unlike the SQLite era we
    do NOT rename the Markdown afterwards: the database now lives off-container
    and survives redeploys, while the checkout is recreated from git on every
    one — renaming a file there would achieve nothing and would break the next
    deploy's seed.
    """
    result = {"seeded": False, "reason": "", "students": 0, "mishmarim": 0,
              "tasks": 0, "speakers": 0}

    existing = _one(_t("app_meta").select("*").eq("key", "seeded").execute())
    if existing and not force:
        result["reason"] = "already seeded"
        return result

    if not os.path.exists(TASKS_MD):
        result["reason"] = f"{os.path.basename(TASKS_MD)} not found"
        return result

    parsed = parse_tasks_md(TASKS_MD)
    speakers = parse_speakers_md(SPEAKERS_MD)

    students = [
        {"id": i, "name": n, "role": "student"}
        for i, n in enumerate(parsed["students"], start=1)
    ]
    # The instructor is a first-class row so tasks can be reassigned to Uri.
    students.append({"id": 100, "name": "Uri", "role": "instructor"})
    if students:
        _t("students").upsert(students).execute()

    mishmarim = [{
        "id": m["id"], "gregorian_date": m["gregorian_date"],
        "hebrew_date": m["hebrew_date"], "mishmar_type": m["mishmar_type"],
        "note": m["note"], "workfile_path": m["workfile_path"],
        "is_staff_built": m["id"] in STAFF_BUILT_MISHMARIM,
    } for m in parsed["mishmarim"]]
    if mishmarim:
        _t("mishmarim").upsert(mishmarim).execute()

    name_to_id = {s["name"]: s["id"] for s in students}
    links = [
        {"mishmar_id": mid, "student_id": name_to_id[sn]}
        for mid, sn in parsed["assignments"] if sn in name_to_id
    ]
    if links:
        _t("assignments").upsert(links).execute()

    by_id = {m["id"]: m for m in mishmarim}
    task_rows = []
    for t in parsed["tasks"]:
        category = classify_task(t["task_description"])
        greg = (by_id.get(t["mishmar_id"]) or {}).get("gregorian_date", "")
        task_rows.append({
            "mishmar_id": t["mishmar_id"], "student_id": None,
            "task_description": t["task_description"], "status": t["status"],
            "category": category, "due_date": compute_due_date(greg, category),
        })
    if task_rows:
        _t("tasks").insert(task_rows).execute()

    if speakers:
        _t("speakers").upsert(speakers, on_conflict="name,source_type").execute()

    _t("app_meta").upsert({"key": "seeded", "value": _now_iso()}).execute()
    result.update(seeded=True, reason="seeded",
                  students=len(parsed["students"]),
                  mishmarim=len(mishmarim), tasks=len(task_rows),
                  speakers=len(speakers))
    return result


def bootstrap() -> dict:
    """Called once at app start."""
    ready = storage_ready()
    if not ready["ok"]:
        return {"seeded": False, "reason": ready["reason"], "storage_ok": False}
    out = seed_from_markdown()
    out["storage_ok"] = True
    return out


# --------------------------------------------------------------------------
# Deadlines — pure Python, no storage
# --------------------------------------------------------------------------

# First match wins, so order matters. Two rules carry the weight:
#   * "אחרי" before "מרצים", or "עדכון מאגר המרצים" (an after-the-night task)
#     is filed as speaker work and dated two weeks too early.
#   * "לוגיסטיקה" before "תוכן", so "סידור חדרי חבורות (ביום המשמר)" is not
#     read as content work merely because it mentions חבורות.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("אחרי",      ("(אחרי)", "סיכום ולקחים", "תודות", "עדכון מאגר", "משוב")),
    ("יום המשמר", ("ביום המשמר", "סידור חדר", "חדרים", "קבלת פני", "הצעת שתי")),
    ("נושא",      ("סגירת נושא", "בחירת נושא", "נושא המשמר")),
    ("מרצים",     ("מרצים", "מרצה")),
    ("הזמנה",     ("הזמנה", "הזמנת", "קנבה", "הדפסה", "הפצה")),
    ("כיבוד",     ("כיבוד", "רשימת קניות", "ארוחת", "קניות")),
    ("קישוט",     ("קישוט",)),
    ("תוכן",      ("חברותות", "חבורות", "מקורות", "טקסט", "לוח זמנים", "לוז", "שיעור")),
)


def classify_task(description: str) -> Optional[str]:
    """None is a legitimate answer — better than inventing a deadline."""
    text = description or ""
    for category, needles in _CATEGORY_RULES:
        if any(n in text for n in needles):
            return category
    return None


def parse_gregorian(date_str: str) -> Optional[_date]:
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", date_str or "")
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    try:
        return _date(y, mo, d)
    except ValueError:
        return None


def compute_due_date(gregorian_date: str, category: Optional[str]) -> Optional[str]:
    if not category or category not in DEADLINE_OFFSETS_DAYS:
        return None
    base = parse_gregorian(gregorian_date)
    if base is None:
        return None
    return (base - _timedelta(days=DEADLINE_OFFSETS_DAYS[category])).isoformat()


def _he_days(n: int) -> str:
    """'1 ימים' reads as broken Hebrew to every trainee."""
    return "יום" if n == 1 else ("יומיים" if n == 2 else f"{n} ימים")


def annotate_deadline(task: dict, today: Optional[_date] = None) -> dict:
    """Attach days_left and a nudge. The deck calls these dates a
    recommendation, so the wording stays soft and a DONE task never nags."""
    today = today or _date.today()
    out = dict(task)
    out["days_left"] = None
    out["overdue"] = False
    out["nudge"] = ""

    if task.get("status") == "DONE" or not task.get("due_date"):
        return out
    try:
        due = _date.fromisoformat(str(task["due_date"])[:10])
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


def backfill_task_metadata() -> dict:
    """Fill category/due_date on tasks missing them. Never overwrites."""
    rows = _rows(_t("tasks").select("id,task_description,category,due_date,mishmar_id")
                 .is_("category", "null").execute())
    dates = {m["id"]: m["gregorian_date"] for m in get_all_mishmarim()}
    filled = 0
    for r in rows:
        category = classify_task(r["task_description"])
        if not category:
            continue
        _t("tasks").update({
            "category": category,
            "due_date": compute_due_date(dates.get(r["mishmar_id"], ""), category),
        }).eq("id", r["id"]).execute()
        filled += 1
    return {"examined": len(rows), "filled": filled,
            "unclassified": len(rows) - filled}


# --------------------------------------------------------------------------
# Mishmarim, students, tasks
# --------------------------------------------------------------------------


def get_all_mishmarim() -> list[dict]:
    mishmarim = _rows(_t("mishmarim").select("*").order("id").execute())
    spend = {b["mishmar_id"]: b["budget_used"]
             for b in _rows(_t("v_mishmar_budget").select("*").execute())}
    for m in mishmarim:
        m["budget_used"] = float(spend.get(m["id"], 0) or 0)
        m["budget_nominal"] = PER_MISHMAR_BUDGET_NIS
    return mishmarim


def get_mishmar(mishmar_id: int) -> Optional[dict]:
    m = _one(_t("mishmarim").select("*").eq("id", mishmar_id).execute())
    if not m:
        return None
    b = _one(_t("v_mishmar_budget").select("*").eq("mishmar_id", mishmar_id).execute())
    m["budget_used"] = float((b or {}).get("budget_used") or 0)
    m["budget_nominal"] = PER_MISHMAR_BUDGET_NIS
    return m


def set_mishmar_topic(mishmar_id: int, topic: str) -> bool:
    resp = _t("mishmarim").update({"topic": topic}).eq("id", mishmar_id).execute()
    return bool(_rows(resp))


def get_students() -> list[dict]:
    return _rows(_t("students").select("*").order("id").execute())


def get_student_by_email(email: str) -> Optional[dict]:
    if not (email or "").strip():
        return None
    rows = _rows(_t("students").select("*").ilike("email", email.strip()).execute())
    return rows[0] if rows else None


def set_student_email(student_id: int, email: Optional[str]) -> bool:
    value = (email or "").strip() or None
    resp = _t("students").update({"email": value}).eq("id", student_id).execute()
    return bool(_rows(resp))


def get_mishmarim_for_student(student_id: int) -> list[dict]:
    links = _rows(_t("assignments").select("mishmar_id")
                  .eq("student_id", student_id).execute())
    ids = [l["mishmar_id"] for l in links]
    if not ids:
        return []
    return [m for m in get_all_mishmarim() if m["id"] in ids]


def get_partners(mishmar_id: int, exclude_student_id: Optional[int] = None) -> list[dict]:
    links = _rows(_t("assignments").select("student_id")
                  .eq("mishmar_id", mishmar_id).execute())
    ids = [l["student_id"] for l in links if l["student_id"] != exclude_student_id]
    if not ids:
        return []
    return _rows(_t("students").select("id,name").in_("id", ids).execute())


def get_tasks_for_mishmar(mishmar_id: int) -> list[dict]:
    return _rows(_t("v_tasks_full").select("*")
                 .eq("mishmar_id", mishmar_id).order("id").execute())


def get_tasks_for_student(student_id: int) -> list[dict]:
    """Every task on this trainee's Mishmarim — shared pair tasks included."""
    mine = [m["id"] for m in get_mishmarim_for_student(student_id)]
    if not mine:
        return []
    rows = _rows(_t("v_tasks_full").select("*").in_("mishmar_id", mine)
                 .order("mishmar_id").order("id").execute())
    return [r for r in rows
            if r.get("student_id") is None or r.get("student_id") == student_id]


def update_task_status(task_id: int, new_status: str) -> bool:
    if new_status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}, got {new_status!r}")
    resp = _t("tasks").update(
        {"status": new_status, "updated_at": _now_iso()}
    ).eq("id", task_id).execute()
    return bool(_rows(resp))


def add_task(mishmar_id: int, task_description: str,
             student_id: Optional[int] = None, status: str = "TO DO",
             category: Optional[str] = None,
             lesson_id: Optional[int] = None,
             details: Optional[str] = None) -> Optional[int]:
    """`lesson_id` ties the task to one slot of the evening. It is never
    guessed here — seeding inserts hundreds of rows and a lookup per row would
    be hundreds of queries. A caller that KNOWS the slot passes it; everyone
    else leaves it NULL and the door falls back to suggest_lesson_for_task."""
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}, got {status!r}")
    category = category or classify_task(task_description)
    m = get_mishmar(mishmar_id)
    resp = _t("tasks").insert({
        "mishmar_id": mishmar_id, "student_id": student_id,
        "task_description": task_description, "status": status,
        "category": category, "lesson_id": lesson_id,
        "details": details,
        "due_date": compute_due_date(m["gregorian_date"], category) if m else None,
    }).execute()
    row = _one(resp)
    return row.get("id") if row else None


def get_student(student_id: int) -> Optional[dict]:
    return _one(_t("students").select("*").eq("id", student_id).execute())


def edit_task(task_id: int, description: Optional[str] = None,
              details: Optional[str] = None,
              due_date: Optional[str] = None) -> bool:
    """Edit a task's text fields. Only non-None values are written; an empty
    string clears the field. due_date is ISO or None."""
    fields: dict[str, Any] = {"updated_at": _now_iso()}
    if description is not None and description.strip():
        fields["task_description"] = description.strip()
    if details is not None:
        fields["details"] = details.strip() or None
    if due_date is not None:
        fields["due_date"] = due_date or None
    resp = _t("tasks").update(fields).eq("id", task_id).execute()
    return bool(_rows(resp))


def delete_task(task_id: int) -> bool:
    return bool(_rows(_t("tasks").delete().eq("id", task_id).execute()))


def get_task(task_id: int) -> Optional[dict]:
    return _one(_t("tasks").select("*").eq("id", task_id).execute())


def find_mishmarim_by_topic(topic: str) -> list[dict]:
    """Mishmarim this season whose topic resembles the given one."""
    t = (topic or "").strip()
    if not t:
        return []
    return _rows(_t("mishmarim").select("id,gregorian_date,hebrew_date,topic")
                 .ilike("topic", f"%{t}%").order("id").execute())


def get_budget_speaker_names(mishmar_id: int) -> list[str]:
    """Speakers recorded on budget lines — people who came but may never have
    been added to the running order, and who must still be reviewable."""
    rows = _rows(_t("budget").select("description")
                 .eq("mishmar_id", mishmar_id).eq("expense_type", "מרצה").execute())
    seen, out = set(), []
    for r in rows:
        name = (r.get("description") or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


# --------------------------------------------------------------------------
# The phase model — the app's answer to "what is my next step?"
#
# A Mishmar is built in a fixed order the deadline offsets already encode:
# close a topic (−21d), then speakers and content (−14d), then logistics
# (−7d), then the after-work. The UI shows a trainee ONLY the current
# phase's tasks — everything at once is how 40 cards attack a person from
# every direction on day one.
# --------------------------------------------------------------------------

PHASES = (
    {"key": "topic",     "label": "נושא",        "icon": "🎯",
     "categories": ("נושא",)},
    {"key": "content",   "label": "מרצים ותוכן", "icon": "🎤",
     "categories": ("מרצים", "תוכן")},
    {"key": "logistics", "label": "לוגיסטיקה",   "icon": "📦",
     "categories": ("הזמנה", "כיבוד", "קישוט", "לוגיסטיקה", "יום המשמר")},
    {"key": "after",     "label": "אחרי הערב",   "icon": "🌙",
     "categories": ("אחרי",)},
)

_PHASE_OF_CATEGORY = {c: p["key"] for p in PHASES for c in p["categories"]}


def mishmar_progress(mishmar_id: Optional[int] = None,
                     mishmar: Optional[dict] = None,
                     tasks: Optional[list[dict]] = None) -> dict:
    """Phase state for one Mishmar.

    Accepts preloaded rows so a 21-Mishmar pipeline costs two queries, not 42.
    A task with no category counts as content (the middle of the build), so an
    unclassified task can never silently vanish from every phase.

    Phase 1 is complete when the topic is SET — that is the real-world signal,
    and the נושא tasks are auto-closed by both write paths when it happens. An
    empty phase counts as complete: there is nothing to do in it.
    """
    m = mishmar or get_mishmar(mishmar_id)
    if tasks is None:
        tasks = get_tasks_for_mishmar(m["id"])

    phases = []
    for spec in PHASES:
        ts = [t for t in tasks
              if _PHASE_OF_CATEGORY.get(t.get("category") or "תוכן") == spec["key"]]
        done = sum(1 for t in ts if t.get("status") == "DONE")
        complete = done == len(ts)
        if spec["key"] == "topic":
            complete = bool(m.get("topic")) or (bool(ts) and complete)
        phases.append({**spec, "tasks": ts, "done": done,
                       "total": len(ts), "complete": complete})

    current = next((i for i, p in enumerate(phases) if not p["complete"]),
                   len(phases) - 1)
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("status") == "DONE")
    open_current = [t for t in phases[current]["tasks"] if t.get("status") != "DONE"]
    open_current.sort(key=lambda t: t.get("due_date") or "9999")
    return {
        "mishmar": m,
        "phases": phases,
        "current": current,
        "done": done,
        "total": total,
        "pct": (done / total) if total else 0.0,
        "next_task": open_current[0] if open_current else None,
    }


def get_all_tasks() -> list[dict]:
    """Every task with its Mishmar context, one query — for pipeline views."""
    return _rows(_t("v_tasks_full").select("*")
                 .order("mishmar_id").order("id").execute())


def get_task_totals() -> dict:
    """Season-wide task counts, for the instructor's progress bar. Counts task
    ROWS, so a pair-shared task (student_id NULL) is counted once — unlike
    v_student_progress, which credits it to both partners on purpose."""
    rows = _rows(_t("tasks").select("status").execute())
    done = sum(1 for r in rows if r.get("status") == "DONE")
    return {"total": len(rows), "done": done}


def get_overdue_tasks() -> list[dict]:
    """Open tasks past their recommended date. CURRENT_DATE is evaluated in
    Postgres, so this does not drift with the app server's clock."""
    return _rows(_t("v_overdue_tasks").select("*").order("due_date").execute())


def get_student_progress() -> list[dict]:
    return _rows(_t("v_student_progress").select("*").order("id").execute())


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


def add_budget_entry(mishmar_id: int, expense_type: str, amount: float = 0,
                     actual_cost: float = 0,
                     description: Optional[str] = None) -> Optional[int]:
    """actual_cost=0 is meaningful: the speaker came free."""
    row = _one(_t("budget").insert({
        "mishmar_id": mishmar_id, "expense_type": expense_type,
        "description": description, "amount": amount, "actual_cost": actual_cost,
    }).execute())
    return row.get("id") if row else None


def get_budget_summary(today: Optional[_date] = None) -> dict:
    """Season-wide spend. There is no ceiling to compare against, by decision:
    `over_nominal` is information, not an alarm.

    The number the instructor actually asked for is `avg_per_past`: what a
    Mishmar that ALREADY HAPPENED cost on average. Dividing by all 21 would
    read as a collapsing average all season; dividing by the evenings behind
    us is the only honest denominator. `gregorian_date` is d.m.Y TEXT, so the
    comparison goes through `parse_gregorian` and never through string order.
    """
    today = today or _date.today()
    per = []
    for m in get_all_mishmarim():
        when = parse_gregorian(m["gregorian_date"])
        per.append({"id": m["id"], "gregorian_date": m["gregorian_date"],
                    "topic": m.get("topic"), "spent": m.get("budget_used") or 0,
                    "past": bool(when and when < today)})
    past = [r for r in per if r["past"]]
    past_spent = sum(r["spent"] for r in past)
    return {
        "per_mishmar": per,
        "total_spent": sum(r["spent"] for r in per),
        "nominal_per_mishmar": PER_MISHMAR_BUDGET_NIS,
        "season_ceiling": SEASON_BUDGET_CEILING_NIS,
        "over_nominal": [r["id"] for r in per if r["spent"] > PER_MISHMAR_BUDGET_NIS],
        "past_count": len(past),
        "past_spent": past_spent,
        # None, not 0 — «no Mishmar has happened yet» is not «costs nothing».
        "avg_per_past": (past_spent / len(past)) if past else None,
    }


# --------------------------------------------------------------------------
# Speakers
# --------------------------------------------------------------------------


class AmbiguousSpeaker(ValueError):
    """Several index rows carry this name.

    Not hypothetical: flag ה7 recorded up to four people called אורי, with the
    standing instruction "אל תאחד אותם על דעתך". Guessing would be that merge.
    """

    def __init__(self, name: str, candidates: list[dict]):
        super().__init__(f"{len(candidates)} speakers named {name!r} — pick one by id")
        self.name = name
        self.candidates = candidates


def add_new_speaker(name: str, expertise_topics: Optional[str] = None,
                    verification_url: Optional[str] = None,
                    source_type: str = "web_search",
                    status: str = "⬜ לא פנינו",
                    lesson_fit: Optional[str] = None,
                    region: Optional[str] = None, contact: Optional[str] = None,
                    notes: Optional[str] = None,
                    title: Optional[str] = None) -> Optional[int]:
    """Grow the index. Contact details are never fabricated — leave them None."""
    if source_type not in SPEAKER_SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {SPEAKER_SOURCE_TYPES}")
    if title is None:
        title, name = split_title(name)
    row = _one(_t("speakers").upsert({
        "name": name, "title": title, "expertise_topics": expertise_topics,
        "verification_url": verification_url, "source_type": source_type,
        "status": status, "lesson_fit": lesson_fit, "region": region,
        "contact": contact, "notes": notes,
    }, on_conflict="name,source_type").execute())
    return row.get("id") if row else None


def get_speaker_by_name(name: str) -> list[dict]:
    """A LIST, deliberately — see AmbiguousSpeaker. Never silently merges."""
    norm = normalize_name(name)
    if not norm:
        return []
    return _rows(_t("speakers").select("*").ilike("name_norm", f"%{norm}%")
                 .order("source_type").execute())


def get_speaker_status(name: str) -> list[dict]:
    norm = normalize_name(name)
    if not norm:
        return []
    return _rows(_t("v_speaker_status").select("*")
                 .ilike("name_norm", f"%{norm}%").execute())


def get_speakers_with_status(only_contacted: bool = False) -> list[dict]:
    q = _t("v_speaker_status").select("*")
    if only_contacted:
        q = q.eq("has_outreach", True)
    return sorted(_rows(q.execute()),
                  key=lambda r: (not r.get("has_outreach"), r.get("name") or ""))


def search_speakers_by_topic(topic: str, lesson: Optional[str] = None) -> list[dict]:
    """A STARTING POINT, not the candidate set — speaker_search must still run
    a live web search alongside this.

    `notes` is searched too, and that is load-bearing: the parser files
    "מה העביר אצלנו" there, and גדי תורג'מן is filed under "הלכה, מחשבת הרמב"ם"
    while his notes read "מועמד טבעי לכל משמר תשובה". Topics alone hid exactly
    the person a תשובה search most wanted.
    """
    t = (topic or "").strip()
    if not t:
        return []
    rows = _rows(
        _t("speakers").select("*")
        .or_(f"expertise_topics.ilike.%{t}%,name.ilike.%{t}%,notes.ilike.%{t}%")
        .execute()
    )
    if lesson:
        # An unrecorded lesson_fit means "never written down", not "unsuitable" —
        # dropping those silently would bury real candidates.
        rows = [r for r in rows
                if not r.get("lesson_fit")
                or r["lesson_fit"] == "TBD"
                or lesson in r["lesson_fit"]]
    return sorted(rows, key=lambda r: (r.get("source_type") or "", r.get("name") or ""))


def get_speaker_stats() -> dict:
    out: dict[str, int] = {}
    for r in _rows(_t("speakers").select("source_type").execute()):
        out[r["source_type"]] = out.get(r["source_type"], 0) + 1
    return out


def resolve_speaker(name: Optional[str] = None, speaker_id: Optional[int] = None,
                    create_if_missing: bool = False) -> Optional[dict]:
    """Exactly one speaker row, or AmbiguousSpeaker."""
    if speaker_id is not None:
        return _one(_t("speakers").select("*").eq("id", speaker_id).execute())

    norm = normalize_name(name)
    if not norm:
        return None
    exact = _rows(_t("speakers").select("*").eq("name_norm", norm).execute())
    if len(exact) > 1:
        raise AmbiguousSpeaker(norm, exact)
    if exact:
        return exact[0]
    if not create_if_missing:
        return None
    new_id = add_new_speaker(name=name, source_type="manual")
    return _one(_t("speakers").select("*").eq("id", new_id).execute()) if new_id else None


def record_outreach(status: str, name: Optional[str] = None,
                    speaker_id: Optional[int] = None,
                    mishmar_id: Optional[int] = None,
                    student_id: Optional[int] = None,
                    note: Optional[str] = None) -> dict:
    """THE single writer for outreach.

    Current status is derived from this log by v_speaker_status. Before it
    existed, closing a speaker wrote only lessons.speaker_status, so the shared
    index never learned and the next pair got a stale answer — defeating the one
    mechanism that stops two pairs approaching the same person.
    """
    if status not in SPEAKER_STATUSES:
        raise ValueError(f"status must be one of {SPEAKER_STATUSES}, got {status!r}")

    speaker = resolve_speaker(name=name, speaker_id=speaker_id, create_if_missing=True)
    if not speaker:
        raise ValueError("no speaker name or id supplied")

    _t("speaker_outreach").insert({
        "speaker_id": speaker["id"], "mishmar_id": mishmar_id,
        "student_id": student_id, "status": status, "note": note,
    }).execute()

    # Keep the work-file's display in step. A mirror of the log, never a source.
    if mishmar_id is not None:
        _t("lessons").update({"speaker_status": status}) \
            .eq("mishmar_id", mishmar_id).eq("speaker_name", speaker["name"]).execute()

    return {"speaker_id": speaker["id"], "name": speaker["name"], "status": status}


def get_all_outreach() -> list[dict]:
    """The whole outreach log, newest first, one query. The index page used to
    call get_outreach_for_speaker per row — 46 HTTPS round-trips per rerun,
    which is the whole reason the page felt slow. Group this in Python."""
    return _rows(_t("v_outreach_full").select("*").order("id", desc=True).execute())


def get_outreach_for_speaker(speaker_id: int) -> list[dict]:
    return _rows(_t("v_outreach_full").select("*").eq("speaker_id", speaker_id)
                 .order("id", desc=True).execute())


def get_outreach_for_mishmar(mishmar_id: int) -> list[dict]:
    return _rows(_t("v_outreach_full").select("*").eq("mishmar_id", mishmar_id)
                 .order("id", desc=True).execute())


# --------------------------------------------------------------------------
# Lessons, feedback, chat
# --------------------------------------------------------------------------


LESSON_DEFAULT_MINUTES = 75
BREAK_DEFAULT_MINUTES = 30
EVENING_START = "20:00"


def create_default_timeline(mishmar_id: int) -> int:
    """The real evening skeleton: 20:00 · three 75-minute lessons with 30-minute
    breaks · a 15-minute break · one hour of חבורות. Titles, roles and formats
    stay EMPTY by design — the skeleton is time, the pair pours the content.
    Returns the number of rows created; refuses (0) if any lessons exist."""
    if get_lessons(mishmar_id):
        return 0
    slots = [
        {"is_break": False, "duration_minutes": 75},
        {"is_break": True,  "duration_minutes": 30},
        {"is_break": False, "duration_minutes": 75},
        {"is_break": True,  "duration_minutes": 30},
        {"is_break": False, "duration_minutes": 75},
        {"is_break": True,  "duration_minutes": 15},
        {"is_break": False, "duration_minutes": 60, "lesson_role": "חבורות"},
    ]
    for i, slot in enumerate(slots, 1):
        _t("lessons").insert({"mishmar_id": mishmar_id, "slot_order": i, **slot}).execute()
    recompute_lesson_times(mishmar_id)
    return len(slots)


def recompute_lesson_times(mishmar_id: int, first_start: str = EVENING_START) -> None:
    """Start times are DERIVED: 20:00 plus the cumulative durations before each
    slot. Editing a duration reflows the whole evening — nobody hand-types
    times that then silently overlap."""
    rows = get_lessons(mishmar_id)
    try:
        h, m = (int(x) for x in (first_start or EVENING_START).split(":"))
    except ValueError:
        h, m = 20, 0
    minutes = h * 60 + m
    for r in rows:
        stamp = f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"
        if r.get("start_time") != stamp:
            _t("lessons").update({"start_time": stamp}).eq("id", r["id"]).execute()
        dur = r.get("duration_minutes") or (
            BREAK_DEFAULT_MINUTES if r.get("is_break") else LESSON_DEFAULT_MINUTES)
        minutes += int(dur)


def get_lesson_speakers(mishmar_id: int) -> dict[int, list[dict]]:
    """All candidate speakers for a Mishmar's lessons, grouped by lesson_id —
    ONE query, per the one-query-per-list rule."""
    lesson_ids = [l["id"] for l in get_lessons(mishmar_id)]
    if not lesson_ids:
        return {}
    rows = _rows(_t("lesson_speakers").select("*")
                 .in_("lesson_id", lesson_ids).order("id").execute())
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["lesson_id"], []).append(r)
    return out


def add_lesson_speaker(lesson_id: int, name: str, phone: Optional[str] = None,
                       student_id: Optional[int] = None) -> Optional[int]:
    """A candidate joins a lesson's list — and the shared index learns the
    person exists (source manual, the phone as contact). The index write is an
    upsert on the normalised name, so a known person is not duplicated."""
    name = (name or "").strip()
    if not name:
        return None
    row = _one(_t("lesson_speakers").insert({
        "lesson_id": lesson_id, "name": name, "phone": (phone or "").strip() or None,
    }).execute())
    try:
        existing = get_speaker_by_name(name)
        if not existing:
            add_new_speaker(name=name, source_type="manual",
                            contact=(phone or "").strip() or None,
                            notes="נוסף כמועמד ממבנה הערב")
        elif phone and not (existing[0].get("contact") or "").strip("TBD "):
            _t("speakers").update({"contact": phone.strip()}).eq(
                "id", existing[0]["id"]).execute()
    except AmbiguousSpeaker:
        pass   # several known people share the name — never merge on our own
    return row.get("id") if row else None


def update_lesson_speaker_status(candidate_id: int, status: str,
                                 mishmar_id: Optional[int] = None,
                                 student_id: Optional[int] = None) -> None:
    """Candidate status routes through the journal's single writer too."""
    if status not in SPEAKER_STATUSES:
        raise ValueError(f"status must be one of {SPEAKER_STATUSES}")
    row = _one(_t("lesson_speakers").update({"status": status})
               .eq("id", candidate_id).execute())
    if row:
        try:
            record_outreach(status, name=row["name"], mishmar_id=mishmar_id,
                            student_id=student_id)
        except AmbiguousSpeaker:
            pass


def close_lesson_speaker(lesson_id: int, name: str,
                         mishmar_id: Optional[int] = None,
                         student_id: Optional[int] = None) -> dict:
    """«סגרתי את X»: X becomes the lesson's speaker, the journal logs ✅, and
    the other candidates vanish — X stays as the single closed row."""
    name = (name or "").strip()
    cands = _rows(_t("lesson_speakers").select("*").eq("lesson_id", lesson_id).execute())
    match = next((c for c in cands
                  if normalize_name(c["name"]) == normalize_name(name)
                  or normalize_name(name) in normalize_name(c["name"])), None)
    closed_name = (match or {}).get("name") or name
    _t("lessons").update({"speaker_name": closed_name}).eq("id", lesson_id).execute()
    removed = []
    for c in cands:
        if match and c["id"] == match["id"]:
            _t("lesson_speakers").update({"status": "✅ סגור"}).eq("id", c["id"]).execute()
        else:
            _t("lesson_speakers").delete().eq("id", c["id"]).execute()
            removed.append(c["name"])
    try:
        record_outreach("✅ סגור", name=closed_name, mishmar_id=mishmar_id,
                        student_id=student_id)
    except AmbiguousSpeaker:
        pass
    return {"closed": closed_name, "removed": removed}


def upload_source_sheet(mishmar_id: int, lesson_id: int,
                        filename: str, data: bytes) -> Optional[str]:
    """Upload a source sheet to Supabase Storage and return its public URL.

    Creates the `sources` bucket on first use (service_role may). Returns None
    on ANY failure — the UI then falls back to a paste-a-link field, so a
    storage hiccup never blocks the pair."""
    try:
        storage = get_client().storage
        try:
            storage.create_bucket("sources", options={"public": True})
        except Exception:
            pass   # already exists, or creation denied — the upload will tell
        safe = re.sub(r"[^\w.\-]+", "_", filename or "source")
        path = f"mishmar-{int(mishmar_id):02d}/lesson-{int(lesson_id)}-{safe}"
        storage.from_("sources").upload(
            path, data,
            {"content-type": "application/octet-stream", "upsert": "true"})
        url = storage.from_("sources").get_public_url(path)
        return str(url) if url else None
    except Exception:
        return None


def set_lesson_source(lesson_id: int, url: Optional[str]) -> None:
    _t("lessons").update({"source_url": (url or "").strip() or None}).eq(
        "id", lesson_id).execute()


def get_lessons(mishmar_id: int) -> list[dict]:
    return _rows(_t("lessons").select("*").eq("mishmar_id", mishmar_id)
                 .order("slot_order").execute())


def upsert_lesson(mishmar_id: int, slot_order: int, title: Optional[str] = None,
                  start_time: Optional[str] = None, description: Optional[str] = None,
                  lesson_role: Optional[str] = None, speaker_name: Optional[str] = None,
                  speaker_status: Optional[str] = None, fmt: Optional[str] = None,
                  student_id: Optional[int] = None) -> Optional[int]:
    """Insert or update one slot. Only non-None fields are written."""
    existing = _one(_t("lessons").select("*").eq("mishmar_id", mishmar_id)
                    .eq("slot_order", slot_order).execute())

    fields = {"start_time": start_time, "title": title, "description": description,
              "lesson_role": lesson_role, "speaker_name": speaker_name,
              "format": fmt}
    given = {k: v for k, v in fields.items() if v is not None}

    # speaker_status is NOT written here. It mirrors the outreach log, and
    # setting it directly would recreate the second writer this design removes.
    status_request = speaker_status

    if existing:
        lesson_id = existing["id"]
        if given:
            _t("lessons").update(given).eq("id", lesson_id).execute()
    else:
        row = _one(_t("lessons").insert(
            {"mishmar_id": mishmar_id, "slot_order": slot_order, **given}).execute())
        lesson_id = row.get("id") if row else None

    if status_request:
        who = speaker_name or (existing or {}).get("speaker_name")
        if who:
            try:
                record_outreach(status_request, name=who, mishmar_id=mishmar_id,
                                student_id=student_id)
            except AmbiguousSpeaker:
                # Several people share this name (ה7). Record nothing rather
                # than pick one; the UI asks which person is meant.
                pass
    return lesson_id


def delete_lesson(lesson_id: int) -> bool:
    return bool(_rows(_t("lessons").delete().eq("id", lesson_id).execute()))


# --------------------------------------------------------------------------
# Tasks ↔ evening slots
#
# «לסגור מי מעביר חבורות סבב א׳» is a task about ONE row of the running order,
# not about the Mishmar in general. Two ways a task knows its slot:
#
#   1. `tasks.lesson_id` — an EXPLICIT link, written when a human (or the chat)
#      creates the task from a slot, or picks a slot in the task editor.
#   2. `suggest_lesson_for_task` — a pure guess from the task's own wording,
#      used only as a fallback for the «פתח» door. Nothing is persisted from a
#      guess: a wrong door costs a click, a wrong stored link is wrong data.
#
# NULL is the common, correct answer — כיבוד, קישוט and הזמנה belong to no slot.
# --------------------------------------------------------------------------

# Hebrew ordinals as they actually appear in the seeded task list, plus the
# digit forms. The geresh/gershayim are stripped before matching, so 'סבב א׳',
# "סבב א'" and 'סבב א' are one key.
_ORDINALS = {
    "ראשון": 1, "ראשונה": 1, "א": 1,
    "שני": 2, "שנייה": 2, "שניה": 2, "ב": 2,
    "שלישי": 3, "שלישית": 3, "ג": 3,
    "רביעי": 4, "רביעית": 4, "ד": 4,
}

_GERESH = str.maketrans("", "", "׳״'\"")


def _norm_task_text(text: Optional[str]) -> str:
    return (text or "").translate(_GERESH)


def _is_chavurot(lesson: dict) -> bool:
    return ("חבורות" in (lesson.get("lesson_role") or "")
            or "חבורות" in (lesson.get("format") or "")
            or "חבורות" in (lesson.get("title") or "")
            or "חברותות" in (lesson.get("title") or ""))


def suggest_lesson_for_task(task: dict, lessons: list[dict]) -> Optional[int]:
    """The slot a task is probably about — or None, which is a real answer.

    Pure: no queries, no writes. Callers already hold both lists, so the door
    on every task card costs nothing. Ambiguity resolves to None on purpose —
    the repo's standing rule is that we never invent a link we cannot justify.
    """
    text = _norm_task_text(task.get("task_description")) + " " + \
        _norm_task_text(task.get("details"))
    if not text.strip():
        return None
    slots = [l for l in lessons if not l.get("is_break")]
    if not slots:
        return None

    # 1. a closed speaker named in the task text — the strongest signal there is.
    for l in slots:
        name = (l.get("speaker_name") or "").strip()
        if len(name) >= 3 and name in text:
            return l["id"]

    # 2. חבורות: pick the round if the text names one, else the only such slot.
    if "חבורות" in text or "חברותות" in text:
        rounds = [l for l in slots if _is_chavurot(l)]
        if rounds:
            n = _round_number(text)
            if n and n <= len(rounds):
                return rounds[n - 1]["id"]
            if len(rounds) == 1:
                return rounds[0]["id"]
            return None            # several rounds, no round named — don't guess
        return None

    # 3. an explicit ordinal or number on a lesson/slot word.
    n = _slot_number(text)
    if n and n <= len(slots):
        return slots[n - 1]["id"]

    # 4. the slot's own title, when the pair gave it one worth matching.
    for l in slots:
        title = _norm_task_text(l.get("title")).strip()
        if len(title) >= 4 and title in text:
            return l["id"]
    return None


def _round_number(text: str) -> Optional[int]:
    m = re.search(r"סבב\s+(\S+)", text)
    if not m:
        return None
    token = m.group(1).strip(" .,:־-")
    if token.isdigit():
        return int(token)
    return _ORDINALS.get(token)


def _slot_number(text: str) -> Optional[int]:
    m = re.search(r"(?:שיעור|מקטע|מפגש)\s+(\S+)", text)
    if not m:
        return None
    token = m.group(1).strip(" .,:־-")
    if token.isdigit():
        return int(token)
    return _ORDINALS.get(token)


def link_task_to_lesson(task_id: int, lesson_id: Optional[int]) -> bool:
    """Tie a task to one slot of the evening — or untie it with None."""
    resp = _t("tasks").update(
        {"lesson_id": lesson_id, "updated_at": _now_iso()}
    ).eq("id", task_id).execute()
    return bool(_rows(resp))


def get_tasks_for_lesson(mishmar_id: Optional[int] = None,
                         tasks: Optional[list[dict]] = None) -> dict[int, list[dict]]:
    """Every EXPLICITLY linked task of a Mishmar, grouped by lesson_id.

    Takes preloaded rows so the workfile — which already holds every task —
    groups them for free instead of paying a second query per render."""
    if tasks is None:
        tasks = get_tasks_for_mishmar(mishmar_id)
    out: dict[int, list[dict]] = {}
    for t in tasks:
        if t.get("lesson_id"):
            out.setdefault(t["lesson_id"], []).append(t)
    return out


def add_feedback(mishmar_id: int, rating: Optional[int] = None,
                 speaker_name: Optional[str] = None, lesson_id: Optional[int] = None,
                 lesson_title: Optional[str] = None,
                 student_id: Optional[int] = None, what_worked: Optional[str] = None,
                 what_didnt: Optional[str] = None) -> Optional[int]:
    """lesson_title carries per-slot feedback BY NAME, so it survives slot
    deletion and reads well years later."""
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("rating must be between 1 and 5")
    row = _one(_t("feedback").insert({
        "mishmar_id": mishmar_id, "student_id": student_id, "lesson_id": lesson_id,
        "lesson_title": lesson_title,
        "speaker_name": speaker_name, "rating": rating,
        "what_worked": what_worked, "what_didnt": what_didnt,
    }).execute())
    return row.get("id") if row else None


def get_feedback_for_mishmar(mishmar_id: int) -> list[dict]:
    return _rows(_t("feedback").select("*").eq("mishmar_id", mishmar_id)
                 .order("id").execute())


def get_feedback_for_speaker(name: str) -> list[dict]:
    """What a trainee two years from now gets that today's trainee does not:
    not just that someone taught here, but whether it worked."""
    return _rows(_t("feedback").select("*").eq("speaker_name", name)
                 .order("id", desc=True).execute())


def add_chat_message(role: str, content: str, mishmar_id: Optional[int] = None,
                     student_id: Optional[int] = None) -> Optional[int]:
    if role not in ("user", "assistant"):
        raise ValueError("role must be 'user' or 'assistant'")
    row = _one(_t("chat_messages").insert({
        "mishmar_id": mishmar_id, "student_id": student_id,
        "role": role, "content": content,
    }).execute())
    return row.get("id") if row else None


def get_chat_history(mishmar_id: Optional[int] = None,
                     student_id: Optional[int] = None, limit: int = 100) -> list[dict]:
    q = _t("chat_messages").select("*")
    if mishmar_id is not None:
        q = q.eq("mishmar_id", mishmar_id)
    if student_id is not None:
        q = q.eq("student_id", student_id)
    return list(reversed(_rows(q.order("id", desc=True).limit(limit).execute())))


def clear_chat_history(mishmar_id: int, student_id: int) -> int:
    return len(_rows(_t("chat_messages").delete()
                     .eq("mishmar_id", mishmar_id)
                     .eq("student_id", student_id).execute()))


# --------------------------------------------------------------------------
# Search cache
# --------------------------------------------------------------------------


def _cache_key(query: str, backend: str = "", region: str = "") -> str:
    return hashlib.sha256(f"{query}|{backend}|{region}".encode("utf-8")).hexdigest()


def cache_get(query: str, backend: str = "", region: str = "") -> Optional[list[dict]]:
    row = _one(_t("search_cache").select("*")
               .eq("query_hash", _cache_key(query, backend, region)).execute())
    if not row:
        return None
    try:
        created = _datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError):
        return None
    age = _datetime.now(created.tzinfo) - created
    # Two lifetimes, chosen by whether the call worked. Without the short one a
    # single blocked afternoon poisons the cache for the rest of the season.
    limit = (_timedelta(days=CACHE_TTL_DAYS_OK) if row.get("ok")
             else _timedelta(hours=CACHE_TTL_HOURS_FAIL))
    if age > limit:
        return None
    payload = row.get("results_json")
    return json.loads(payload) if isinstance(payload, str) else payload


def cache_put(query: str, results: list[dict], ok: bool = True,
              backend: str = "", region: str = "") -> None:
    _t("search_cache").upsert({
        "query_hash": _cache_key(query, backend, region),
        "query_text": query, "results_json": results,
        "ok": bool(ok), "created_at": _now_iso(),
    }).execute()


def cache_stats() -> dict:
    rows = _rows(_t("search_cache").select("ok,created_at").execute())
    return {
        "total": len(rows),
        "ok": sum(1 for r in rows if r.get("ok")),
        "newest": max((str(r.get("created_at") or "") for r in rows), default=None),
    }


# --------------------------------------------------------------------------

if __name__ == "__main__":
    ready = storage_ready()
    print("storage:", ready)
    if ready["ok"]:
        print(bootstrap())
        print("scope:", PROGRAMME, ACADEMIC_YEAR_HE, "—", INSTITUTION)
