"""
archive.py — cross-year memory: what did we already do, and how did it go?

Two sources, and they answer different questions:

  * The 2025-26 work-files (`Mishmer-section/2025-26/mishmarim/`) — what a past
    Mishmar actually was: its running order, who taught, what the decoration
    and the themed dinner were.
  * The Feedback table — how it went. That half is empty until the programme
    runs a season with the post-Mishmar review, and grows from there.

Be honest about the corpus size. There are five archived work-files. A trainee
asking "was there a Mishmar on תשובה?" will often get nothing, and nothing is
the correct answer — not a reason to stretch a weak match into a strong one.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import data_manager as dm

ARCHIVE_ROOT = os.path.join(dm.REPO_ROOT, "Mishmer-section", "2025-26", "mishmarim")
CURRENT_ROOT = os.path.join(dm.REPO_ROOT, "Mishmer-section", "2026-27", "mishmarim")


# Every work-file inherits the template's scaffolding — instructional
# blockquotes and the status legend "⬜ לא פנינו · 📩 נשלחה פנייה · ⏳ ממתין
# לתשובה · ...". That legend contains the word תשובה, so an unfiltered search
# for a Mishmar on תשובה matched all 21 empty templates. Boilerplate has to be
# stripped before matching or the archive returns noise for common words.
_BOILERPLATE = re.compile(
    r"^\s*(>.*|\*\*סטטוסים:\*\*.*|\|\s*-+.*|#{1,6}\s*$)$", re.MULTILINE
)


def _strip_boilerplate(text: str) -> str:
    return _BOILERPLATE.sub("", text)


def _iter_workfiles(include_current: bool = False) -> list[tuple[str, str]]:
    """(label, content) for each work-file, with template scaffolding removed.

    Only the 2025-26 archive by default. This season's folders are still
    unfilled templates, so searching them answers "does the template mention
    this word", not "did we do this before" — which is the actual question.
    """
    roots = [ARCHIVE_ROOT] + ([CURRENT_ROOT] if include_current else [])
    out: list[tuple[str, str]] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry, "workfile.md")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    out.append((entry, _strip_boilerplate(fh.read())))
            except OSError:
                continue
    return out


def _title_of(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _snippet(text: str, term: str, width: int = 160) -> str:
    idx = text.find(term)
    if idx < 0:
        return ""
    start = max(0, idx - width // 2)
    return re.sub(r"\s+", " ", text[start : start + width]).strip()


def _stem(term: str) -> str:
    """Crude Hebrew stem: drop the last two letters on a long-enough word.

    Not linguistics — just enough that פילוסופיה matches פילוסופית. Floored at
    four characters so short words are never shortened into noise.
    """
    return term[: max(4, len(term) - 2)] if len(term) >= 6 else term


def search_past_mishmarim(query: str, limit: int = 5) -> list[dict]:
    """Find past Mishmarim whose work-file mentions the query.

    Word-level matching, not semantic — with a five-document corpus a fancier
    approach would be false precision.
    """
    query = (query or "").strip()
    if not query:
        return []

    terms = [t for t in re.split(r"\s+", query) if len(t) >= 3]
    results = []
    for label, text in _iter_workfiles():
        # Match the stem as well as the whole word. Hebrew inflects heavily:
        # a search for "פילוסופיה" must find "משמר פילוסופית המזרח", which a
        # plain substring match misses entirely.
        hits = [t for t in terms if t in text or _stem(t) in text]
        if not hits:
            continue
        # Distinct terms matched dominates; raw occurrences break ties, so a
        # work-file genuinely about the subject outranks a passing mention.
        occurrences = sum(max(text.count(t), text.count(_stem(t))) for t in hits)
        results.append(
            {
                "folder": label,
                "title": _title_of(text, label),
                "matched_terms": hits,
                "score": len(hits) * 100 + occurrences,
                "occurrences": occurrences,
                "snippet": _snippet(text, hits[0] if hits[0] in text else _stem(hits[0])),
            }
        )
    results.sort(key=lambda r: -r["score"])
    return results[:limit]


def speaker_history(name: str) -> dict:
    """Everything we know about how this speaker went, across years.

    Combines the index row (what they teach, status) with any feedback rows.
    """
    rows = dm.get_speaker_by_name(name)
    feedback = dm.get_feedback_for_speaker(name)
    ratings = [f["rating"] for f in feedback if f.get("rating")]
    return {
        "name": name,
        "index_entries": rows,
        "feedback": feedback,
        "times_rated": len(ratings),
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        # Said plainly so a caller does not read silence as a bad review.
        "note": (
            "אין עדיין משוב על המרצה הזה — המשוב מצטבר מהעונה הזו והלאה."
            if not feedback else ""
        ),
    }


def similar_topics(topic: str) -> list[dict]:
    """Mishmarim in the database whose topic resembles this one."""
    if not (topic or "").strip():
        return []
    return dm.find_mishmarim_by_topic(topic)


def summarise_for_topic(topic: str) -> dict:
    """One call answering 'has anything like this been done before?'"""
    past = search_past_mishmarim(topic)
    same = similar_topics(topic)
    return {
        "topic": topic,
        "past_workfiles": past,
        "same_topic_this_season": same,
        "corpus_size": len(_iter_workfiles()),
        "note": (
            "לא נמצא משמר קודם בנושא הזה. הארכיון מכיל כרגע מעט קבצים, "
            "אז היעדר תוצאה לא אומר שלא היה — רק שלא תועד."
            if not past and not same else ""
        ),
    }
