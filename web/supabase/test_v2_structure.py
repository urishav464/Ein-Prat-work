"""Prove the site's structure doors write exactly what the Streamlit app writes.

    python3 scripts/harness/db.py up
    python3 web/supabase/test_v2_structure.py [--walks 3] [--steps 80] [--seed 5787]

Both apps edit the same evenings, so stage 2ב's doors (v2_set_topic …
v2_remove_person in v2.sql) are TWINS of data_manager: the same slots and
clock, the same people, the same shared speaker index and outreach journal,
and the same task board — which the slots own (dm.sync_lesson_tasks).

Two throwaway copies of the harness fixture. On one, data_manager runs
through the PostgREST shim: for every step, the dm calls the Streamlit
callback makes, then dm.sync_lesson_tasks. On the other, the same step is ONE
door, called as the trainee of that evening. After every step both hold the
same evening — its row, its slots by position, their people in order, its
tasks as a sorted multiset (slot, text, status, category, due date,
generated, details, owner) — and the same index and journal.

  the fixed scenario   every path of every door, refusals included: a topic
                       closed and renamed, slots of each kind, candidates and
                       the close that removes the rest (by the row clicked —
                       «תמר» never closes «תמר כהן»), a panel closed one by
                       one, two rounds of חבורות with rooms, a slot deleted
                       (the numbers and the rounds rename), the index learning
                       a phone only when it has none, two index rows of one
                       name (nothing learned, nothing logged)
  the old states       written identically into both copies, then
                       dm.sync_lesson_tasks vs v2_private.sync_lesson_tasks:
                       orphans, a stale number, a DONE round label, a human
                       task in our wording, a slot deleted the bare way, a task
                       on a break
  the random walks     seeded; targets by position; the door's refusals are
                       predicted from the same rules and compared

Prints one JSON line; exit 1 on the first step where the two differ."""
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = Path(__file__).with_name("v2.sql")
EMAIL = "trainee.parity@example.org"
GOOGLE = {"app_metadata": {"provider": "google"}}

# the Streamlit slot editor's lists (app.LESSON_ROLES / LESSON_FORMATS) and a
# few values outside them, which the doors keep as typed
ROLES = ["", "יסודות", "ערעור", "טוויסט", "נחיתה", "טקס", "חבורות", "פאנל", "תפקיד חופשי"]
FORMATS = ["", "הרצאה", "חבורות", "פאנל", "דיבייט", "טד", "ניגון"]
TITLES = ["", "פתיחה", "פאנל הפתיחה", "חברותות בערב", "שיעור על חבורות", "  כותרת עם רווחים  ", "א" * 121]
NAMES = ["אבי כהן", "ד״ר רות לוי", 'ד"ר רות לוי', "הרב משה פרץ", "שם כפול", "תמר", "תמר כהן",
         "מוכר בלי טלפון", "מוכר עם טלפון", "  רווחים  בשם  ", "פרופ׳ דן גל", "עו״ד נועה",
         "חדש לגמרי", "", "ב" * 121]
PHONES = ["", "", "050-1111111", "052-2222222", " 053-3333333 ", "9" * 41]
LINKS = ["", "https://example.org/a", "http://example.org/b", " https://example.org/c ",
         "javascript:alert(1)", "ftp://example.org/x"]
DURATIONS = [60, 75, 90, 15, 30, 45, 4, 241]
EXTRA_ROOMS = ["", "חדר אוכל"]
EXTRA_STATUSES = ["סטטוס מומצא"]
HTTP = re.compile(r"^https?://\S+$", re.I)      # v2_private.is_http_url

# every answer each door can give — the run must have seen them all
COVERAGE = {
    ("set_topic", "ok"), ("set_topic", "invalid_text"),
    ("add_slot", "ok"), ("add_slot", "invalid_kind"), ("add_slot", "exists"), ("add_slot", "too_many"),
    ("save_slot", "ok"), ("save_slot", "invalid_duration"), ("save_slot", "invalid_text"),
    ("save_slot", "invalid_url"),
    ("delete_slot", "ok"), ("reopen", "ok"), ("reopen", "invalid"),
    ("add_person", "ok"), ("add_person", "invalid_text"), ("add_person", "invalid_room"),
    ("add_person", "invalid"), ("add_person", "closed"), ("add_person", "too_many"),
    ("edit_person", "ok"), ("edit_person", "invalid_room"), ("edit_person", "invalid_url"),
    ("set_status", "ok"), ("set_status", "invalid_status"), ("set_status", "invalid"),
    ("set_status", "closed"),
    ("remove_person", "ok"), ("remove_person", "closed"),
}


def http_url(link: str) -> bool:
    return bool(HTTP.match(link)) and len(link) <= 1000


def dsn_for(name: str) -> str:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/harness/db.py"), "fresh", name],
                       capture_output=True, text=True, cwd=ROOT)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if not out.get("ok"):
        raise SystemExit(json.dumps(out))
    return out["dsn"]


