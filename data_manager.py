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
SPEAKER_STATUSES = (
    "⬜ לא פנינו", "📩 נשלחה פנייה", "⏳ ממתין לתשובה",
    "✅ סגור", "❌ לא יכול/ה", "⚠️ בתנאי",
)

TASK_CATEGORIES = (
    "נושא", "מרצים", "הזמנה", "כיבוד", "קישוט", "תוכן", "לוגיסטיקה", "אחרי",
)

# Days BEFORE the Mishmar each category is recommended to close. Negative = after.
# The opening deck calls these "המלצה — לא חוק", and that framing is load-bearing:
# a trainee sees a nudge; only the instructor view treats a passed date as action.
DEADLINE_OFFSETS_DAYS = {
    "נושא": 21, "מרצים": 14, "הזמנה": 7, "כיבוד": 7,
    "קישוט": 7, "תוכן": 7, "לוגיסטיקה": 0, "אחרי": -7,
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
    _client = create_client(url, key)
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
        # RLS is on with no policies, so an anon key is refused rather than
        # returning nothing. Distinguish that from a schema that was never
        # installed — the two look alike from here but need opposite fixes.
        denied = any(k in detail.lower() for k in
                     ("permission denied", "42501", "row-level security"))
        if denied:
            reason = (
                "ההתחברות עובדת, אבל המפתח נדחה. RLS מופעל על כל הטבלאות, ולכן "
                "**חייבים את מפתח ה-service_role** — מפתח anon לא ייתן גישה. "
                "Supabase → Project Settings → API → service_role."
            )
        else:
            reason = (
                "ההתחברות ל-Supabase עובדת אבל הטבלאות חסרות. הריצו את "
                "`supabase_schema.sql` ב-SQL Editor."
            )
        return {"ok": False, "reason": f"{reason} ({detail[:120]})"}


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
    ("לוגיסטיקה", ("ביום המשמר", "סידור חדר", "חדרים", "קבלת פני")),
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
             category: Optional[str] = None) -> Optional[int]:
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}, got {status!r}")
    category = category or classify_task(task_description)
    m = get_mishmar(mishmar_id)
    resp = _t("tasks").insert({
        "mishmar_id": mishmar_id, "student_id": student_id,
        "task_description": task_description, "status": status,
        "category": category,
        "due_date": compute_due_date(m["gregorian_date"], category) if m else None,
    }).execute()
    row = _one(resp)
    return row.get("id") if row else None


def get_student(student_id: int) -> Optional[dict]:
    return _one(_t("students").select("*").eq("id", student_id).execute())


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


def get_budget_summary() -> dict:
    """Season-wide spend. There is no ceiling to compare against, by decision:
    `over_nominal` is information, not an alarm."""
    per = []
    for m in get_all_mishmarim():
        per.append({"id": m["id"], "gregorian_date": m["gregorian_date"],
                    "topic": m.get("topic"), "spent": m.get("budget_used") or 0})
    return {
        "per_mishmar": per,
        "total_spent": sum(r["spent"] for r in per),
        "nominal_per_mishmar": PER_MISHMAR_BUDGET_NIS,
        "season_ceiling": SEASON_BUDGET_CEILING_NIS,
        "over_nominal": [r["id"] for r in per if r["spent"] > PER_MISHMAR_BUDGET_NIS],
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


def get_outreach_for_speaker(speaker_id: int) -> list[dict]:
    return _rows(_t("v_outreach_full").select("*").eq("speaker_id", speaker_id)
                 .order("id", desc=True).execute())


def get_outreach_for_mishmar(mishmar_id: int) -> list[dict]:
    return _rows(_t("v_outreach_full").select("*").eq("mishmar_id", mishmar_id)
                 .order("id", desc=True).execute())


# --------------------------------------------------------------------------
# Lessons, feedback, chat
# --------------------------------------------------------------------------


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


def add_feedback(mishmar_id: int, rating: Optional[int] = None,
                 speaker_name: Optional[str] = None, lesson_id: Optional[int] = None,
                 student_id: Optional[int] = None, what_worked: Optional[str] = None,
                 what_didnt: Optional[str] = None) -> Optional[int]:
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("rating must be between 1 and 5")
    row = _one(_t("feedback").insert({
        "mishmar_id": mishmar_id, "student_id": student_id, "lesson_id": lesson_id,
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
