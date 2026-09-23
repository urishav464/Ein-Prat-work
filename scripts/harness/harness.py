#!/usr/bin/env python3
"""Drive the app on the local harness and say what every click cost — and why.

    python3 scripts/harness/harness.py serve [--root DIR] [--port 8562] [--scout ok|empty] [--rtt 0.15]
    python3 scripts/harness/harness.py scenario FILE.json [--port 8562]
    python3 scripts/harness/harness.py sweep [--port 8562]
    python3 scripts/harness/harness.py stop [--port 8562]

`serve` starts app.py (from the repo, or from --root: a scratch copy carrying a
candidate fix) on a throwaway copy of the fixture database, traced by
tracer.py. `scenario` replays a JSON list of steps in headless Chromium and
prints, per step, what happened on the server:

  {"step": "...", "app_runs": 1, "fragment_runs": 0, "dialog_runs": 0,
   "queries": 6, "by_table": {"select speakers": 2, ...},
   "runs": [{"kind": "app", "ms": 1240, "caused_by": "callback _add_candidate ← button «➕ הוסף כמועמד» app.py:1869",
             "writes": ["lesson_speakers", "speakers"], "queries": 6, "rerun_requests": [...]}],
   "flags": ["DOUBLE RUN at app.py:1234", "untriggered app run"], "wall_ms": 1650, "expect_failed": [...]}

`sweep` runs scripts/harness/sweep.json — every screen cold plus one
representative click per kind, each with the contract number it must meet
(.claude/rules/ui.md). Output is JSON lines; the last line is the summary.

Scenario steps (a list under "steps"; "user" logs in first by name):
  {"nav": "🔍 חיפוש מרצים"}                 sidebar screen
  {"click": {"text": "בנה מפה"}}            a button by its visible text (substring)
  {"click": {"key": "cand-"}}               a widget by key prefix (st-key-<key>)
  {"click": {"css": "...", "nth": 0}}       anything else
  {"press": {"key": "card-map-3-", "what": "checkbox"}}   keyboard activation — the
        only reliable way to toggle a checkbox or open a popover (clicks at the
        viewport edge are intercepted)
  {"fill": {"label": "נושא המשמר", "text": "...", "commit": "Enter"}}
  {"select": {"label": "משמר", "option": "#04"}}
  {"reload": true}                           a browser reload (an untriggered app run)
  {"wait": 1500}
Any step may carry "name", "expect": {"app_runs": 0, "queries_max": 4,
"tables": ["update tasks", "select v_tasks_full"]}, and "measure": false.

The harness never clicks 🗑 / «אפס» / «מחק»: a scenario that names one is refused.
Processes are stopped by /proc/<pid>/exe, never pkill -f (it kills the caller's
own shell, whose command line contains the pattern)."""
import argparse, json, os, signal, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CHROME = os.environ.get("MISHMAR_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
FORBIDDEN = ("🗑", "אפס", "מחק")


def trace_path(port: int) -> Path:
    return Path(f"/tmp/mishmar-trace-{port}.jsonl")


def pid_path(port: int) -> Path:
    return Path(f"/tmp/mishmar-serve-{port}.pid")


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


# ------------------------------------------------------------------ serve / stop


def _is_python(pid: int) -> bool:
    try:
        return "python" in os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return False


def stop(port: int, quiet: bool = False) -> None:
    pp = pid_path(port)
    stopped = False
    if pp.exists():
        pid = int(pp.read_text().strip() or 0)
        if pid and _is_python(pid):
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not _is_python(pid):
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, signal.SIGKILL)
            stopped = True
        pp.unlink()
    if not quiet:
        emit({"ok": True, "stopped": stopped, "port": port})


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2) as r:
            return r.read().strip() == b"ok"
    except Exception:
        return False


def serve(root: Path, port: int, scout: str, rtt: float, db: str | None) -> dict:
    stop(port, quiet=True)
    db = db or f"trace_{port}"
    r = subprocess.run([sys.executable, str(HERE / "db.py"), "fresh", db],
                       capture_output=True, text=True)
    info = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1] or "{}")
    if not info.get("ok"):
        return {"ok": False, "blocked": info.get("blocked") or r.stderr[-300:]}
    tp = trace_path(port)
    tp.write_text("")
    env = dict(os.environ, MISHMAR_ROOT=str(root), MISHMAR_PG_DSN=info["dsn"],
               MISHMAR_TRACE=str(tp), SIM_RTT=str(rtt))
    env.pop("MISHMAR_NO_CACHE", None)          # measure the real cache, not its absence
    if scout:
        env["SIM_SCOUT"] = scout
    log = open(f"/tmp/mishmar-serve-{port}.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(HERE / "run_traced.py"),
         "--server.port", str(port), "--server.headless", "true",
         "--server.fileWatcherType", "none", "--server.runOnSave", "false",
         "--browser.gatherUsageStats", "false"],
        cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pid_path(port).write_text(str(proc.pid))
    for _ in range(120):
        if _healthy(port):
            return {"ok": True, "url": f"http://localhost:{port}", "pid": proc.pid,
                    "root": str(root), "db": db, "trace": str(tp), "scout": scout or None}
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    stop(port, quiet=True)
    tail = Path(f"/tmp/mishmar-serve-{port}.log").read_text()[-400:]
    return {"ok": False, "blocked": "streamlit did not start: " + tail}


