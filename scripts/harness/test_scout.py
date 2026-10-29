"""The scout's round 3, without the Anthropic API — what the code does around
the model, on recorded answers.

    python3 scripts/harness/db.py up
    python3 scripts/harness/test_scout.py

`chat_agent._scout_run` is driven by a stand-in client whose streams return
recorded messages — a search, its results, a page opened, and the JSON the
model ends with — so everything the code decides is checked for real:

  the request   the examples typed, the «לא מתאים» marks (one per person, the
                newest reason) and the evening's own people reach the model;
                the search budget is 3 per angle + 1 per example (ceiling 12),
                pages 1 per angle + 1, +1 with examples (ceiling 5)
  grounding     a `teaching_link` the search never returned is blanked; a name
                with no retrieved page at all is thrown out as ungrounded;
                contact fields are stripped
  steering      an example, a marked name and a person already on the evening
                never come back — each lands in `rejected` with the reason
  ranking       🟢 a lecture page AND a page from 2024+ · 🟡 a lecture page, or
                a recent institutional page · 🟠 neither — and the list is
                sorted by it before the cap
  pause_turn    resumed with the assistant turn sent back, the answer read
                from the last turn only, the usage summed
  storage       `slim_for_storage` keeps the teaching fields, the examples and
                the marks; `dm.mark_search_dismissed` appends to one row (a
                second mark replaces the reason) and touches no other;
                `dm.search_avoid` / `dm.evening_people` read them back — on a
                fresh copy of the harness fixture, through the shim

What the model makes of the new prompts is not checked here — that is the
pair's re-run of a real topic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class Node(SimpleNamespace):
    """A content block as the SDK hands it over — attributes, and model_dump()
    for the assistant turn the code sends back after a pause."""

    def model_dump(self, exclude_none: bool = False) -> dict:
        def plain(v):
            if isinstance(v, Node):
                return v.model_dump(exclude_none)
            if isinstance(v, list):
                return [plain(x) for x in v]
            return v
        return {k: plain(v) for k, v in vars(self).items() if not (exclude_none and v is None)}


def usage(searches: int, fetches: int) -> Node:
    return Node(input_tokens=1000, output_tokens=400, cache_read_input_tokens=2000,
                cache_creation_input_tokens=0,
                server_tool_use=Node(web_search_requests=searches, web_fetch_requests=fetches))


class Stream:
    def __init__(self, msg: Node):
        self.msg = msg
        self.current_message_snapshot = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for _ in self.msg.content:
            yield Node(type="content_block_stop")

    def get_final_message(self) -> Node:
        return self.msg


class Client:
    """messages.stream(**kwargs) → the next recorded message; every request kept."""

    def __init__(self, replies: list[Node]):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def stream(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, ensure_ascii=False, default=str)))
        return Stream(self.replies.pop(0))


LECTURE = "https://www.youtube.com/watch?v=lecture-on-marx"
FACULTY = "https://history.example.ac.il/staff/old-professor"
MECHINA = "https://mechina.example.org.il/team"
OLD = "https://blog.example.com/2019/post"
FOREIGN = "https://never-retrieved.example.com/talk"
LECTURE2 = "https://podcast.example.com/episode-12"


def searched() -> list[Node]:
    return [
        Node(type="server_tool_use", id="s1", name="web_search", input={"query": "הרצאה מרקס מכינה"}),
        Node(type="web_search_tool_result", tool_use_id="s1", content=[
            Node(type="web_search_result", url=LECTURE, title="הרצאה: מרקס לצעירים", page_age="March 3, 2025"),
            Node(type="web_search_result", url=FACULTY, title="סגל החוג", page_age="2025-01-10"),
            Node(type="web_search_result", url=OLD, title="פוסט ישן", page_age="2019-05-01"),
            Node(type="web_search_result", url=LECTURE2, title="פרק 12", page_age=None),
        ]),
        Node(type="server_tool_use", id="f1", name="web_fetch", input={"url": MECHINA}),
        Node(type="web_fetch_tool_result", tool_use_id="f1",
             content=Node(type="web_fetch_result", url=MECHINA, content=Node(title="צוות המכינה"))),
    ]


ANSWER = {"candidates": [
    # a faculty page from 2025 and nothing else → 🟡 (listed FIRST by the model)
    {"name": "פרופ׳ ותיק", "title": "", "angle": "1", "bio": "חוקר", "teaching": "", "teaching_link": "",
     "fit": "תחום", "link": FACULTY, "evidence": [{"title": "", "href": FACULTY}], "phone": "050-0000000"},
    # a lecture page from 2025 → 🟢
    {"name": "מרצה צעירה", "title": "", "angle": "1", "bio": "מורה במכינה",
     "teaching": "מלמדת מרקס בסדרת הרצאות", "teaching_link": LECTURE, "fit": "מרקס לצעירים",
     "link": MECHINA, "evidence": [{"title": "", "href": MECHINA}], "email": "x@example.com"},
    # a teaching link the search never returned, an old page → link blanked, 🟠
    {"name": "שם עם קישור זר", "title": "", "angle": "2", "bio": "", "teaching": "מרצה",
     "teaching_link": FOREIGN, "fit": "", "link": OLD, "evidence": []},
    # a podcast page with no date → 🟡
    {"name": "מנחת פודקאסט", "title": "", "angle": "3", "bio": "", "teaching": "פודקאסט",
     "teaching_link": LECTURE2, "fit": "", "link": "", "evidence": []},
    # the typed example, the marked name, the person on the evening, the ungrounded one
    {"name": "אסף מלאך", "title": "ד\"ר", "angle": "2", "link": LECTURE, "evidence": []},
    {"name": "מסומן לא מתאים", "title": "", "angle": "2", "link": LECTURE, "evidence": []},
    {"name": "כבר בערב", "title": "", "angle": "3", "link": LECTURE, "evidence": []},
    {"name": "בלי שום דף", "title": "", "angle": "3", "link": FOREIGN,
     "evidence": [{"title": "", "href": FOREIGN}]},
], "rejected": [{"name": "קרל מרקס", "why": "לא בחיים"}]}


def scan(ca, replies: list[Node], **kw) -> tuple[dict, Client]:
    client = Client(replies)
    ca.get_client = lambda: client
    smap = {"reading": "על מהפכות", "angles": [
        {"key": k, "label": ca.ANGLES[k], "field": f"זווית {k}", "who": "מחנך/ת", "terms": ["מרקס"],
         "where": ["מכינות קדם-צבאיות"], "why": "", "on": True} for k in ("1", "2", "3")]}
    res = ca.scout_speakers("מרקסיזם ומהפכות", "", "", scout_map_result=smap, **kw)
    return res, client


def main() -> int:
    checks: dict[str, bool] = {}
    facts: dict = {}
    r = subprocess.run([sys.executable, str(HERE / "db.py"), "fresh", "scouttest"],
                       capture_output=True, text=True, cwd=ROOT)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False))
        return 1
    os.environ["MISHMAR_NO_CACHE"] = "1"             # before data_manager wraps its reads
    sys.path[:0] = [str(HERE), str(ROOT)]
    import logging
    import streamlit                                  # noqa: F401 — then quiet its cache logger
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    import pgrest_shim
    pgrest_shim.DSN = out["dsn"]
    import data_manager as dm
    dm.set_client(pgrest_shim.FakeSupabase())
    import chat_agent as ca
    ca._index_memory = lambda name: None              # the index is the fixture's business, not this test's

    # ---- names
    checks["one person however typed: ד\"ר / ד״ר / no title / double spaces"] = len({
        ca._name_key(x) for x in ('ד"ר אסף מלאך', "ד״ר אסף מלאך", "אסף  מלאך", " אסף מלאך ")}) == 1
    checks["examples: cleaned, once each, at most three"] = ca._clean_names(
        ["ד\"ר אסף מלאך", "אסף מלאך", "", "  יגאל ליברנט ", "א", "ב"], ca.MAX_EXAMPLES) \
        == ["ד\"ר אסף מלאך", "יגאל ליברנט", "א"]
    checks["marks: one per person, the newest reason"] = ca._clean_avoid(
        [{"name": "פלוני", "why": "לא בנושא"}, {"name": "אלמוני", "why": "אקדמי מדי"},
         {"name": "פלוני", "why": "אקדמי מדי"}, {"name": "", "why": "x"}, "junk"]) \
        == [{"name": "פלוני", "why": "אקדמי מדי"}, {"name": "אלמוני", "why": "אקדמי מדי"}]

    # ---- budgets
    def budget(n, k):
        t = ca._scout_tools(n, True, k)
        return t[0]["max_uses"], t[1]["max_uses"]
    facts["budgets"] = {f"{n}x{k}": budget(n, k) for n in (1, 2, 3) for k in (0, 1, 3)}
    checks["budget: 3 searches per angle + 1 per example (≤12); pages angles+1, +1 with examples (≤5)"] = \
        facts["budgets"] == {"1x0": (3, 2), "1x1": (4, 3), "1x3": (6, 3), "2x0": (6, 3), "2x1": (7, 4),
                             "2x3": (9, 4), "3x0": (9, 4), "3x1": (10, 5), "3x3": (12, 5)}
    checks["budget: no fetch tool when fetch is off for the organization"] = \
        len(ca._scout_tools(3, False, 2)) == 1

    # ---- one scan, every rule
    final = Node(role="assistant", stop_reason="end_turn", usage=usage(3, 1),
                 content=searched() + [Node(type="text", text=json.dumps(ANSWER, ensure_ascii=False),
                                            citations=None)])
    res, client = scan(ca, [final],
                       examples=["ד״ר אסף מלאך", "יגאל ליברנט"],
                       avoid=[{"name": "מסומן לא מתאים", "why": "לא בנושא"},
                              {"name": "מסומן לא מתאים", "why": "אקדמי מדי"}],
                       on_evening=["כבר בערב", "מועמד/ת אחר/ת"])
    sent = json.loads(client.requests[0]["messages"][0]["content"])
    tools = client.requests[0]["tools"]
    facts["sent"] = {k: sent.get(k) for k in ("examples", "avoid", "on_evening", "max_candidates")}
    checks["request: examples, the newest mark, the evening's people — all three reach the model"] = \
        sent["examples"] == ["ד״ר אסף מלאך", "יגאל ליברנט"] \
        and sent["avoid"] == [{"name": "מסומן לא מתאים", "why": "אקדמי מדי"}] \
        and sent["on_evening"] == ["כבר בערב", "מועמד/ת אחר/ת"]
    checks["request: 3 angles + 2 examples → 11 searches, 5 pages"] = \
        tools[0]["max_uses"] == 11 and tools[1]["max_uses"] == 5
    checks["request: the system prompt asks for people who teach, not faculty pages"] = \
        "מלמדים היום צעירים או קהל רחב" in client.requests[0]["system"][0]["text"] \
        and "לא דפי סגל" in client.requests[0]["system"][0]["text"]
    got = {c["name"]: c for c in res.get("candidates") or []}
    facts["ranked"] = [(c["name"], c["confidence"]) for c in res.get("candidates") or []]
    checks["ranking: 🟢 lecture + 2025 · 🟡 recent faculty page · 🟡 undated podcast · 🟠 foreign link"] = \
        got.get("מרצה צעירה", {}).get("confidence") == "high" \
        and got.get("פרופ׳ ותיק", {}).get("confidence") == "medium" \
        and got.get("מנחת פודקאסט", {}).get("confidence") == "medium" \
        and got.get("שם עם קישור זר", {}).get("confidence") == "low"
    checks["ranking: sorted by it — the lecturer before the professor the model listed first"] = \
        [n for n, _ in facts["ranked"]][:1] == ["מרצה צעירה"] \
        and [lvl for _, lvl in facts["ranked"]] == sorted((lvl for _, lvl in facts["ranked"]),
                                                          key=ca._CONFIDENCE_RANK.get)
    checks["grounding: a teaching link the search never returned is blanked"] = \
        got.get("שם עם קישור זר", {}).get("teaching_link") == "" \
        and got.get("מרצה צעירה", {}).get("teaching_link") == LECTURE \
        and got.get("מרצה צעירה", {}).get("teaching_title") == "הרצאה: מרקס לצעירים"
    checks["grounding: no phone / email survives"] = \
        not any(k in c for c in got.values() for k in ("phone", "email", "contact"))
    why = {x["name"]: x["why"] for x in res.get("rejected") or []}
    facts["rejected"] = why
    checks["steering: the example, the marked name, the evening's person — out, each with its reason"] = \
        "אסף מלאך" not in got and "הדוגמאות" in why.get("אסף מלאך", "") \
        and "מסומן לא מתאים" not in got and why.get("מסומן לא מתאים") == "סומן קודם כלא מתאים — אקדמי מדי" \
        and "כבר בערב" not in got and why.get("כבר בערב") == "כבר בערב"
    checks["grounding: a name with no retrieved page → ungrounded"] = \
        "בלי שום דף" not in got and "ungrounded" in why.get("בלי שום דף", "")
    checks["the cap still holds (5)"] = len(got) <= ca.MAX_SCOUT_CANDIDATES
    slim = ca.slim_for_storage({**res, "dismissed": [{"name": "x", "why": "לא בנושא"}]})
    sc = {c["name"]: c for c in slim["candidates"]}
    checks["storage: teaching fields, the examples and the marks are kept"] = \
        sc["מרצה צעירה"]["teaching_link"] == LECTURE and sc["מרצה צעירה"]["teaching"] \
        and slim["examples"] == ["ד״ר אסף מלאך", "יגאל ליברנט"] \
        and slim["avoid"] == [{"name": "מסומן לא מתאים", "why": "אקדמי מדי"}] \
        and slim["dismissed"] == [{"name": "x", "why": "לא בנושא"}]

    # ---- a paused turn
    paused = Node(role="assistant", stop_reason="pause_turn", usage=usage(2, 0), content=searched()[:2]
                  + [Node(type="text", text="{\"half\": ", citations=None)])
    done = Node(role="assistant", stop_reason="end_turn", usage=usage(1, 1),
                content=searched()[2:] + [Node(type="text", text=json.dumps(ANSWER, ensure_ascii=False),
                                               citations=None)])
    res2, client2 = scan(ca, [paused, done])
    checks["pause_turn: resumed with the turn sent back; the answer from the last turn; usage summed"] = \
        len(client2.requests) == 2 and client2.requests[1]["messages"][-1]["role"] == "assistant" \
        and not res2.get("fallback") and (res2.get("usage") or {}).get("searches") == 3

    # ---- the marks on the database
    import psycopg2
    sid = dm.save_search("מרקסיזם", ca.slim_for_storage(res), mishmar_id=5, lesson_topic="", angle="")
    other = dm.save_search("נושא אחר", ca.slim_for_storage(res), mishmar_id=5)
    dm.mark_search_dismissed(sid, "פרופ׳ ותיק", "לא בנושא")
    dm.mark_search_dismissed(sid, "מנחת פודקאסט", "לא מרצה לצעירים")
    dm.mark_search_dismissed(sid, "פרופ׳ ותיק", "אקדמי מדי")
    dm.mark_search_dismissed(None, "x", "y")                       # no row: nothing, no error
    con = psycopg2.connect(out["dsn"])
    cur = con.cursor()
    cur.execute("SELECT id, results_json FROM speaker_searches WHERE id IN (%s, %s)", (sid, other))
    rows = dict(cur.fetchall())
    facts["dismissed"] = rows[sid].get("dismissed")
    checks["db: marks on the row — a second mark replaces the reason; the other row untouched"] = \
        rows[sid].get("dismissed") == [{"name": "מנחת פודקאסט", "why": "לא מרצה לצעירים"},
                                       {"name": "פרופ׳ ותיק", "why": "אקדמי מדי"}] \
        and not rows[other].get("dismissed") and rows[sid].get("examples") == ["ד״ר אסף מלאך", "יגאל ליברנט"]
    checks["db: search_avoid reads the evening's marks back; none for another evening"] = \
        {(d["name"], d["why"]) for d in dm.search_avoid(5)} \
        == {("מנחת פודקאסט", "לא מרצה לצעירים"), ("פרופ׳ ותיק", "אקדמי מדי")} \
        and dm.search_avoid(3) == [] and dm.search_avoid(None) == []
    cur.execute("SELECT speaker_name FROM lessons WHERE mishmar_id = 5 AND speaker_name IS NOT NULL")
    want = {n.strip() for (s,) in cur.fetchall() for n in s.split("·") if n.strip()}
    cur.execute("SELECT ls.name FROM lesson_speakers ls JOIN lessons l ON l.id = ls.lesson_id "
                "WHERE l.mishmar_id = 5")
    want |= {n.strip() for (n,) in cur.fetchall()}
    people = dm.evening_people(5)
    facts["evening_people"] = people
    checks["db: evening_people = the evening's speakers and candidates, once each"] = \
        set(people) == want and len(people) == len(set(people)) and dm.evening_people(None) == []

    ok = all(checks.values())
    print(json.dumps({"ok": ok, "passed": sum(checks.values()), "total": len(checks),
                      "checks": checks, "facts": facts}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
