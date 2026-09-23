"""The Streamlit entry of the harness: app.py over the local PostgreSQL, traced.

Started by `harness.py serve`, never by hand — it sets the environment:
  MISHMAR_ROOT     the tree to run (the repo, or a scratch copy with a fix in it)
  MISHMAR_PG_DSN   the throwaway database (db.py fresh)
  MISHMAR_TRACE    where tracer.py writes its JSON lines
  SIM_RTT          simulated Supabase round-trip, seconds (default 0.15)
  SIM_SCOUT        ok | empty — canned scout results instead of the Anthropic API

Streamlit re-executes this file on every app run; everything that patches
is guarded inside tracer.install(), so it happens once per process."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get("MISHMAR_ROOT") or os.path.join(HERE, "..", ".."))
for p in (HERE, ROOT):          # ROOT first on the path: its data_manager, not the repo's
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

# never reach real services: a secrets file would give the app real Supabase
# and Anthropic credentials. The harness refuses rather than hopes.
for cand in (os.path.join(ROOT, ".streamlit", "secrets" + ".toml"),
             os.path.expanduser(os.path.join("~", ".streamlit", "secrets" + ".toml"))):
    if os.path.exists(cand):
        raise SystemExit(f"harness refuses to run: a Streamlit secrets file exists at {cand}")

import pgrest_shim                                   # noqa: E402
import data_manager as dm                            # noqa: E402
import tracer                                        # noqa: E402

tracer.install(ROOT)
dm.set_client(pgrest_shim.FakeSupabase())

_mode = os.environ.get("SIM_SCOUT")
if _mode and not getattr(tracer, "_scout_patched", False):
    tracer._scout_patched = True
    import chat_agent as _ca
    fx = os.path.join(HERE, "fixtures")
    _canned = json.load(open(os.path.join(fx, f"scout_{_mode}.json"), encoding="utf-8"))
    _map = json.load(open(os.path.join(fx, f"scout_map_{_mode}.json"), encoding="utf-8"))
    _ca.scout_map = lambda *a, **k: json.loads(json.dumps(_map))

    def _fake_scout(*a, progress=None, scout_map_result=None, **k):
        m = scout_map_result or _canned.get("map")
        on = {x["key"] for x in (m or {}).get("angles", []) if x.get("on", True)}
        if progress:
            for q in _canned.get("queries", [])[:3]:
                progress("מחפש: " + q.lstrip("🔎📄 "))
        res = json.loads(json.dumps(_canned))
        res["map"] = m
        if not res.get("fallback"):
            res["candidates"] = [c for c in res["candidates"] if c.get("angle") in on]
            res["strong"] = sum(1 for c in res["candidates"] if c["confidence"] == "high")
        return res
    _ca.scout_speakers = _fake_scout

tracer.app_run(os.path.join(ROOT, "app.py"))