def main(argv: list[str]) -> int:
    import psycopg2
    walks = int(argv[argv.index("--walks") + 1]) if "--walks" in argv else 3
    steps = int(argv[argv.index("--steps") + 1]) if "--steps" in argv else 80
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 5787
    # `--sql PATH`: run against another copy of v2.sql — how a planted bug is
    # shown to fail this test before the test is trusted to pass
    sql_file = Path(argv[argv.index("--sql") + 1]) if "--sql" in argv else SQL

    dsn_py, dsn_sql = dsn_for("v2par_py"), dsn_for("v2par_sql")
    os.environ["MISHMAR_NO_CACHE"] = "1"             # before data_manager wraps its reads
    sys.path[:0] = [str(ROOT / "scripts/harness"), str(ROOT)]
    import logging
    import streamlit                                  # noqa: F401 — then quiet its cache logger
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    import pgrest_shim
    pgrest_shim.DSN = dsn_py
    import data_manager as dm
    dm.set_client(pgrest_shim.FakeSupabase())

    py = psycopg2.connect(dsn_py)
    sq = psycopg2.connect(dsn_sql)
    py.autocommit = sq.autocommit = True
    pc, sc = py.cursor(), sq.cursor()
    sql = sql_file.read_text(encoding="utf-8")
    for cur in (pc, sc):
        cur.execute(sql)

    def both(statement: str, args=()) -> None:
        """The same write in both copies — the old states and the index's namesakes."""
        for cur in (pc, sc):
            cur.execute(statement, args)

    # the trainee: the first one on #05 (the fixture gives it a timeline and a
    # candidate); a second evening of theirs is emptied for the topic's close
    pc.execute("""SELECT student_id FROM assignments WHERE mishmar_id = 5 ORDER BY student_id LIMIT 1""")
    me = pc.fetchone()[0]
    pc.execute("SELECT mishmar_id FROM assignments WHERE student_id = %s AND mishmar_id <> 5 ORDER BY 1", (me,))
    others = [r[0] for r in pc.fetchall()]
    e0 = others[0]
    both("DELETE FROM lessons WHERE mishmar_id = %s", (e0,))
    both("DELETE FROM tasks WHERE mishmar_id = %s AND (generated OR lesson_id IS NOT NULL)", (e0,))
    both("UPDATE mishmarim SET topic = NULL WHERE id = %s", (e0,))
    both("UPDATE students SET email = %s WHERE id = %s", (EMAIL, me))
    # the index states the rules turn on: two rows of one name, a known person
    # without a phone and one with, a titled one
    both("""INSERT INTO speakers (name, source_type, notes) VALUES
              ('שם כפול', 'original_44', 'בדיקה'), ('שם כפול', 'web_search', 'בדיקה'),
              ('מוכר בלי טלפון', 'manual', 'בדיקה'), ('מוכר עם טלפון', 'manual', 'בדיקה')""")
    both("UPDATE speakers SET contact = 'TBD' WHERE name = 'מוכר בלי טלפון'")
    both("UPDATE speakers SET contact = '03-1234567' WHERE name = 'מוכר עם טלפון'")
    both("""INSERT INTO speakers (name, title, source_type) VALUES ('רות לוי', 'ד״ר', 'original_44')
            ON CONFLICT DO NOTHING""")
    claims = json.dumps({"email": EMAIL, **GOOGLE})

    # ---- the two sides of one step

    def door(fn: str, *args):
        sc.execute("SELECT set_config('request.jwt.claims', %s, false)", (claims,))
        sc.execute("SET ROLE authenticated")
        try:
            sc.execute(f"SELECT public.{fn}({', '.join(['%s'] * len(args))})", args)
            return sc.fetchone()[0]
        finally:
            sc.execute("RESET ROLE")

    syncs: list[dict] = []
    real_sync = dm.sync_lesson_tasks

    def counted_sync(mid):
        res = real_sync(mid)
        syncs.append(res)
        return res

    dm.sync_lesson_tasks = counted_sync           # every sync the reference makes, inner ones too

    def lessons_of(mid):
        return dm.get_lessons(mid)

    def people_of(lesson_id):
        return [p for p in dm._rows(dm._t("lesson_speakers").select("*").eq("lesson_id", lesson_id)
                                    .order("id").execute())]

    def lesson(lesson_id):
        return dm._one(dm._t("lessons").select("*").eq("id", lesson_id).execute())

    def predict(op: dict) -> str:
        """The door's refusal, from the same rules, read off the Python copy."""
        kind = op["op"]
        rooms = ("", *dm.CHAVUROT_ROOMS)
        if kind == "set_topic":
            t = (op["topic"] or "").strip()
            return "invalid_text" if not t or len(t) > 200 else "ok"
        if kind == "add_slot":
            if op["kind"] not in ("lesson", "chavurot", "break", "skeleton"):
                return "invalid_kind"
            rows = lessons_of(op["mid"])
            if op["kind"] == "skeleton":
                return "exists" if rows else "ok"
            return "too_many" if len(rows) >= 20 else "ok"
        l = lesson(op["lesson"]) if "lesson" in op else None
        p = None
        if "person" in op:
            p = dm._one(dm._t("lesson_speakers").select("*").eq("id", op["person"]).execute())
            l = lesson(p["lesson_id"])
        ordinary = l and not l.get("is_break") and not dm.is_chavurot(l) and not dm.is_panel(l)
        closed = bool(ordinary and (l.get("speaker_name") or "").strip())
        if kind == "save_slot":
            if not 5 <= op["duration"] <= 240:
                return "invalid_duration"
            if l["is_break"]:
                return "ok"
            if len(op["title"].strip()) > 120 or len(op["role"].strip()) > 60 \
                    or len(op["format"].strip()) > 60 or len(op["description"].strip()) > 2000:
                return "invalid_text"
            link = op["link"].strip()
            return "invalid_url" if link and not http_url(link) else "ok"
        if kind == "delete_slot":
            return "ok"
        if kind == "reopen":
            return "ok" if ordinary else "invalid"
        if kind == "add_person":
            name, phone = op["name"].strip(), op["phone"].strip()
            if not name or len(name) > 120 or len(phone) > 40:
                return "invalid_text"
            if op["room"].strip() not in rooms:
                return "invalid_room"
            if l["is_break"]:
                return "invalid"
            if closed:
                return "closed"
            return "too_many" if len(people_of(l["id"])) >= 12 else "ok"
        if kind == "edit_person":
            if op["phone"] is not None and len(op["phone"].strip()) > 40:
                return "invalid_text"
            if op["room"] is not None and op["room"].strip() not in rooms:
                return "invalid_room"
            link = (op["link"] or "").strip()
            return "invalid_url" if op["link"] is not None and link and not http_url(link) else "ok"
        if kind == "set_status":
            if op["status"] not in dm.SPEAKER_STATUSES:
                return "invalid_status"
            if l["is_break"] or dm.is_chavurot(l):
                return "invalid"
            return "closed" if closed else "ok"
        if kind == "remove_person":
            return "closed" if closed else "ok"
        raise ValueError(kind)

    def reference(op: dict) -> dict:
        """What the Streamlit callbacks write for this step, then the sync."""
        kind = op["op"]
        res: dict = {}
        if kind == "set_topic":
            mid = op["mid"]
            closing = not (dm.get_mishmar(mid) or {}).get("topic")
            dm.set_mishmar_topic(mid, op["topic"].strip())                 # app._close_topic_clicked
            if closing:
                for t in dm.get_tasks_for_mishmar(mid):
                    if t.get("category") == "נושא" and t["status"] != "DONE":
                        dm.update_task_status(t["id"], "DONE")
                dm.create_default_timeline(mid)
        elif kind == "add_slot":
            mid = op["mid"]
            if op["kind"] == "skeleton":
                dm.create_default_timeline(mid)
            elif op["kind"] == "break":
                dm.add_break(mid, 15)
            else:                                                          # app._add_slot_clicked
                dm.add_lesson_slot(mid, 60, role="חבורות" if op["kind"] == "chavurot" else None)
        elif kind == "save_slot":
            l = lesson(op["lesson"])
            mid = l["mishmar_id"]
            if l["is_break"]:
                dm.set_lesson_duration(mid, l["id"], op["duration"])
            else:                                                          # app._lesson_edit_dialog
                title, role, fmt = op["title"].strip(), op["role"].strip(), op["format"].strip()
                dm.update_lesson(l["id"], title=title, description=op["description"].strip(),
                                 lesson_role=role, fmt=fmt)
                if dm.is_panel({**l, "title": title, "lesson_role": role, "format": fmt}):
                    if not dm.is_panel(l):
                        dm.adopt_panel_speaker(l)
                    dm.refresh_panel_speakers(l["id"])
                dm.set_lesson_duration(mid, l["id"], op["duration"])
                link = op["link"].strip()
                if link != (l.get("source_url") or ""):
                    dm.set_lesson_source(l["id"], link)
                dm.recompute_lesson_times(mid)
        elif kind == "delete_slot":
            l = lesson(op["lesson"])
            mid = l["mishmar_id"]
            res["tasks"] = dm.delete_lesson_with_tasks(mid, l["id"])["tasks"]
        elif kind == "reopen":
            l = lesson(op["lesson"])
            mid = l["mishmar_id"]
            dm.reopen_lesson_speaker(l["id"])
        elif kind == "add_person":
            l = lesson(op["lesson"])
            mid = l["mishmar_id"]
            name, phone, room = op["name"].strip(), op["phone"].strip(), op["room"].strip()
            if dm.is_chavurot(l):                                          # app._add_presenter_clicked
                dm.add_chavurot_presenter(l["id"], name, room=room or None, student_id=me)
            else:
                cid = dm.add_lesson_speaker(l["id"], name, phone=phone, student_id=me)
                if op["close"]:
                    if dm.is_panel(l):                                     # app._add_panelist_clicked
                        r = dm.close_panelist(cid, mishmar_id=mid, student_id=me)
                        res = {"closed": r["closed"], "logged": r["logged"]}
                    else:                                                  # app._add_candidate_clicked
                        r = dm.close_lesson_speaker(l["id"], name, mishmar_id=mid, student_id=me,
                                                    candidate_id=cid)
                        res = {"closed": r["closed"], "removed": r["removed"], "logged": r["logged"]}
        elif kind == "edit_person":
            p = dm._one(dm._t("lesson_speakers").select("*").eq("id", op["person"]).execute())
            mid = lesson(p["lesson_id"])["mishmar_id"]
            if op["phone"] is not None:
                dm.set_candidate_phone(p["id"], op["phone"])               # app._phone_changed
            if op["room"] is not None:
                dm.set_candidate_room(p["id"], op["room"].strip() or None)  # app._room_changed
            if op["link"] is not None:
                dm.set_candidate_source(p["id"], op["link"])               # app._source_changed
        elif kind == "set_status":
            p = dm._one(dm._t("lesson_speakers").select("*").eq("id", op["person"]).execute())
            l = lesson(p["lesson_id"])
            mid = l["mishmar_id"]
            if dm.is_panel(l):                                             # app._panelist_status_changed
                res["logged"] = dm.update_lesson_speaker_status(p["id"], op["status"], mishmar_id=mid,
                                                                student_id=me)
                dm.refresh_panel_speakers(l["id"])
            elif op["status"] == "✅ סגור":                                 # app._close_candidate
                r = dm.close_lesson_speaker(l["id"], p["name"], mishmar_id=mid, student_id=me,
                                            candidate_id=p["id"])
                res = {"closed": r["closed"], "removed": r["removed"], "logged": r["logged"]}
            else:                                                          # app._candidate_status_changed
                res["logged"] = dm.update_lesson_speaker_status(p["id"], op["status"], mishmar_id=mid,
                                                                student_id=me)
        elif kind == "remove_person":
            p = dm._one(dm._t("lesson_speakers").select("*").eq("id", op["person"]).execute())
            l = lesson(p["lesson_id"])
            mid = l["mishmar_id"]
            dm.delete_lesson_candidate(p["id"])
            if dm.is_panel(l):                                             # app._remove_panelist
                dm.refresh_panel_speakers(l["id"])
        else:
            raise ValueError(kind)
        dm.sync_lesson_tasks(mid)
        return res

    def door_call(op: dict, sq_ids: dict):
        kind = op["op"]
        if kind == "set_topic":
            return door("v2_set_topic", op["mid"], op["topic"])
        if kind == "add_slot":
            return door("v2_add_slot", op["mid"], op["kind"])
        if kind == "save_slot":
            return door("v2_save_slot", sq_ids["lesson"], op["title"], op["duration"], op["role"],
                        op["format"], op["description"], op["link"])
        if kind == "delete_slot":
            return door("v2_delete_slot", sq_ids["lesson"])
        if kind == "reopen":
            return door("v2_reopen_slot", sq_ids["lesson"])
        if kind == "add_person":
            return door("v2_add_person", sq_ids["lesson"], op["name"], op["phone"], op["room"], op["close"])
        if kind == "edit_person":
            return door("v2_edit_person", sq_ids["person"], op["phone"], op["room"], op["link"])
        if kind == "set_status":
            return door("v2_set_person_status", sq_ids["person"], op["status"])
        if kind == "remove_person":
            return door("v2_remove_person", sq_ids["person"])
        raise ValueError(kind)

    # ---- positions ↔ ids, and the snapshot both copies must agree on

    def slot_ids(cur, mid):
        cur.execute("SELECT id FROM lessons WHERE mishmar_id = %s ORDER BY slot_order, id", (mid,))
        return [r[0] for r in cur.fetchall()]

    def person_ids(cur, lesson_id):
        cur.execute("SELECT id FROM lesson_speakers WHERE lesson_id = %s ORDER BY id", (lesson_id,))
        return [r[0] for r in cur.fetchall()]

    def snapshot(cur, mids) -> dict:
        def s(v):
            return "∅" if v is None else str(v)
        snap = {}
        for mid in mids:
            cur.execute("SELECT topic, start_time FROM mishmarim WHERE id = %s", (mid,))
            ev = cur.fetchone()
            cur.execute("""SELECT id, slot_order, start_time, duration_minutes, is_break, title, description,
                                  lesson_role, format, speaker_name, speaker_status, source_url
                             FROM lessons WHERE mishmar_id = %s ORDER BY slot_order, id""", (mid,))
            ls = cur.fetchall()
            pos = {r[0]: i for i, r in enumerate(ls)}
            people = []
            for r in ls:
                cur.execute("""SELECT name, phone, status, room, source_url FROM lesson_speakers
                                WHERE lesson_id = %s ORDER BY id""", (r[0],))
                people.append([tuple(map(s, p)) for p in cur.fetchall()])
            cur.execute("""SELECT lesson_id, task_description, status, category, due_date, generated,
                                  details, student_id FROM tasks WHERE mishmar_id = %s""", (mid,))
            tasks = sorted(tuple(map(s, (pos.get(t[0], "?" if t[0] else None),) + t[1:]))
                           for t in cur.fetchall())
            snap[mid] = {"evening": tuple(map(s, ev)), "lessons": [tuple(map(s, r[1:])) for r in ls],
                         "people": people, "tasks": tasks}
        cur.execute("""SELECT name, title, source_type, contact, notes, status, expertise_topics,
                              verification_url, lesson_fit, region, domains FROM speakers""")
        snap["index"] = sorted(tuple(map(s, r)) for r in cur.fetchall())
        cur.execute("""SELECT s.name, o.mishmar_id, o.student_id, o.status, o.note
                         FROM speaker_outreach o JOIN speakers s ON s.id = o.speaker_id ORDER BY o.id""")
        snap["journal"] = [tuple(map(s, r)) for r in cur.fetchall()]
        return snap

    def diff(a: dict, b: dict) -> list:
        out = []
        for k in a:
            if a[k] == b.get(k):
                continue
            if isinstance(a[k], dict):
                for kk in a[k]:
                    if a[k][kk] != b[k].get(kk):
                        aa, bb = a[k][kk], b[k].get(kk)
                        if isinstance(aa, list):
                            only_py = [x for x in aa if x not in bb][:6]
                            only_sql = [x for x in bb if x not in aa][:6]
                            out.append({"where": f"{k}.{kk}", "python_only": only_py, "sql_only": only_sql,
                                        "lengths": [len(aa), len(bb)]})
                        else:
                            out.append({"where": f"{k}.{kk}", "python": aa, "sql": bb})
            else:
                aa, bb = a[k], b.get(k)
                out.append({"where": k, "python_only": [x for x in aa if x not in bb][:6],
                            "sql_only": [x for x in bb if x not in aa][:6]})
        return out

    mids = [5, e0]
    log: list[dict] = []
    fail: dict = {}

    def resolve(op: dict) -> tuple[dict, dict] | None:
        """Positions → ids, in each copy. None when the position no longer exists."""
        py_ids, sq_ids = {}, {}
        if "slot" in op:
            mid, i = op["slot"]
            a, b = slot_ids(pc, mid), slot_ids(sc, mid)
            if i >= len(a):
                return None
            py_ids["lesson"], sq_ids["lesson"] = a[i], b[i]
        if "who" in op:
            mid, i, j = op["who"]
            a, b = slot_ids(pc, mid), slot_ids(sc, mid)
            if i >= len(a):
                return None
            pa, pb = person_ids(pc, a[i]), person_ids(sc, b[i])
            if j >= len(pa):
                return None
            py_ids["person"], sq_ids["person"] = pa[j], pb[j]
        return py_ids, sq_ids

    def step(op: dict, label: str) -> bool:
        ids = resolve(op)
        if ids is None:
            return True                                    # nothing there any more — not a step
        py_ids, sq_ids = ids
        ref_op = {**op, **py_ids}
        want = predict(ref_op)
        got = door_call(op, sq_ids)
        status = (got or {}).get("status")
        entry = {"step": label, "op": {k: v for k, v in op.items()}, "want": want, "got": status}
        if status != want:
            fail.update(entry, why="the door's answer is not the predicted one", door=got)
            return False
        if want == "ok":
            syncs.clear()
            res = reference(ref_op)
            total = {k: sum(s_.get(k, 0) for s_ in syncs) for k in ("created", "removed", "adopted",
                                                                       "completed", "renamed")}
            door_res = got.get("result") or {}
            if door_res.get("sync") != total:
                fail.update(entry, why="sync counts differ", python=total, sql=door_res.get("sync"))
                return False
            for k in ("closed", "removed", "logged", "tasks"):
                if k in res and res[k] != door_res.get(k):
                    fail.update(entry, why=f"result.{k} differs", python=res[k], sql=door_res.get(k))
                    return False
            # the door's answer is the evening as v2_workfile shows it now
            sc.execute("RESET ROLE")
        a, b = snapshot(pc, mids), snapshot(sc, mids)
        if a != b:
            fail.update(entry, why="the databases differ", diff=diff(a, b))
            return False
        log.append(entry)
        return True

    def legacy(statement: str, label: str) -> bool:
        """An old state written into both copies, then both reconcilers."""
        for cur in (pc, sc):
            cur.execute(statement)
        for mid in mids:
            a = real_sync(mid)
            sc.execute("SELECT v2_private.sync_lesson_tasks(%s)", (mid,))
            b = sc.fetchone()[0]
            if a != b:
                fail.update(step=label, why="sync counts differ", python=a, sql=b)
                return False
        x, y = snapshot(pc, mids), snapshot(sc, mids)
        if x != y:
            fail.update(step=label, why="the databases differ after the sync", diff=diff(x, y))
            return False
        log.append({"step": label, "got": "ok"})
        return True

    checks: dict[str, bool] = {}
    # the constants the SQL spells out once
    sc.execute("SELECT v2_private.rooms(), v2_private.speaker_statuses(), v2_private.round_suffix(2, 2)")
    rooms, statuses, suffix = sc.fetchone()
    checks["constants: the rooms, the statuses, a round's suffix are dm's"] = \
        tuple(rooms) == dm.CHAVUROT_ROOMS and tuple(statuses) == dm.SPEAKER_STATUSES \
        and suffix == dm.round_suffix(2, 2)
    names_in = NAMES + ["ד״ר", "  ד״ר  רות  ", "הרבנית שירה", "פרופסור אבי", "דר' יוסי", "עו\"ד דנה", "x"]
    sc.execute("SELECT n, (v2_private.split_title(n)).title, (v2_private.split_title(n)).name, "
               "v2_private.norm_name(n) FROM unnest(%s::text[]) AS n", (names_in,))
    wrong = [r for r in sc.fetchall()
             if (r[1], r[2]) != dm.split_title(r[0]) or r[3] != dm.normalize_name(r[0])]
    checks["twins: split_title and normalize_name agree on every name"] = not wrong
    texts = ["סגירת מרצה — שיעור 3", "דף מקורות — שיעור 12", "מי מעביר את התוכן — חבורות — סבב ב׳",
             "  דפי מקורות למעבירי החבורות — סבב א׳ ", "סידור כיתת שבייד", "משימה רגילה", "",
             "חלוקת חללים למעבירי החבורות"]
    sc.execute("SELECT t, v2_private.base_slot_text(t), v2_private.rename_key(t) FROM unnest(%s::text[]) AS t",
               (texts,))
    wrong = [r for r in sc.fetchall() if (r[1], r[2]) != (dm._base_slot_text(r[0]), dm._rename_key(r[0]))]
    checks["twins: base_slot_text and rename_key agree"] = not wrong

    # ---- the fixed scenario: every path of every door
    E = e0
    fixed = [
        {"op": "set_topic", "mid": E, "topic": "   "},
        {"op": "set_topic", "mid": E, "topic": "  נושא בדיקה — מה נשאר מאיתנו  "},
        {"op": "set_topic", "mid": E, "topic": "נושא בדיקה — שם אחר"},
        {"op": "add_slot", "mid": E, "kind": "skeleton"},
        {"op": "add_slot", "mid": E, "kind": "סוג מומצא"},
        {"op": "add_slot", "mid": E, "kind": "lesson"},
        {"op": "add_slot", "mid": E, "kind": "chavurot"},
        {"op": "add_slot", "mid": E, "kind": "break"},
        {"op": "add_person", "slot": (E, 0), "name": "אבי כהן", "phone": "050-1111111", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "שם כפול", "phone": "", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "מוכר בלי טלפון", "phone": "052-2222222", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "מוכר עם טלפון", "phone": "053-3333333", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "", "phone": "", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "x", "phone": "", "room": "חדר אוכל", "close": False},
        {"op": "set_status", "who": (E, 0, 0), "status": "📩 נשלחה פנייה"},
        {"op": "set_status", "who": (E, 0, 1), "status": "📩 נשלחה פנייה"},
        {"op": "set_status", "who": (E, 0, 0), "status": "סטטוס מומצא"},
        {"op": "edit_person", "who": (E, 0, 0), "phone": "050-9999999", "room": None, "link": None},
        {"op": "edit_person", "who": (E, 0, 1), "phone": "051-0000000", "room": None, "link": None},
        {"op": "set_status", "who": (E, 0, 2), "status": "✅ סגור"},
        {"op": "add_person", "slot": (E, 0), "name": "מאוחר מדי", "phone": "", "room": "", "close": False},
        {"op": "remove_person", "who": (E, 0, 0)},
        {"op": "set_status", "who": (E, 0, 0), "status": "📩 נשלחה פנייה"},
        {"op": "edit_person", "who": (E, 0, 0), "phone": "", "room": None, "link": None},
        {"op": "reopen", "slot": (E, 0)},
        {"op": "add_person", "slot": (E, 0), "name": "תמר כהן", "phone": "", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 0), "name": "תמר", "phone": "054-0000000", "room": "", "close": True},
        # the second lesson becomes a panel; its people close one by one
        {"op": "save_slot", "slot": (E, 2), "title": "פאנל הפתיחה", "duration": 90, "role": "",
         "format": "פאנל", "description": "שלושה קולות", "link": "https://example.org/sheet"},
        {"op": "add_person", "slot": (E, 2), "name": "ד״ר רות לוי", "phone": "054-4444444", "room": "", "close": True},
        {"op": "add_person", "slot": (E, 2), "name": "הרב משה פרץ", "phone": "", "room": "", "close": False},
        {"op": "add_person", "slot": (E, 2), "name": "פרופ׳ דן גל", "phone": "", "room": "", "close": False},
        {"op": "set_status", "who": (E, 2, 1), "status": "✅ סגור"},
        {"op": "set_status", "who": (E, 2, 2), "status": "❌ לא יכול/ה"},
        {"op": "remove_person", "who": (E, 2, 0)},
        {"op": "reopen", "slot": (E, 2)},
        # the first lesson (closed: תמר) becomes a panel, keeps her, and goes back
        {"op": "save_slot", "slot": (E, 0), "title": "", "duration": 75, "role": "", "format": "פאנל",
         "description": "", "link": ""},
        {"op": "save_slot", "slot": (E, 0), "title": "", "duration": 75, "role": "", "format": "",
         "description": "", "link": ""},
        {"op": "save_slot", "slot": (E, 0), "title": "", "duration": 4, "role": "", "format": "",
         "description": "", "link": ""},
        {"op": "save_slot", "slot": (E, 0), "title": "", "duration": 75, "role": "", "format": "",
         "description": "", "link": "javascript:alert(1)"},
        {"op": "save_slot", "slot": (E, 0), "title": "א" * 121, "duration": 75, "role": "", "format": "",
         "description": "", "link": ""},
        # two rounds of חבורות: the skeleton's (slot 6) and the one added (slot 8)
        {"op": "add_person", "slot": (E, 6), "name": "מעביר א", "phone": "", "room": "בית מדרש", "close": False},
        {"op": "add_person", "slot": (E, 6), "name": "מעביר ב", "phone": "", "room": "כיתת שבייד", "close": True},
        {"op": "add_person", "slot": (E, 8), "name": "מעביר ג", "phone": "", "room": "כיתת שבייד", "close": False},
        {"op": "add_person", "slot": (E, 8), "name": "מעביר ד", "phone": "", "room": "ספריית שבייד", "close": False},
        {"op": "edit_person", "who": (E, 6, 0), "phone": None, "room": "כיתת בית מדרש",
         "link": "https://example.org/p1"},
        {"op": "edit_person", "who": (E, 6, 1), "phone": None, "room": None, "link": "https://example.org/p2"},
        {"op": "edit_person", "who": (E, 6, 1), "phone": None, "room": "חדר אוכל", "link": None},
        {"op": "edit_person", "who": (E, 6, 1), "phone": None, "room": None, "link": "ftp://example.org/x"},
        {"op": "set_status", "who": (E, 6, 0), "status": "✅ סגור"},
        {"op": "reopen", "slot": (E, 6)},
        {"op": "remove_person", "who": (E, 8, 0)},
        {"op": "delete_slot", "slot": (E, 8)},          # one round left: the labels lose «— סבב»
        {"op": "delete_slot", "slot": (E, 0)},          # the lessons renumber: «שיעור 2» → «שיעור 1»
        {"op": "save_slot", "slot": (E, 0), "title": "", "duration": 45, "role": "", "format": "",
         "description": "", "link": ""},              # a break: its duration only
        {"op": "add_person", "slot": (E, 0), "name": "בהפסקה", "phone": "", "room": "", "close": False},
        {"op": "set_status", "who": (E, 0, 0), "status": "✅ סגור"},
        {"op": "delete_slot", "slot": (E, 0)},
        # the fixture's own evening: its candidate, closed, then a change of mind
        {"op": "set_status", "who": (5, 0, 0), "status": "📩 נשלחה פנייה"},
        {"op": "add_person", "slot": (5, 0), "name": "חדש לגמרי", "phone": " 055-5555555 ", "room": "", "close": False},
        {"op": "set_status", "who": (5, 0, 1), "status": "✅ סגור"},
        {"op": "reopen", "slot": (5, 0)},
        {"op": "set_topic", "mid": 5, "topic": "נושא בדיקה — גבולות הסמכות, מחדש"},
    ]
    for n, op in enumerate(fixed):
        if not step(op, f"fixed #{n}"):
            break
    # twelve on a fresh lesson, then one too many; twenty rows, then one too many
    if not fail and step({"op": "add_slot", "mid": E, "kind": "lesson"}, "fixed: a lesson for the crowd"):
        last = len(slot_ids(pc, E)) - 1
        for n in range(13):
            if not step({"op": "add_person", "slot": (E, last), "name": f"מועמד {n}", "phone": "", "room": "",
                         "close": False}, f"fixed: crowd #{n}"):
                break
    if not fail:
        for n in range(21):
            if not step({"op": "add_slot", "mid": E, "kind": "break" if n % 3 else "lesson"}, f"fixed: rows #{n}"):
                break
    checks["the fixed scenario: every step the same in both"] = not fail

    # ---- old states, then both reconcilers
    if not fail:
        olds = [
            ("an orphan of ours (its slot deleted the bare way)",
             f"""UPDATE tasks SET lesson_id = NULL WHERE id = (SELECT t.id FROM tasks t JOIN lessons l ON l.id = t.lesson_id
                    WHERE t.mishmar_id = {E} AND t.generated AND t.status <> 'DONE'
                    ORDER BY l.slot_order, t.task_description LIMIT 1)"""),
            ("a stale number", f"""UPDATE tasks SET task_description = 'דף מקורות — שיעור 7'
                    WHERE id = (SELECT t.id FROM tasks t JOIN lessons l ON l.id = t.lesson_id
                    WHERE t.mishmar_id = {E} AND t.generated AND t.task_description LIKE 'דף מקורות — שיעור %'
                    ORDER BY l.slot_order LIMIT 1)"""),
            ("a DONE round label with one round left", f"""UPDATE tasks SET task_description = task_description || ' — סבב א׳',
                    status = 'DONE' WHERE id = (SELECT t.id FROM tasks t JOIN lessons l ON l.id = t.lesson_id
                    WHERE t.mishmar_id = {E} AND t.generated AND t.task_description = 'מי מעביר את התוכן — חבורות'
                    ORDER BY l.slot_order LIMIT 1)"""),
            ("a human task in our wording", f"""INSERT INTO tasks (mishmar_id, task_description, status, lesson_id, generated)
                    SELECT {E}, 'סגירת מרצה — שיעור 1', 'TO DO', l.id, false FROM lessons l
                     WHERE l.mishmar_id = {E} AND NOT l.is_break ORDER BY l.slot_order LIMIT 1"""),
            ("a human task, our wording, no slot", f"""INSERT INTO tasks (mishmar_id, task_description, status, generated)
                    VALUES ({E}, 'דף מקורות — שיעור 2', 'TO DO', false)"""),
            ("a slot deleted the bare way", f"""DELETE FROM lessons WHERE id = (SELECT l.id FROM lessons l
                    WHERE l.mishmar_id = {E} AND NOT l.is_break ORDER BY l.slot_order LIMIT 1)"""),
            ("one of ours on a break", f"""UPDATE tasks SET lesson_id = (SELECT l.id FROM lessons l WHERE l.mishmar_id = {E}
                    AND l.is_break ORDER BY l.slot_order LIMIT 1)
                    WHERE id = (SELECT t.id FROM tasks t JOIN lessons l ON l.id = t.lesson_id
                    WHERE t.mishmar_id = {E} AND t.generated AND t.status <> 'DONE'
                    ORDER BY l.slot_order DESC, t.task_description LIMIT 1)"""),
            ("two orphans of one wording", f"""INSERT INTO tasks (mishmar_id, task_description, status, generated)
                    VALUES ({E}, 'סגירת מרצה — שיעור 2', 'TO DO', true), ({E}, 'סגירת מרצה — שיעור 2', 'TO DO', true),
                           ({E}, 'סידור כיתת שבייד', 'DONE', true)"""),
        ]
        for label, statement in olds:
            if not legacy(statement, f"old state: {label}"):
                break
    # old states the clock and a panel's adoption read, then the doors that read them:
    # a break and a lesson with no duration (the clock's defaults, 30 and 75);
    # a lesson closed by a name with no candidate row behind it, and one closed
    # by a candidate whose row is not ✅ — each then made a panel
    if not fail:
        both(f"""UPDATE lessons SET duration_minutes = NULL WHERE id IN (
                   (SELECT id FROM lessons WHERE mishmar_id = {E} AND is_break ORDER BY slot_order LIMIT 1),
                   (SELECT id FROM lessons WHERE mishmar_id = {E} AND NOT is_break ORDER BY slot_order DESC LIMIT 1))""")
        step({"op": "delete_slot", "slot": (E, len(slot_ids(pc, E)) - 1)}, "old state: no durations, then a reflow")
    plain = [i for i, l in enumerate(dm.get_lessons(E))
             if not l["is_break"] and not dm.is_chavurot(l) and not dm.is_panel(l)]
    checks["the old states: there are plain lessons left to make panels of"] = len(plain) > 1
    if not fail and plain:
        for cur in (pc, sc):
            cur.execute("DELETE FROM lesson_speakers WHERE lesson_id = %s", (slot_ids(cur, E)[plain[0]],))
            cur.execute("UPDATE lessons SET speaker_name = 'מרצה ותיק בלי שורה' WHERE id = %s",
                        (slot_ids(cur, E)[plain[0]],))
        step({"op": "save_slot", "slot": (E, plain[0]), "title": "", "duration": 75, "role": "",
              "format": "פאנל", "description": "", "link": ""}, "old state: closed with no row, made a panel")
    if not fail and len(plain) > 1:
        for cur in (pc, sc):
            l2 = slot_ids(cur, E)[plain[1]]
            cur.execute("INSERT INTO lesson_speakers (lesson_id, name, status) VALUES (%s, 'מועמד לא סגור', "
                        "'📩 נשלחה פנייה')", (l2,))
            cur.execute("UPDATE lessons SET speaker_name = 'מועמד לא סגור' WHERE id = %s", (l2,))
        step({"op": "save_slot", "slot": (E, plain[1]), "title": "", "duration": 60, "role": "פאנל",
              "format": "", "description": "", "link": ""}, "old state: closed, its row not ✅, made a panel")
    checks["the old states: both reconcilers agree"] = not fail

    # ---- the random walks
    def random_op(rnd: random.Random) -> dict:
        mid = rnd.choice(mids)
        n_slots = len(slot_ids(pc, mid))
        kind = rnd.choices(["add_person", "set_status", "edit_person", "remove_person", "save_slot",
                            "add_slot", "delete_slot", "reopen", "set_topic"],
                           weights=[26, 16, 10, 8, 15, 8, 6, 6, 5])[0]
        i = rnd.randrange(max(n_slots, 1)) if rnd.random() < 0.97 else n_slots + 3
        j = rnd.randrange(4)
        if kind == "add_person":
            return {"op": kind, "slot": (mid, i), "name": rnd.choice(NAMES), "phone": rnd.choice(PHONES),
                    "room": rnd.choice([*dm.CHAVUROT_ROOMS, *EXTRA_ROOMS]), "close": rnd.random() < 0.3}
        if kind == "set_status":
            return {"op": kind, "who": (mid, i, j),
                    "status": rnd.choice([*dm.SPEAKER_STATUSES, *EXTRA_STATUSES])}
        if kind == "edit_person":
            return {"op": kind, "who": (mid, i, j),
                    "phone": rnd.choice([None, *PHONES]),
                    "room": rnd.choice([None, *dm.CHAVUROT_ROOMS, *EXTRA_ROOMS]),
                    "link": rnd.choice([None, *LINKS])}
        if kind == "remove_person":
            return {"op": kind, "who": (mid, i, j)}
        if kind == "save_slot":
            return {"op": kind, "slot": (mid, i), "title": rnd.choice(TITLES),
                    "duration": rnd.choice(DURATIONS), "role": rnd.choice(ROLES),
                    "format": rnd.choice(FORMATS), "description": rnd.choice(["", "תיאור", "  תיאור  "]),
                    "link": rnd.choice(LINKS)}
        if kind == "add_slot":
            return {"op": kind, "mid": mid, "kind": rnd.choice(["lesson", "chavurot", "break", "skeleton"])}
        if kind in ("delete_slot", "reopen"):
            return {"op": kind, "slot": (mid, i)}
        return {"op": kind, "mid": mid, "topic": rnd.choice(["נושא אקראי", "", "נושא אקראי שני"])}

    walked = 0
    if not fail:
        for w in range(walks):
            rnd = random.Random(seed + w)
            for n in range(steps):
                if not step(random_op(rnd), f"walk {w} #{n}"):
                    break
                walked += 1
            if fail:
                break
    checks[f"the random walks: {walks} × {steps} steps the same in both"] = not fail
    seen = {(e["op"]["op"], e["got"]) for e in log if "op" in e}
    unseen = sorted(COVERAGE - seen)
    checks["coverage: every answer of every door was given at least once"] = not unseen

    print(json.dumps({"ok": all(checks.values()), "checks": checks, "steps": len(log),
                      **({"never_seen": unseen} if unseen else {}),
                      "walked": walked, "evenings": mids, "trainee": me,
                      **({"first_difference": fail} if fail else {})}, ensure_ascii=False, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