# ------------------------------------------------------------------ reading the trace


def read_events(tp: Path, offset: int) -> tuple[list[dict], int]:
    with open(tp, encoding="utf-8") as f:
        f.seek(offset)
        data = f.read()
        end = f.tell()
    out = []
    for line in data.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out, end


def _cause(pre: list[dict]) -> str:
    """Name what caused a run from the events that preceded its start."""
    trig = [e for e in pre if e["ev"] == "trigger"]
    rr = [e for e in pre if e["ev"] == "rerun_request"]
    if rr:
        e = rr[-1]
        return f"st.rerun(scope={e.get('scope')}) at app.py:{e.get('line')} in {e.get('fn')}"
    if trig:
        e = trig[-1]
        who = f"{e.get('widget')} «{e.get('label')}»" + (f" key={e['key']}" if e.get("key") else "")
        if e["how"] == "callback":
            return f"callback {e.get('fn')} ← {who} app.py:{e.get('line')}"
        return f"if-{e.get('widget')} {who} app.py:{e.get('line')} (no callback)"
    return ""


def summarize(events: list[dict]) -> dict:
    runs, pre, open_runs = [], [], []
    flags = []
    for e in events:
        ev = e["ev"]
        if ev == "run_start":
            cur = {"kind": e["kind"], "name": e["name"], "pre": pre, "events": [],
                   "t": e["t"], "first": e.get("first_in_session")}
            pre = []
            open_runs.append(cur)
            runs.append(cur)
        elif ev == "run_end":
            if open_runs:
                cur = open_runs.pop()
                cur["ms"] = e.get("ms")
                cur["status"] = e.get("status")
                cur["changed"] = e.get("changed") or []
                # a rerun request in THIS run causes the NEXT one
                pre = [x for x in cur["events"] if x["ev"] == "rerun_request"]
        elif open_runs:
            open_runs[-1]["events"].append(e)
        else:
            pre.append(e)
    out_runs = []
    by_table: dict[str, int] = {}
    for r in runs:
        evs = r["pre"] + r["events"]
        qs = [x for x in evs if x["ev"] == "query"]
        for q in qs:
            k = f"{q['verb']} {q['table']}"
            by_table[k] = by_table.get(k, 0) + 1
        cause = _cause(r["pre"])
        if not cause:
            # an `if st.button(...)` is seen DURING the run it caused
            clicked = [x for x in r["events"] if x["ev"] == "trigger" and x.get("how") == "if-button"]
            if clicked:
                cause = _cause(clicked[:1])
        if not cause and r.get("first"):
            cause = "page load: a new browser session (open, reload, or a lost session)"
        if not cause and r.get("changed"):
            c = r["changed"][0]
            cause = f"widget value changed: {c['widget']} «{c['label']}» app.py:{c['line']} (no callback)"
        writes = sorted({t for x in evs if x["ev"] == "invalidate"
                         for t in (x["tables"] if isinstance(x["tables"], list) else [x["tables"]])})
        reqs = [{"scope": x.get("scope"), "line": x.get("line"), "fn": x.get("fn"),
                 "after_write": x.get("after_write")}
                for x in r["events"] if x["ev"] == "rerun_request"]
        for q in reqs:
            if q["after_write"]:
                flags.append(f"DOUBLE RUN: write then st.rerun at app.py:{q['line']} ({q['fn']})")
        if not cause:
            cause = "untriggered (a reconnect, or the read cache's TTL expiring)"
            if r["kind"] == "app":
                flags.append("untriggered app run")
        cb_ms = sum(x.get("ms") or 0 for x in r["pre"] if x["ev"] == "callback_end")
        out_runs.append({"kind": r["kind"], "name": r["name"], "ms": r.get("ms"),
                         "callback_ms": cb_ms,
                         "status": r.get("status"), "caused_by": cause, "writes": writes,
                         "queries": len(qs), "rerun_requests": reqs})
    return {
        "app_runs": sum(1 for r in out_runs if r["kind"] == "app"),
        "fragment_runs": sum(1 for r in out_runs if r["kind"] == "fragment"),
        "dialog_runs": sum(1 for r in out_runs if r["kind"] == "dialog"),
        "queries": sum(by_table.values()),
        "by_table": dict(sorted(by_table.items(), key=lambda kv: -kv[1])),
        "server_ms": sum((r["ms"] or 0) + r["callback_ms"] for r in out_runs),
        "runs": out_runs,
        "flags": flags,
    }


