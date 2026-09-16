"""
speaker_search.py — finding real, living, reachable speakers for a Mishmar.

This is the hardest and most failure-prone step in building a Mishmar
(system_rules.md §4), so it is a first-class feature, not a lookup.

TWO PATHS, BOTH PRIMARY — this is the core design decision:

  1. DISCOVERY (`search_candidates`) — fires broad queries at academic and
     institutional sites and *mines names out of the results*. This is what
     surfaces a lecturer nobody has heard of: a new postdoc, a researcher who
     is excellent but not famous, someone no language model has in its weights.
     Without this the tool could only ever re-propose already-famous people.

  2. VERIFICATION (`verify_speaker`) — takes a name from anywhere (this
     module, the local index, a student, or a model's suggestion) and answers
     the ⚠️ לאמת checklist already specified in the generator prompt: alive?
     still in this field? where do they live? do they actually lecture?
     Search results settle those far better than model memory does.

Neither path is a fallback for the other. A name that only a model could
propose still needs verifying; a name only a search could surface still needs
a human to judge it.

NOTHING HERE OPENS THE DATABASE DIRECTLY — the cache and the index both go
through data_manager, which remains the single data seam.

⚠️ Contact details are never scraped and never guessed. We store the
institutional page URL, which is where a human can go and find them.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from typing import Any, Optional

import data_manager as dm

# --------------------------------------------------------------------------
# Rate-limit policy
#
# Real volume for a whole season is small: 19 Mishmarim x ~3 speakers x ~3
# queries is roughly 300-600 searches spread over five months. The problem is
# never the total — it is the BURST. A pair sitting down for one evening fires
# 25 queries in three minutes, and that is exactly what trips DuckDuckGo's
# limiter. Everything below is aimed at bursts, not at volume.
#
# All trainees share one machine, so one Streamlit process serves everyone and
# these module-level globals genuinely gate every user at once.
# --------------------------------------------------------------------------

# «Don't stop until there are four strong ones» — bounded, because we cannot
# promise four exist for every topic. When the budget runs out the caller says
# how many it actually found rather than padding the list with weak names.
MIN_STRONG_CANDIDATES = 4
MAX_DISCOVERY_QUERIES = 14
ENRICH_TOP_N = 6

# Round 2: the institutions the programme actually invites from — the list the
# generator prompt already names. Round 3: shapes that surface active people
# (an interview or a 2025-26 lecture proves someone is alive and teaching).
ESCALATION_INSTITUTIONS = [
    'site:ac.il "{topic}"',
    '"{topic}" מכון הרטמן OR "ון ליר" OR "בית מורשה"',
    '"{topic}" "בית אבי חי" OR "זלמן שזר" OR מכללת הרצוג',
    '"{topic}" חוקר OR חוקרת מרצה ישראל',
]
ESCALATION_ACTIVITY = [
    '"{topic}" ראיון',
    '"{topic}" הרצאה 2025 OR 2026',
    '"{topic}" פודקאסט עברית',
    '"{topic}" ספר חדש ראיון',
]

MIN_INTERVAL_SEC = 4.0
COOLDOWN_LADDER = (60, 300, 900)      # escalates while we keep getting blocked
REGION = "il-he"

# ddgs 9.16 ships eight text backends. Rotating matters: one backend blocking
# us no longer ends the session. mojeek and wikipedia run independent indexes
# and are markedly less trigger-happy than the big three.
BACKENDS = "duckduckgo, mojeek, brave, wikipedia, yahoo"

_lock = threading.Lock()
_last_call_at = 0.0
_cooldown_until = 0.0
_cooldown_step = 0
_net_calls = 0
_cache_hits = 0


class SearchUnavailable(RuntimeError):
    """Network search cannot run right now. Carries the query for manual use.

    Raised rather than returned so a caller can never mistake "blocked" for
    "no results found" — the two mean opposite things to a student.
    """

    def __init__(self, message: str, query: str = "", retry_after: int = 0):
        super().__init__(message)
        self.query = query
        self.retry_after = retry_after


def search_status() -> dict:
    """Whether search is usable, and what it has cost so far this process."""
    remaining = max(0, int(_cooldown_until - time.time()))
    return {
        "available": remaining == 0,
        "cooldown_remaining_sec": remaining,
        "network_calls": _net_calls,
        "cache_hits": _cache_hits,
        "min_interval_sec": MIN_INTERVAL_SEC,
    }


def _throttle() -> None:
    """Serialise callers and keep a minimum gap between network calls.

    The sleep happens while holding the lock on purpose: on a shared machine
    we want ten trainees to queue behind one another rather than to burst.
    """
    global _last_call_at
    with _lock:
        gap = time.time() - _last_call_at
        if gap < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - gap)
        _last_call_at = time.time()


def _enter_cooldown() -> int:
    global _cooldown_until, _cooldown_step
    secs = COOLDOWN_LADDER[min(_cooldown_step, len(COOLDOWN_LADDER) - 1)]
    _cooldown_step += 1
    _cooldown_until = time.time() + secs
    return secs


def manual_search_links(query: str) -> dict:
    """The fallback that actually works: hand the student the query itself.

    When search is blocked or rate-limited, the most practical thing we can do
    is give them a clickable link. They have a browser open next to the app
    anyway. This keeps the tool useful even where the network is unavailable.
    """
    q = urllib.parse.quote_plus(query)
    return {
        "query": query,
        "duckduckgo": f"https://duckduckgo.com/?q={q}",
        "google": f"https://www.google.com/search?q={q}",
    }


def _fetch(query: str, max_results: int = 8) -> list[dict]:
    """The single network seam. Cache -> cooldown gate -> throttle -> ddgs.

    Every search in this module goes through here, so caching, throttling and
    backoff are impossible to accidentally bypass.
    """
    global _net_calls, _cache_hits, _cooldown_step

    cached = dm.cache_get(query, backend=BACKENDS, region=REGION)
    if cached is not None:
        _cache_hits += 1
        return cached

    remaining = int(_cooldown_until - time.time())
    if remaining > 0:
        raise SearchUnavailable(
            f"החיפוש בהמתנה עוד {remaining} שניות (נחסמנו זמנית).",
            query=query,
            retry_after=remaining,
        )

    try:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
    except ImportError as exc:
        raise SearchUnavailable(f"ddgs לא מותקן: {exc}", query=query) from exc

    _throttle()
    try:
        results = DDGS().text(
            query,
            region=REGION,
            max_results=max_results,
            backend=BACKENDS,
        )
        _net_calls += 1
    except RatelimitException as exc:
        secs = _enter_cooldown()
        dm.cache_put(query, [], ok=False, backend=BACKENDS, region=REGION)
        raise SearchUnavailable(
            f"מנוע החיפוש חסם אותנו זמנית. ממתינים {secs} שניות.",
            query=query,
            retry_after=secs,
        ) from exc
    except (TimeoutException, DDGSException, OSError) as exc:
        # KNOWN search/network failures only — this covers the proxy refusals
        # seen in sandboxed environments. Cached as a failure, which expires in
        # an hour rather than in 60 days.
        dm.cache_put(query, [], ok=False, backend=BACKENDS, region=REGION)
        raise SearchUnavailable(
            f"החיפוש נכשל: {type(exc).__name__}. אפשר לחפש ידנית בקישור למטה.",
            query=query,
        ) from exc
    # Anything else — a TypeError, an AttributeError, a bug in this module — is
    # deliberately NOT caught. Swallowing it here would cache a real programming
    # error as a network failure and make it look identical to a blocked proxy,
    # which is the hardest kind of bug to find.

    normalised = [
        {
            "title": r.get("title", ""),
            "href": r.get("href", "") or r.get("url", ""),
            "body": r.get("body", "") or r.get("description", ""),
        }
        for r in (results or [])
    ]
    # A successful call clears the escalation, so one bad patch does not leave
    # us in a 15-minute cooldown for the rest of the evening.
    _cooldown_step = 0
    dm.cache_put(
        query, normalised, ok=bool(normalised),
        backend=BACKENDS, region=REGION,
    )
    return normalised


# --------------------------------------------------------------------------
# Discovery queries
#
# Institutions come from system_rules.md §4 — this is not a new list.
# Templates are written to surface PEOPLE rather than articles: staff pages,
# lecture listings, institute pages, podcast episodes, recent authors.
# --------------------------------------------------------------------------

LESSON_PROFILES: dict[str, dict] = {
    "1": {
        "label": "היסודות — היסטוריון, חוקר, איש אקדמיה",
        "queries": [
            'site:ac.il "{topic}" סגל',
            'site:ac.il "{topic}" מרצה',
            '"{topic}" חוקר האוניברסיטה העברית OR בר-אילן OR "תל אביב"',
            '"{topic}" היסטוריון ישראלי הרצאה',
            '"{topic}" ספר חדש מחבר',
        ],
    },
    "2": {
        "label": "העומק והערעור — פילוסוף, הוגה, מחשבת ישראל",
        "queries": [
            'site:ac.il "מחשבת ישראל" "{topic}"',
            '"{topic}" מכון הרטמן OR "ון ליר" OR "בית מורשה"',
            '"{topic}" פילוסופיה הרצאה ישראל',
            '"{topic}" הוגה דעות ראיון',
        ],
    },
    "3": {
        "label": "הזווית המפתיעה — אמנות, קולנוע, פסיכולוגיה, סוציולוגיה",
        "queries": [
            '"{topic}" קולנוע OR פסיכולוגיה הרצאה ישראל',
            '"{topic}" פודקאסט עברית',
            '"{topic}" "בית אבי חי" OR "זלמן שזר"',
            'site:ac.il "{topic}" סוציולוגיה OR אמנות',
        ],
    },
}

# The generator prompt is full of these, and they are texts to study, not
# people to invite. Flagged rather than dropped — a living person may share a
# surname, and silently deleting a name is exactly the failure mode we avoid.
HISTORICAL_THINKERS = {
    "שפינוזה", "קאנט", "קפקא", "עגנון", "לוינס", "קאמי", "ניטשה", "הגל",
    "היידגר", "פרויד", "יונג", "ארנדט", "בובר", "רוזנצווייג", "ביאליק",
    "ברדיצ'בסקי", "הרב קוק", "רמב\"ם", "הרמב\"ם", "מרקס", "דקארט", "אריסטו",
    "אפלטון", "סארטר", "פוקו", "דרידה", "ויטגנשטיין", "לייבוביץ",
}

_DEATH_HINTS = re.compile(r"\(\s*\d{4}\s*[-–—]\s*\d{4}\s*\)|נפטר|ז[\"״']ל|זכרונו לברכה")

_TITLES = r"פרופ[׳'\"]?|פרופסור|ד[\"״']ר|דר[׳']|הרב(?:נית)?|עו[\"״']ד|האלוף|תא[\"״']ל"
_HEB = r"[א-ת]"

# A title followed by 1-3 Hebrew words is a high-precision person pattern.
_RE_TITLED_NAME = re.compile(
    rf"(?:{_TITLES})\s+((?:{_HEB}{{2,}}[־'\"]?\s+){{0,2}}{_HEB}{{2,}})"
)
# A bare name is a PAIR of adjacent Hebrew words in a result TITLE (plus a
# third when the second is a name connector — «יוסי בן ארי»). Every adjacent
# pair of a Hebrew run is tried: a non-overlapping regex used to align its
# window on «שיחה עם דן» and never see «דן כהן» at all. Much noisier than a
# titled match, hence the second-signal bar in `extract_names`.
_RE_HEB_RUN = re.compile(rf"{_HEB}[{_HEB[1:-1]}׳'\"־-]*(?:\s+{_HEB}[{_HEB[1:-1]}׳'\"־-]*)*")
_NAME_CONNECTORS = {"בן", "בר", "בת", "אבו", "אל", "דה"}


def _bare_windows(title: str) -> list[str]:
    out: list[str] = []
    for run in _RE_HEB_RUN.findall(title or ""):
        words = [w for w in re.split(r"\s+", run) if w]
        i = 0
        while i < len(words) - 1:
            cand = f"{words[i]} {words[i + 1]}"
            if words[i + 1] in _NAME_CONNECTORS and i + 2 < len(words):
                cand = f"{cand} {words[i + 2]}"
                i += 1                   # «בן ארי» is not a second person
            if cand not in out:
                out.append(cand)
            i += 1
    return out

# Words that look like names to a regex but are not people.
_NOT_A_NAME = {
    "אוניברסיטה", "האוניברסיטה", "מכון", "המכון", "הרצאה", "הרצאות", "פודקאסט",
    "ספר", "ספרים", "מחלקה", "המחלקה", "פקולטה", "הפקולטה", "בית", "מדרש",
    "כנס", "כנסים", "פרק", "עמוד", "אתר", "חדשות", "ויקיפדיה", "מרכז", "המרכז",
    "קרן", "עמותה", "תוכנית", "קורס", "סדרה", "יום", "שנה", "שנת", "מאמר",
    "מאמרים", "מחקר", "עיון", "ימי", "סדנה", "כתב", "עת", "הוצאת", "הוצאה",
    "ראיון", "סרטון", "וידאו", "צפייה", "קריאה", "לימוד", "לימודי", "תואר",
    "סגל", "חבר", "חברי", "אנשי", "צוות", "רשימת", "כל", "עוד", "לפני",
    "אחרי", "בין", "עם", "של", "על", "אל", "מן", "זה", "היא", "הוא", "הם",
    "תשפ", "תשפ\"ה", "תשפ\"ו", "בני", "ברית", "מדינת", "ישראל", "התוכנית",
    "הישראלי", "הישראלית", "העברית", "היהודית", "היהודי", "בישראל",
    # Verbs and connectives that a greedy match otherwise swallows into the
    # name itself ("משה הלברטל מלמד"). Caught here rather than by trimming,
    # because a real name never contains one of these words.
    "מלמד", "מלמדת", "מלמדים", "מרצה", "מרצים", "מרצות", "תרצה", "ירצה",
    "כתב", "כתבה", "כותב", "כותבת", "אמר", "אמרה", "טוען", "טוענת",
    "חוקר", "חוקרת", "מדבר", "מדברת", "ידבר", "תדבר", "יעביר", "תעביר",
    "משוחח", "משוחחת", "מספר", "מספרת", "בשיחה", "בהרצאה", "בראיון",
    "מנהל", "מנהלת", "עורך", "עורכת", "מגיש", "מגישה", "יתארח", "תתארח",
}


# Function words, connectives, common verbs and site chrome that a 2–3-word
# window catches in a page title. A blocklist is the right tool: a person's name
# never contains one of these, while a whitelist of given names would reject
# real people. The first live search minted «עבודה נוספת לא», «באה במקום
# העבודה» and «גולשים לתוכן ההרצאה» as people — every word of them is here.
_STOPWORDS = {
    "לא", "של", "את", "על", "עם", "כל", "גם", "אבל", "או", "אם", "כי", "מה", "מי",
    "איך", "למה", "מתי", "איפה", "כאן", "שם", "עכשיו", "היום", "אתמול", "מחר",
    "יש", "אין", "היה", "היתה", "הייתה", "היו", "יהיה", "תהיה", "להיות",
    "באה", "בא", "באו", "בואו", "הולך", "הולכת", "במקום", "בגלל", "בשביל", "כדי",
    "לפי", "מול", "תחת", "בתוך", "מתוך", "אצל", "לעומת", "בעקבות", "ליד", "דרך",
    "עבודה", "עבודות", "העבודה", "נוספת", "נוסף", "נוספים", "נוספות", "הקיימת", "הקיים",
    "חדש", "חדשה", "חדשים", "ישן", "ישנה", "גדול", "גדולה", "קטן", "קטנה",
    "טוב", "טובה", "רע", "רעה", "מלא", "מלאה", "המלא", "המלאה", "ראשון", "ראשונה",
    "שני", "שנייה", "אחר", "אחרת", "אחרים", "אחרות", "עצמו", "עצמה", "עצמם",
    "גולשים", "גולש", "לתוכן", "תוכן", "התוכן", "לצפייה", "להאזנה", "להורדה", "לקריאה",
    "דף", "הדף", "העמוד", "הבית", "האתר", "ערוץ", "הערוץ", "פרקים", "עונה",
    "שידור", "שידורים", "חי", "בשידור", "ההרצאה", "ההרצאות", "שיעור", "השיעור",
    "שיעורים", "הקורס", "המאמר", "הספר", "הראיון", "שיחה", "השיחה", "הפודקאסט",
    "בעברית", "עברית", "ישראלי", "ישראלית", "שאלה", "השאלה", "שאלות", "תשובה",
    "התשובה", "תשובות", "דבר", "הדבר", "דברים", "פעם", "פעמים", "שנים", "השנה",
    "ימים", "שבוע", "חודש", "דקות", "שעות", "שעה", "חלק", "החלק", "סוף", "הסוף",
    "תחילת", "התחלה", "אנחנו", "אתם", "אתן", "אני", "אתה", "הן", "שלנו", "שלכם",
    "שלי", "זאת", "זו", "אלה", "אלו", "כך", "ככה", "לכן", "אז", "רק", "כבר",
    "עדיין", "מאוד", "יותר", "פחות", "הכי", "כמה", "הרבה", "מעט", "קצת", "בערך",
    "המאה", "המאות", "העולם", "החיים", "האדם", "בני", "הגדול", "הגדולה", "הקטן",
}
_NOT_A_NAME = _NOT_A_NAME | _STOPWORDS

# A role word IMMEDIATELY before or after a bare two-word window is what turns
# «שיחה עם דן כהן» into a person and leaves «גולשים לתוכן ההרצאה» alone. It
# has to be the very next word: a 30-character window let «שיחה עם … מות
# הנראטיב» promote «מות הנראטיב» to a person.
_ROLE_WORDS = {
    "מרצה", "מרצת", "חוקר", "חוקרת", "סופר", "סופרת", "משורר", "משוררת",
    "היסטוריון", "היסטוריונית", "פילוסוף", "פילוסופית", "פסיכולוג", "פסיכולוגית",
    "סוציולוג", "סוציולוגית", "אנתרופולוג", "אנתרופולוגית", "במאי", "במאית",
    "אמן", "אמנית", "עיתונאי", "עיתונאית", "הרב", "הרבנית", "פרופסור", "דוקטור",
    "בהנחיית", "בהנחיה", "מאת", "בהשתתפות", "הרצאתו", "הרצאתה",
    # connectives that introduce a person in a title: «שיחה עם», «הרצאה של»
    "עם", "של",
}


def _role_adjacent(title: str, name: str) -> bool:
    words = [w.strip("\"״׳'־-:,.?!()[]{}·—–|") for w in re.split(r"\s+", title or "")]
    words = [w for w in words if w]
    parts = name.split()
    for i in range(len(words) - len(parts) + 1):
        if words[i:i + len(parts)] == parts:
            before = words[i - 1] if i > 0 else ""
            after = words[i + len(parts)] if i + len(parts) < len(words) else ""
            if before in _ROLE_WORDS or after in _ROLE_WORDS:
                return True
    return False


def lesson_keywords(lesson_topic: str, limit: int = 3) -> list[str]:
    """The lesson title as SEARCH TERMS, not as a phrase.

    «מות הנראטיב הגדול: איך המאה ה-20 ריסקה את הוודאות?» was pasted whole
    into every query, in quotes — an exact phrase no page on the web contains,
    so the engine degraded to noise and 38 junk "names" came back. Three
    content words, unquoted, is what a person would type."""
    out: list[str] = []
    for w in re.split(r"\s+", lesson_topic or ""):
        w = w.strip("\"״׳'־-:,.?!()[]{}")
        if len(w) >= 4 and re.fullmatch(r"[א-ת\"״׳'־-]+", w) \
                and w not in _STOPWORDS and w not in out:
            out.append(w)
    return out[:limit]


def _looks_like_person(name: str) -> bool:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if not (2 <= len(parts) <= 3):
        return False
    if any(p.strip("־'\"") in _NOT_A_NAME for p in parts):
        return False
    if any(len(p.strip("־'\"")) < 2 for p in parts):
        return False
    return True


def _trim_to_name(captured: str, titled: bool = True) -> Optional[str]:
    """The person inside a greedy capture, or None.

    Both name patterns take up to three Hebrew words, so «ד״ר רות לוי מרצה»
    captures a trailing common noun and the whole match was thrown away —
    losing a real person, and (worse) counting her once instead of twice, which
    is the difference between «medium» and «high» confidence. Backing off to the
    first two words recovers her without loosening what counts as a person.

    The back-off is for TITLED captures only: on a bare window it gave a
    rejected three-word phrase a second chance to become a two-word "name".
    """
    name = captured.strip()
    if _looks_like_person(name):
        return name
    parts = [p for p in re.split(r"\s+", name) if p]
    if titled and len(parts) > 2:
        shorter = " ".join(parts[:2])
        if _looks_like_person(shorter):
            return shorter
    return None


def extract_names(results: list[dict], exclude_words: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """Mine person-names out of search results.

    `exclude_words` are the words of the SUBJECT being searched: a topic phrase
    recurs in result after result («מות הנראטיב» in every title about the
    lesson), which is exactly the second-signal bar a bare window has to clear
    — so a window that contains a subject word is never a person.

    This is what makes discovery real rather than decorative. Without it the
    module could only ever verify names somebody already knew, which means an
    unknown-but-excellent lecturer would never surface.

    Precision beats recall here: a junk name wastes a student's time, and the
    caller sees a confidence level rather than a flat list.
    """
    found: dict[str, dict] = {}

    for r in results:
        title = r.get("title", "") or ""
        body = r.get("body", "") or ""
        blob = f"{title} {body}"

        for m in _RE_TITLED_NAME.finditer(blob):
            name = _trim_to_name(m.group(1))
            if not name:
                continue
            entry = found.setdefault(
                name, {"name": name, "hits": 0, "titled": False, "evidence": []}
            )
            entry["titled"] = True
            entry["hits"] += 1
            if r not in entry["evidence"]:
                entry["evidence"].append(r)

        # Bare names only from titles, where a person's name is far more
        # likely to be the subject than in prose — and a bare window needs a
        # SECOND signal before it is a person at all: the same two words in
        # another result, or a role word beside them («שיחה עם דן כהן»).
        for window in _bare_windows(title):
            name = _trim_to_name(window, titled=False)
            if not name or any(w in exclude_words for w in name.split()):
                continue
            entry = found.setdefault(
                name, {"name": name, "hits": 0, "titled": False, "evidence": [], "role": False}
            )
            if entry["titled"]:
                continue                 # counted by the titled pattern already
            if r not in entry["evidence"]:
                entry["evidence"].append(r)
                entry["hits"] += 1
            if _role_adjacent(title, name):
                entry["role"] = True

    out = []
    for entry in found.values():
        if entry["titled"] and entry["hits"] >= 2:
            confidence = "high"
        elif entry["titled"]:
            confidence = "medium"
        elif entry["hits"] >= 2 or entry.get("role"):
            confidence = "low"
        else:
            continue                     # one bare window in one title is not a person
        entry["confidence"] = confidence
        entry["flags"] = _flags_for(entry["name"], entry["evidence"])
        out.append(entry)

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda e: (order[e["confidence"]], -e["hits"]))
    return out


def _flags_for(name: str, evidence: list[dict]) -> list[str]:
    flags: list[str] = []
    if any(t in name for t in HISTORICAL_THINKERS):
        flags.append("☠️ הוגה היסטורי — טקסט ללימוד, לא מועמד להרצאה")
    else:
        blob = " ".join(f"{e.get('title','')} {e.get('body','')}" for e in evidence)
        if _DEATH_HINTS.search(blob):
            flags.append("☠️ ייתכן שאינו בחיים — לבדוק לפני פנייה")
    return flags


def _index_note(name: str) -> list[str]:
    """Local-index notes for a name. No network — this is a free check.

    Answers the last line of the ⚠️ לאמת checklist ("have we already approached
    them this year?") from the shared outreach log, which is the whole point of
    the index: the next pair must see what the previous pair already did.
    """
    notes = []
    for row in dm.get_speaker_status(name):
        status = (row.get("current_status") or "").strip()
        origin = "📗 מהמאגר" if row.get("source_type") == "original_44" else "📘 במאגר"
        notes.append(f"{origin} · {status or 'ללא סטטוס'}")

        if row.get("has_outreach"):
            # THE collision-prevention line. Without it two pairs approach the
            # same person a week apart and neither knows.
            history = dm.get_outreach_for_speaker(row["speaker_id"])
            for o in history[:3]:
                who = o.get("student_name") or "מישהו מהצוות"
                where = f"משמר #{o['mishmar_id']:02d}" if o.get("mishmar_id") else "ללא משמר"
                when = (o.get("created_at") or "")[:10]
                notes.append(f"‼️ {who} כבר פנה — {where} · {o['status']} · {when}")

        if "לא יכול" in status or "סירב" in status:
            # Per 2026-27/speakers.md: refusals are almost always to a specific
            # date, not in principle. Presenting one as a hard no loses a lead.
            notes.append("↩️ סירוב הוא כמעט תמיד לתאריך מסוים — שווה לנסות שוב בתקופה אחרת")
    return notes


def search_candidates(
    topic: str,
    lesson: str = "1",
    max_queries: int = 4,
    lesson_topic: str = "",
    include_index: bool = True,
    progress=None,
) -> dict:
    """DISCOVERY: find candidate speakers for a topic, from index AND from the web.

    `progress` is an optional callable taking one Hebrew line; the screen uses
    it to show which round is running instead of a blind spinner.

    Returns index hits, newly mined web names, the raw results behind them, and
    every query used (so a student can rerun any of them by hand).
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic is required")

    lesson = str(lesson or "")
    subject_words = frozenset(w.strip("\"״׳'־-:,.?!()") for w in
                              re.split(r"\s+", f"{topic} {lesson_topic}") if len(w) > 1)
    # The evening's topic and the SLOT's topic are different questions — «אמון»
    # for the night, «אמון במשפחה» for this lesson — and the queries want both.
    # `subject` is the human-readable pair (shown, and handed to verification);
    # the QUERIES quote only the topic and add the lesson as up to three plain
    # keywords, in the first round only — the escalation rounds widen the net,
    # and a sentence in quotes was the reason the first live search found nothing.
    subject = f"{topic} {lesson_topic}".strip() if lesson_topic.strip() else topic
    keywords = lesson_keywords(lesson_topic)

    if lesson == "4":
        # The generator prompt is explicit: lesson 4 is חבורות / ניגון /
        # כתיבה — interactive by design, never a frontal outside guest.
        return {
            "topic": topic,
            "lesson": lesson,
            "skipped": True,
            "reason": (
                "שיעור 4 הוא נחיתה אל הלב — חבורות, ניגון, כתיבה. "
                "לא מביאים אליו מרצה חיצוני. חפשו מרצה לשיעורים 1–3, "
                "ולשיעור 4 בנו פורמט אינטראקטיבי עם צוות הבית."
            ),
            "index_hits": [], "web_names": [], "raw": [], "queries": [], "errors": [],
        }

    # No lesson chosen is the DEFAULT now: the profile is a recommendation, not
    # a requirement, so an empty choice searches all three angles.
    if lesson in LESSON_PROFILES:
        profile = LESSON_PROFILES[lesson]
        round1 = list(profile["queries"][:max_queries])
    else:
        profile = {"label": "כל הזוויות"}
        round1, seen_t = [], set()
        for k in ("1", "2", "3"):          # round-robin so no angle is starved
            for t in LESSON_PROFILES[k]["queries"][:2]:
                if t not in seen_t:
                    seen_t.add(t)
                    round1.append(t)

    index_hits = dm.search_speakers_by_topic(topic, lesson=lesson) if include_index else []

    raw: list[dict] = []
    queries: list[str] = []
    errors: list[dict] = []
    web_names: list[dict] = []

    def _run(templates: list[str], with_keywords: bool = False) -> None:
        for template in templates:
            if len(queries) >= MAX_DISCOVERY_QUERIES:
                return
            q = template.format(topic=topic)
            if with_keywords and keywords:
                q = f"{q} {' '.join(keywords)}"
            if q in queries:
                continue
            queries.append(q)
            try:
                raw.extend(_fetch(q))
            except SearchUnavailable as exc:
                errors.append({"query": q, "error": str(exc),
                               "manual": manual_search_links(q)})
                # Keep going: a later query may hit the cache even while the
                # network is down, and each failure carries its own manual link.
                continue

    def _strong() -> int:
        return sum(1 for e in web_names if e.get("confidence") == "high")

    # ---- adaptive rounds -------------------------------------------------
    # One pass used to be the whole search: if the first four queries returned
    # thin results, the screen shrugged. The instruction now is «don't stop
    # until there are four strong names» — bounded, because we cannot promise
    # that four exist for every topic. Each round widens the net differently.
    rounds = [round1, ESCALATION_INSTITUTIONS, ESCALATION_ACTIVITY]
    round_labels = ("סורק את הרשת", "מרחיב למוסדות ואקדמיה", "מרחיב לפעילות אחרונה — ראיונות, הרצאות, פודקאסטים")
    rounds_used = 0
    for templates in rounds:
        if progress:
            progress(f"{round_labels[rounds_used]} · סבב {rounds_used + 1}")
        _run(templates, with_keywords=(rounds_used == 0))
        rounds_used += 1
        web_names = extract_names(raw, exclude_words=subject_words)
        if _strong() >= MIN_STRONG_CANDIDATES or len(queries) >= MAX_DISCOVERY_QUERIES:
            break

    # Annotate anything we already know about, so two trainees cannot approach
    # the same person unaware of each other. This runs even when the index is
    # NOT being searched: it is collision safety, not a search result.
    known = {r["name"] for r in index_hits}
    for entry in web_names:
        entry["index_notes"] = _index_note(entry["name"])
        entry["already_known"] = entry["name"] in known or bool(entry["index_notes"])

    return {
        "topic": topic,
        "lesson_topic": lesson_topic,
        "subject": subject,
        "keywords": keywords,
        "rounds_used": rounds_used,
        "strong_found": sum(1 for e in web_names if e.get("confidence") == "high"),
        "lesson": lesson,
        "lesson_label": profile["label"],
        "skipped": False,
        "index_hits": index_hits,
        "web_names": web_names,
        "raw": raw,
        "queries": queries,
        "errors": errors,
    }


def verify_speaker(
    name: str,
    topic: Optional[str] = None,
    depth: int = 2,
) -> dict:
    """VERIFICATION: mechanise the ⚠️ לאמת checklist for one name.

    depth=2 by default. Four queries per name reads as more thorough, but at a
    4s throttle it turns three candidates into a full minute of waiting, and
    the first two queries carry most of the signal.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")

    checks = [
        f'"{name}" הרצאה 2025 OR 2026',
        f'"{name}" {topic}' if topic else f'"{name}" מרצה',
        f'"{name}" אוניברסיטה OR מכון OR מכללה',
        f'"{name}" ראיון OR פודקאסט',
    ][: max(1, depth)]

    evidence: list[dict] = []
    errors: list[dict] = []
    for q in checks:
        try:
            evidence.extend(_fetch(q, max_results=6))
        except SearchUnavailable as exc:
            errors.append({"query": q, "error": str(exc), "manual": manual_search_links(q)})

    blob = " ".join(f"{e.get('title','')} {e.get('body','')}" for e in evidence)
    recent_years = sorted(set(re.findall(r"\b(202[3-9])\b", blob)))
    notes = _index_note(name)   # one lookup, used twice below

    return {
        "name": name,
        "topic": topic,
        "queries": checks,
        "evidence": evidence[:12],
        "errors": errors,
        "flags": _flags_for(name, evidence),
        "index_notes": notes,
        "recent_years": recent_years,
        # Deliberately NOT auto-decided. The module gathers evidence; a human
        # (or the model in chat) judges it. Contact details are never scraped.
        "checklist": {
            "בחיים ופעיל היום": "⚠️ לבדוק בראיות למטה",
            "עדיין עוסק בתחום": "⚠️ לבדוק בראיות למטה",
            "היכן מתגורר": "⚪ לא ידוע — לברר",
            "מרצה בפועל בפני קהל": "⚠️ לבדוק בראיות למטה",
            "לא פנינו אליו השנה": (
                "⚠️ מופיע במאגר — ראו הערות" if notes else "✅ לא נמצא במאגר"
            ),
            "פרטי קשר": "TBD — לעולם לא ממולא אוטומטית",
        },
    }


def format_for_chat(result: dict) -> str:
    """Build the block a student pastes into the chat for synthesis.

    Synthesis happens in the chat window, not in the app — no paid API in v1.
    The app's job is to hand over evidence in a form a model can reason about.
    """
    lines: list[str] = []
    topic = result.get("topic", "")
    lines.append(f"# מועמדים למרצה — נושא: {topic} · שיעור {result.get('lesson','?')}")
    lines.append(f"({result.get('lesson_label','')})")
    lines.append("")

    if result.get("index_hits"):
        lines.append("## 📗 מהמאגר")
        for r in result["index_hits"]:
            lines.append(
                f"- **{r['name']}** — {r.get('expertise_topics') or 'תחום לא רשום'} · "
                f"אזור: {r.get('region') or '⚪ לא ידוע'} · סטטוס: {r.get('status') or '—'}"
            )
        lines.append("")

    if result.get("web_names"):
        lines.append("## 🌐 שמות שעלו מחיפוש (לא מהמאגר — כולם ⚠️ לאמת)")
        for e in result["web_names"][:15]:
            flag = " ".join(e.get("flags", []))
            known = " · ‼️ כבר במאגר" if e.get("already_known") else ""
            src = e["evidence"][0].get("href", "") if e.get("evidence") else ""
            lines.append(f"- **{e['name']}** (ודאות: {e['confidence']}){known} {flag}")
            if src:
                lines.append(f"  - מקור: {src}")
        lines.append("")

    if result.get("errors"):
        lines.append("## ⚠️ שאילתות שנכשלו — להריץ ידנית")
        for err in result["errors"]:
            lines.append(f"- `{err['query']}` → {err['manual']['duckduckgo']}")
        lines.append("")

    lines.append(
        "**לסינתזה:** דרג את השמות לפי התאמה לנושא ולפרופיל השיעור, סמן מי "
        "חי ופעיל היום, ציין אזור מגורים אם ידוע, וסמן כל שם שאינו מהמאגר "
        "ב-⚠️ לאמת. אל תמציא פרטי קשר."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys

    topic = sys.argv[1] if len(sys.argv) > 1 else "תשובה"
    lesson = sys.argv[2] if len(sys.argv) > 2 else "1"
    res = search_candidates(topic, lesson)
    print(json.dumps(
        {k: v for k, v in res.items() if k != "raw"}, ensure_ascii=False, indent=2
    ))
    print()
    print(format_for_chat(res))
    print()
    print("status:", search_status())
