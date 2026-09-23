"""The rerun tracer: every run of the app, and what caused it, as JSON lines.

Installed by run_traced.py before app.py executes. It changes no behaviour —
it wraps and records. One line per event in $MISHMAR_TRACE:

  run_start / run_end   kind = app | fragment | dialog, name, ms, status
                        (app = one exec of app.py; fragment/dialog = a run
                        scoped to that function — `fragment_ids_this_run`)
  trigger               how = callback | if-button, with the callback's name,
                        the widget kind, its key and label, and the app.py line
                        where the widget was drawn. Callbacks run BEFORE the
                        run they cause, so a trigger precedes its run_start.
  changed               at run_end: widgets whose returned value differs from
                        the last run that drew them — how a bare widget (no
                        callback) is caught as the cause of a run.
  rerun_request         st.rerun(): scope, caller line, whether this run had
                        already written (write → st.rerun = a DOUBLE RUN)
  query                 one real round-trip through the shim: verb, table, ms
                        (a cache hit never reaches the shim, so it is absent)
  invalidate            the tables a write cleared from the read cache

A run with no trigger, no change and no rerun_request before it is
`untriggered`: a first load, a browser reconnect, or — if it is full of
queries — the read cache's TTL expiring. harness.py does that reading.

Test-only; never imported by the app."""
import functools, json, os, sys, threading, time

LOG = os.environ.get("MISHMAR_TRACE", "/tmp/mishmar-trace.jsonl")
BUTTONS = {"button", "form_submit_button", "download_button"}
# widgets whose return value is their state — tracked to find a bare trigger
VALUED = BUTTONS | {"checkbox", "toggle", "radio", "selectbox", "multiselect",
                    "segmented_control", "pills", "feedback", "text_input", "text_area",
                    "number_input", "date_input", "time_input", "slider", "select_slider",
                    "color_picker"}
# containers that can carry an on_change in 1.64 (open/close → a run when set)
CONTAINERS = {"popover", "expander", "tabs", "file_uploader", "data_editor"}

_lock = threading.Lock()
_tl = threading.local()
_installed = False
_seen: dict = {}          # session → widget identity → last value
_sessions: set = set()    # sessions that have had a run
APP = ""


def emit(ev: str, **kw) -> None:
    kw["ev"] = ev
    kw["t"] = round(time.time(), 4)
    kw["thread"] = threading.get_ident() % 100000
    line = json.dumps(kw, ensure_ascii=False, default=str)
    with _lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _app_frame(depth: int = 2):
    """The innermost frame inside app.py (or chat_panel.py): where the widget
    or st.rerun() actually sits in the app's source."""
    f = sys._getframe(depth)
    while f is not None:
        fn = f.f_code.co_filename
        if fn == APP or fn.endswith("/chat_panel.py"):
            return f.f_lineno, f.f_code.co_name
        f = f.f_back
    return None, None


def _short(v, n=40):
    s = v if isinstance(v, str) else ("" if v is None else str(v))
    return s.replace("\n", " ")[:n]


def _fp(v):
    """A comparable fingerprint of a widget's value."""
    try:
        return json.dumps(v, ensure_ascii=False, default=str, sort_keys=True)[:200]
    except Exception:
        return repr(v)[:200]


# ---------------------------------------------------------------- runs


def _session() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return (ctx.session_id if ctx else "")[:8]
    except Exception:
        return ""


def begin(kind: str, name: str) -> None:
    stack = getattr(_tl, "stack", None)
    if stack is None:
        stack = _tl.stack = []
    sid = _session()
    first = sid not in _sessions
    _sessions.add(sid)
    stack.append({"kind": kind, "name": name, "t0": time.perf_counter(),
                  "wrote": False, "values": {}, "session": sid})
    # a session's first run is a page load: the browser opened, reloaded, or
    # lost its session (Streamlit keeps none across a reload)
    emit("run_start", kind=kind, name=name, session=sid, first_in_session=first)


def end(status: str = "ok") -> None:
    stack = getattr(_tl, "stack", None) or []
    if not stack:
        return
    run = stack.pop()
    changed = []
    seen = _seen.setdefault(run["session"], {})
    for ident, (fp, label, line) in run["values"].items():
        before = seen.get(ident)
        # a button going back to False after its click is not a cause
        released = ident.split(":", 1)[0] in BUTTONS and fp == "false"
        if before is not None and before != fp and not released:
            changed.append({"widget": ident, "label": label, "line": line})
        seen[ident] = fp
    emit("run_end", kind=run["kind"], name=run["name"], status=status,
         ms=round((time.perf_counter() - run["t0"]) * 1000), changed=changed[:8])


def _current():
    stack = getattr(_tl, "stack", None) or []
    return stack[-1] if stack else None