def settle(tp: Path, offset: int, timeout: float = 45.0, quiet_ms: int = 700,
           grace: float = 1.5) -> list[dict]:
    """Wait until the server is idle after an action: every run that started
    has ended and nothing new arrived for `quiet_ms`. An action that causes
    no run at all (a popover opening client-side) settles after `grace`."""
    t_end = time.time() + timeout
    t0 = time.time()
    events, last_len, last_change = [], -1, time.time()
    while time.time() < t_end:
        events, _ = read_events(tp, offset)
        if len(events) != last_len:
            last_len, last_change = len(events), time.time()
        starts = sum(1 for e in events if e["ev"] == "run_start")
        ends = sum(1 for e in events if e["ev"] == "run_end")
        idle = (time.time() - last_change) * 1000 >= quiet_ms
        if events and starts == ends and idle:
            return events
        if not events and time.time() - t0 >= grace:
            return events
        time.sleep(0.1)
    return events


# ------------------------------------------------------------------ the browser


def _locator(page, spec: dict):
    if "key" in spec:
        loc = page.locator(f'[class*="st-key-{spec["key"]}"]')
        inner = spec.get("inner", "button, input, textarea, [role=checkbox], [role=combobox]")
        if inner:
            loc = loc.locator(inner)
    elif "text" in spec:
        loc = page.locator("button").filter(has_text=spec["text"])
    elif "label" in spec:
        loc = page.locator(f'[aria-label="{spec["label"]}"]')
    else:
        loc = page.locator(spec["css"])
    # a key or text also matches what sits folded inside a closed expander —
    # count only what a person could actually click
    if spec.get("visible", True):
        loc = loc.filter(visible=True)
    return loc.nth(spec.get("nth", 0))


def _body_error(page) -> str:
    body = page.inner_text("body")
    for needle in ("Traceback", "StreamlitAPIException", "DuplicateElementKey",
                   "AttributeError", "KeyError"):
        if needle in body:
            i = body.index(needle)
            return body[i:i + 200].replace("\n", " ")
    return ""


def _act(page, step: dict) -> str:
    if "nav" in step:
        label = step["nav"]
        page.locator('[data-testid="stSidebar"] label').filter(has_text=label).first.click()
        return f"nav «{label}»"
    if "click" in step:
        spec = step["click"]
        loc = _locator(page, spec)
        text = (loc.inner_text(timeout=15000) or "").strip()
        if any(f in text for f in FORBIDDEN):
            raise ValueError(f"refused: the harness never clicks «{text}»")
        loc.click(timeout=15000)
        return f"click «{text[:30] or spec}»"
    if "press" in step:
        spec = step["press"]
        what = spec.get("what", "button")
        inner = {"checkbox": "input[type=checkbox]", "button": "button"}.get(what, what)
        loc = _locator(page, {**spec, "inner": inner})
        loc.focus(timeout=15000)
        page.keyboard.press("Space" if what == "checkbox" else "Enter")
        return f"press {what} {spec}"
    if "fill" in step:
        spec = step["fill"]
        loc = _locator(page, spec) if ("key" in spec or "css" in spec) else \
            page.locator(f'[aria-label="{spec["label"]}"]').nth(spec.get("nth", 0))
        loc.fill(spec["text"], timeout=15000)
        if spec.get("commit"):
            loc.press(spec["commit"])
        return f"fill «{spec.get('label') or spec.get('key')}»"
    if "select" in step:
        spec = step["select"]
        box = page.locator(f'[aria-label*="{spec["label"]}"]').nth(spec.get("nth", 0))
        box.click(timeout=15000)
        page.locator('[role="option"]').filter(has_text=spec["option"]).first.click(timeout=15000)
        return f"select «{spec['option']}»"
    if "reload" in step:
        page.reload()
        return "reload"
    if "wait" in step:
        page.wait_for_timeout(int(step["wait"]))
        return f"wait {step['wait']}"
    raise ValueError(f"unknown step {step}")


def _login(page, url: str, user: str) -> None:
    page.goto(url, timeout=90000)
    page.locator('input[aria-label="השם שלך"]').wait_for(timeout=60000)
    page.fill('input[aria-label="השם שלך"]', user)
    page.get_by_role("button", name="כניסה").click()
    page.locator('[data-testid="stSidebar"]').wait_for(timeout=60000)


def _check(expect: dict, s: dict) -> list[str]:
    bad = []
    for k in ("app_runs", "fragment_runs", "dialog_runs"):
        if k in expect and s[k] != expect[k]:
            bad.append(f"{k} {s[k]} ≠ {expect[k]}")
    if "queries_max" in expect and s["queries"] > expect["queries_max"]:
        bad.append(f"queries {s['queries']} > {expect['queries_max']}")
    if "tables" in expect and sorted(s["by_table"]) != sorted(expect["tables"]):
        bad.append(f"tables {sorted(s['by_table'])} ≠ {sorted(expect['tables'])}")
    return bad


def run_scenario(sc: dict, port: int, browser) -> list[dict]:
    tp = trace_path(port)
    url = f"http://localhost:{port}"
    ctx = browser.new_context(viewport={"width": sc.get("width", 1500), "height": 1100})
    page = ctx.new_page()
    results = []
    try:
        offset = tp.stat().st_size
        _login(page, url, sc.get("user", "Uri"))
        settle(tp, offset)
        for i, step in enumerate(sc.get("steps", [])):
            offset = tp.stat().st_size
            t0 = time.time()
            try:
                what = _act(page, step)
            except Exception as exc:                  # a missing element is a finding too
                results.append({"scenario": sc.get("name"), "step": step.get("name") or str(step)[:60],
                                "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                break
            events = settle(tp, offset)
            s = summarize(events)
            if events:
                s["wall_ms"] = round((max(e["t"] for e in events) - t0) * 1000)
            else:
                s["wall_ms"] = 0
            err = _body_error(page)
            if step.get("measure", True):
                row = {"scenario": sc.get("name"), "step": step.get("name") or what, **s}
                if err:
                    row["page_error"] = err
                if step.get("expect"):
                    row["expect_failed"] = _check(step["expect"], s)
                results.append(row)
            elif err:
                results.append({"scenario": sc.get("name"), "step": what, "page_error": err})
    finally:
        ctx.close()
    return results


def _browser(p):
    return p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])


def scenario(files: list[str], port: int) -> int:
    from playwright.sync_api import sync_playwright
    if not _healthy(port):
        emit({"ok": False, "blocked": f"nothing is serving on port {port} — run `harness.py serve`"})
        return 1
    rc = 0
    with sync_playwright() as p:
        br = _browser(p)
        for f in files:
            sc = json.loads(Path(f).read_text(encoding="utf-8"))
            for row in run_scenario(sc, port, br):
                emit(row)
                if row.get("expect_failed") or row.get("error") or row.get("page_error"):
                    rc = 1
        br.close()
    return rc


def sweep(port: int) -> int:
    plan = json.loads((HERE / "sweep.json").read_text(encoding="utf-8"))
    from playwright.sync_api import sync_playwright
    if not _healthy(port):
        emit({"ok": False, "blocked": f"nothing is serving on port {port} — run `harness.py serve`"})
        return 1
    failed, rows = [], 0
    with sync_playwright() as p:
        br = _browser(p)
        for sc in plan:
            if "file" in sc:
                sc = {**json.loads((HERE / sc["file"]).read_text(encoding="utf-8")),
                      **{k: v for k, v in sc.items() if k != "file"}}
            for row in run_scenario(sc, port, br):
                emit(row)
                rows += 1
                if row.get("expect_failed") or row.get("error") or row.get("page_error"):
                    failed.append(f"{row.get('scenario')} / {row.get('step')}")
        br.close()
    emit({"summary": True, "steps": rows, "failed": failed})
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "scenario", "sweep", "stop"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--port", type=int, default=8562)
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--scout", default="ok", help="canned scout results: ok | empty | '' for none")
    ap.add_argument("--rtt", type=float, default=0.15)
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if a.cmd == "serve":
        res = serve(Path(a.root).resolve(), a.port, a.scout, a.rtt, a.db)
        emit(res)
        return 0 if res.get("ok") else 1
    if a.cmd == "stop":
        stop(a.port)
        return 0
    if a.cmd == "scenario":
        return scenario(a.files, a.port)
    return sweep(a.port)


if __name__ == "__main__":
    sys.exit(main())