def app_run(path: str) -> None:
    """One exec of app.py, recorded as an app run. RerunException/StopException
    pass through — they are how Streamlit ends a run early."""
    begin("app", "main")
    status = "ok"
    try:
        src = open(path, encoding="utf-8").read()
        exec(compile(src, path, "exec"), {"__name__": "__main__", "__file__": path})
    except BaseException as exc:
        status = type(exc).__name__
        raise
    finally:
        end(status)


def _scoped(kind: str, fn):
    """Wrap a fragment/dialog body: a run that Streamlit scoped to it (not the
    first draw inside an app run) is recorded as its own run."""
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    @functools.wraps(fn)
    def inner(*a, **k):
        ctx = get_script_run_ctx()
        scoped = bool(ctx is not None and getattr(ctx, "fragment_ids_this_run", None))
        cur = _current()
        # a nested draw inside a scoped run of the same kind is not a new run
        if not scoped or (cur is not None and cur["kind"] != "app"):
            return fn(*a, **k)
        begin(kind, fn.__name__)
        status = "ok"
        try:
            return fn(*a, **k)
        except BaseException as exc:
            status = type(exc).__name__
            raise
        finally:
            end(status)
    return inner


# ---------------------------------------------------------------- widgets


def _wrap_cb(cb, kind, key, label, line):
    name = getattr(cb, "__name__", None) or type(cb).__name__

    def traced(*a, **k):
        emit("trigger", how="callback", fn=name, widget=kind, key=key,
             label=_short(label), line=line)
        t0 = time.perf_counter()
        try:
            return cb(*a, **k)
        finally:
            emit("callback_end", fn=name, ms=round((time.perf_counter() - t0) * 1000))
    return traced


def _wrap_widget(kind, orig):
    @functools.wraps(orig)
    def widget(self, *a, **k):
        line, where = _app_frame()
        key = k.get("key")
        label = a[0] if a and isinstance(a[0], str) else k.get("label")
        for cbk in ("on_click", "on_change", "on_submit"):
            cb = k.get(cbk)
            if callable(cb):
                k[cbk] = _wrap_cb(cb, kind, key, label, line)
            elif cb == "rerun":
                emit("rerun_armed", widget=kind, key=key, label=_short(label), line=line)
        res = orig(self, *a, **k)
        if kind in VALUED:
            run = _current()
            ident = f"{kind}:{key}" if key else f"{kind}:{line}:{_short(label, 24)}"
            if run is not None:
                run["values"][ident] = (_fp(res), _short(label), line)
            if kind in BUTTONS and res is True and not callable(k.get("on_click")):
                emit("trigger", how="if-button", widget=kind, key=key,
                     label=_short(label), line=line, fn=where)
        return res
    return widget


# ---------------------------------------------------------------- install


def install(root: str) -> None:
    """Idempotent: Streamlit re-executes the runner on every app run, the
    patches must be applied once per process."""
    global _installed, APP
    APP = os.path.join(root, "app.py")
    if _installed:
        return
    _installed = True
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator

    for kind in sorted(VALUED | CONTAINERS):
        orig = getattr(DeltaGenerator, kind, None)
        if orig is None:
            continue
        setattr(DeltaGenerator, kind, _wrap_widget(kind, orig))
        # `st.button` is bound to the main container at import time —
        # rebind it, or every top-level widget would bypass the wrapper
        if hasattr(st, kind):
            setattr(st, kind, getattr(st._main, kind))

    _fragment = st.fragment

    def fragment(func=None, **kw):
        def deco(f):
            return _fragment(_scoped("fragment", f), **kw)
        return deco(func) if func is not None else deco
    st.fragment = fragment

    _dialog = st.dialog

    def dialog(*da, **dk):
        d = _dialog(*da, **dk)
        return lambda f: d(_scoped("dialog", f))
    st.dialog = dialog

    _rerun = st.rerun

    def rerun(*a, **k):
        line, where = _app_frame()
        run = _current()
        emit("rerun_request", scope=k.get("scope", a[0] if a else "app"), line=line, fn=where,
             in_run=run["kind"] if run else "callback",
             after_write=bool(run and run["wrote"]))
        return _rerun(*a, **k)
    st.rerun = rerun

    import data_manager as dm
    _inv = dm._invalidate

    def invalidate(tables=None):
        run = _current()
        if run is not None:
            run["wrote"] = True
        line, where = _app_frame()
        emit("invalidate", tables=sorted(tables) if tables else "ALL", line=line, fn=where)
        return _inv(tables)
    dm._invalidate = invalidate

    import pgrest_shim
    rtt = float(os.environ.get("SIM_RTT", "0.15"))
    _execute = pgrest_shim.Query.execute

    def execute(self):
        t0 = time.perf_counter()
        time.sleep(rtt)                  # Streamlit Cloud → Supabase round-trip
        try:
            return _execute(self)
        finally:
            line, where = _app_frame()
            emit("query", verb=self.verb, table=self.table,
                 ms=round((time.perf_counter() - t0) * 1000), line=line, fn=where)
    pgrest_shim.Query.execute = execute
