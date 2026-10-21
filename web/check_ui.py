"""The v2 prototype in a real browser — two builds, every screen, one JSON line.

    python3 web/check_ui.py [--shots DIR] [--under PATH]

Needs `npm install` done in web/ and the harness's Python Playwright (the same
pre-installed Chromium as scripts/harness/). Builds the app twice:

  demo  no Supabase configured → the bundled demo data (names replaced)
  auth  pointed at a MOCK Supabase host that does not exist; every request the
        browser sends it is answered here (route interception), so the
        signed-in code path runs for real with no account and no network

and checks, at 390px and 1500px:

  demo  Hebrew + RTL, no sideways scroll, the hero and its four-step stepper,
        a ✓ redrawn within a frame, no markdown markers on screen
  auth  signed out → «כניסה עם Google» asks for provider=google with PKCE,
        and «מדיניות פרטיות» opens privacy.html — static, nothing from elsewhere;
        a stored session → exactly ONE rpc/v2_my_home, carrying the user's
        token; ✓ redrawn within a frame, then ONE v2_set_task_status naming
        that task, and undo saves «IN PROGRESS»; a failed save puts the task
        back and says so; late tasks (made late against today) folded one
        <details> per Mishmar in date order, phases inside, the hero's own late
        task kept out; not_linked / wrong_provider / error screens, not_linked
        with a working link to the demo; «התנתקות» → back to the sign-in
        screen; the instructor → the trainees to choose from, ONE
        rpc/v2_home_as for the one picked, that trainee's home under the
        instructor's note, a ✓ redrawn with NO save sent, and back to the list

Every build is served under a sub-path — /mishmar/, as GitHub Pages serves it
(--under to change) — so every link, icon and the manifest must be relative to pass. Three more builds check the settings as a
person pastes them: with quotes, a space and «/rest/v1/» they still sign in;
a URL that is not one gets a screen naming the setting (never a blank page)
with the demo one tap away; and a secret key — a service_role JWT or
sb_secret_ — fails the build itself.

Exit 1 on any failed check. Screenshots land in --shots (default: a temp dir)."""
import base64
import functools
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WEB = Path(__file__).resolve().parent
CHROME = os.environ.get("MISHMAR_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
MOCK = "https://mock-project.supabase.invalid"
ANON = "sb_publishable_mock_key_for_tests"
WIDTHS = (390, 1500)


def build(out: Path, url: str, key: str, must_fail: bool = False) -> str:
    """Build with these two settings. Returns the build's error text when it
    failed and was expected to; a surprise either way stops the run."""
    env = dict(os.environ, VITE_SUPABASE_URL=url, VITE_SUPABASE_ANON_KEY=key)
    r = subprocess.run(["npx", "vite", "build", "--outDir", str(out), "--emptyOutDir"],
                       cwd=WEB, env=env, capture_output=True, text=True)
    if bool(r.returncode) != must_fail:
        raise SystemExit(json.dumps({"ok": False, "build": (r.stdout + r.stderr)[-800:],
                                     "expected_failure": must_fail}))
    return r.stdout + r.stderr if must_fail else ""


def serve(root: Path, under: str = "mishmar") -> str:
    """Serve the build under a sub-path (http://…/v2), the harder case: every
    link, asset and icon must be relative for it to work, and then the site's
    root works too."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    www = Path(tempfile.mkdtemp(prefix="v2www-"))
    (www / under).symlink_to(root, target_is_directory=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(www)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/{under}"


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def session() -> dict:
    now = int(time.time())
    user = {"id": "00000000-0000-4000-8000-000000000001", "aud": "authenticated",
            "role": "authenticated", "email": "trainee.test@example.org",
            "app_metadata": {"provider": "google"}, "user_metadata": {},
            "created_at": "2026-10-01T00:00:00Z"}
    token = ".".join([b64({"alg": "HS256", "typ": "JWT"}),
                      b64({"sub": user["id"], "email": user["email"], "role": "authenticated",
                           "aud": "authenticated", "exp": now + 3600, "iat": now,
                           "app_metadata": user["app_metadata"]}), "c2ln"])
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600,
            "expires_at": now + 3600, "refresh_token": "mock-refresh", "user": user}


# ---------------------------------------------------------------- the demo build

FACTS = """() => {
  const q = (s, r = document) => [...r.querySelectorAll(s)];
  const late = q('details').filter(d => d.querySelector('summary')?.textContent.includes('באיחור'));
  const hero = q('section').find(s => s.querySelector('ol[aria-label="שלבי הבנייה"]'));
  const loaded = fam => [...document.fonts].filter(f => f.family.replace(/["']/g, '') === fam && f.status === 'loaded').length;
  const taps = q('button[aria-label]').map(b => b.getBoundingClientRect()).filter(r => r.width > 0);
  return {
    dir: document.documentElement.dir, lang: document.documentElement.lang,
    bodyDirection: getComputedStyle(document.body).direction,
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    h1: document.querySelector('h1')?.textContent,
    h2: q('h2').map(e => e.textContent.trim()),
    banner: q('[role=note]').some(n => n.textContent.includes('מצב הדגמה')),
    lateGroups: late.map(d => ({
      summary: d.querySelector('summary').textContent.replace(/\\s+/g, ' ').trim(),
      open: d.open,
      phases: q(':scope > div > div > p.mb-2', d).map(p => p.textContent.replace(/\\s+/g, ' ').trim()),
    })),
    hero: hero ? hero.querySelector('span')?.textContent : null,
    stepper: hero ? q('ol[aria-label="שלבי הבנייה"] > li', hero).length : 0,
    heroRight: hero ? Math.round(window.innerWidth - hero.getBoundingClientRect().right) : null,
    fontsLoaded: {Assistant: loaded('Assistant'), Rubik: loaded('Rubik')},
    h1Font: getComputedStyle(document.querySelector('h1')).fontFamily.split(',')[0],
    minTap: taps.length ? Math.round(Math.min(...taps.map(r => Math.min(r.width, r.height)))) : null,
    rawMarkdown: /\\*\\(|\\)\\*|`/.test(document.body.innerText),
  };
}"""

TICK = """async () => {
  const hero = [...document.querySelectorAll('section')].find(s => s.querySelector('ol[aria-label="שלבי הבנייה"]'));
  const heading = () => ([...hero.querySelectorAll('p')].find(p => p.textContent.startsWith('המשימות של שלב'))?.textContent ?? '');
  const doneHead = () => ([...document.querySelectorAll('summary')].find(s => s.textContent.includes('הושלמו'))?.textContent ?? '');
  const btn = hero.querySelector('button[aria-label^="סמן שבוצע"]:not([disabled])');
  if (!btn) return null;
  const label = btn.getAttribute('aria-label');
  const before = {heading: heading(), done: doneHead()};
  const t0 = performance.now();
  btn.click();
  await new Promise(r => requestAnimationFrame(() => r()));
  const ms = performance.now() - t0;
  return {before, after: {heading: heading(), done: doneHead()}, ms: Math.round(ms),
          gone: ![...hero.querySelectorAll('button')].some(b => b.getAttribute('aria-label') === label),
          label, hero: hero.querySelector('span').textContent};
}"""


def check_demo(browser, base: str, shots: Path, checks: dict, facts: dict) -> None:
    for w in WIDTHS:
        ctx = browser.new_context(viewport={"width": w, "height": 900}, locale="he-IL")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(f"{base}/?demo")
        page.wait_for_selector("h1")
        page.evaluate("document.fonts.ready.then(() => true)")
        f = page.evaluate(FACTS)
        page.screenshot(path=str(shots / f"v2-demo-{w}.png"), full_page=True)
        tick = page.evaluate(TICK)
        # a folded late group opens on a tap
        toggled = page.evaluate("""() => {
          const d = [...document.querySelectorAll('details')].find(d => !d.open && d.textContent.includes('באיחור'));
          if (!d) return null;
          d.querySelector('summary').click();
          return d.open;
        }""")
        # the install pieces, fetched the way the browser resolves them: the
        # manifest relative to the page, its icons relative to the manifest
        pwa = page.evaluate("""async () => {
          const href = document.querySelector('link[rel=manifest]').href;
          const r = await fetch(href);
          if (!r.ok) return {manifest: r.status};
          const m = await r.json();
          const icons = await Promise.all(m.icons.map(async i =>
            (await fetch(new URL(i.src, href))).status));
          const start = (await fetch(new URL(m.start_url, href))).status;
          return {manifest: r.status, icons, start};
        }""")
        f.update(tick=tick, lateToggle=toggled, errors=errors, pwa=pwa)
        facts[f"demo@{w}"] = f
        checks[f"demo@{w}: manifest, icons and start page load under a sub-path"] = \
            pwa.get("manifest") == 200 and pwa.get("start") == 200 \
            and bool(pwa.get("icons")) and all(s == 200 for s in pwa["icons"])
        k = f"demo@{w}: "
        checks[k + "Hebrew, RTL"] = f["dir"] == "rtl" and f["lang"] == "he" and f["bodyDirection"] == "rtl"
        checks[k + "no sideways scroll"] = f["overflowX"] <= 0
        checks[k + "demo banner"] = f["banner"]
        checks[k + "hero + 4-step stepper"] = bool(f["hero"]) and f["stepper"] == 4
        # the demo's own data may have nothing late on its as_of date — then the
        # section must be absent, not an empty heading (the grouping itself is
        # checked on the auth build, with tasks made late against today)
        checks[k + "late section only when something is late"] = \
            bool(f["lateGroups"]) == any("עבר התאריך" in h for h in f["h2"])
        checks[k + "✓ redrawn within a frame"] = bool(tick) and tick["gone"] \
            and tick["after"]["heading"] != tick["before"]["heading"] \
            and tick["after"]["done"] != tick["before"]["done"] and tick["ms"] < 100
        checks[k + "no markdown markers on screen"] = not f["rawMarkdown"]
        checks[k + "no page errors"] = not errors
        ctx.close()


# ---------------------------------------------------------------- the auth build

class MockSupabase:
    """Answers the browser's calls to the mock host; records what it was asked."""

    def __init__(self, rpc_status: int = 200, rpc_body: dict | None = None, save_status: int = 200,
                 as_body: dict | None = None, wf_body: dict | None = None):
        self.rpc_status, self.rpc_body = rpc_status, rpc_body or {}
        self.save_status = save_status
        self.as_body = as_body or {"status": "forbidden"}
        self.wf_body = wf_body
        self.calls: list[dict] = []

    def __call__(self, route, request):
        u = urlparse(request.url)
        try:
            body = json.loads(request.post_data or "null")
        except ValueError:
            body = request.post_data
        self.calls.append({"path": u.path, "query": u.query, "method": request.method,
                           "auth": request.headers.get("authorization"),
                           "apikey": request.headers.get("apikey"), "body": body})
        if u.path == "/auth/v1/authorize":
            return route.fulfill(status=200, content_type="text/html", body="<p>mock Google</p>")
        if u.path == "/rest/v1/rpc/v2_my_home":
            return route.fulfill(status=self.rpc_status, content_type="application/json",
                                 body=json.dumps(self.rpc_body, ensure_ascii=False))
        if u.path == "/rest/v1/rpc/v2_home_as":
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(self.as_body, ensure_ascii=False))
        # the workfile's doors answer like v2.sql does: the evening asked for,
        # and the task as the database would store it
        b = body if isinstance(body, dict) else {}
        answer = None
        if u.path == "/rest/v1/rpc/v2_workfile":
            answer = json.loads(json.dumps(self.wf_body)) if self.wf_body else {"status": "forbidden"}
            if self.wf_body:
                answer["mishmar"]["id"] = b.get("p_mishmar_id")
        elif u.path == "/rest/v1/rpc/v2_add_task":
            answer = {"status": "ok", "task": {
                "id": 9999, "mishmar_id": b.get("p_mishmar_id"), "task_description": b.get("p_text"),
                "details": None, "status": "TO DO", "category": b.get("p_category") or "תוכן",
                "due_date": None, "lesson_id": None}}
        elif u.path == "/rest/v1/rpc/v2_edit_task":
            base = next((t for t in (self.wf_body or {}).get("tasks", []) if t["id"] == b.get("p_task_id")), {})
            answer = {"status": "ok", "task": {
                **base, "task_description": b.get("p_text") or base.get("task_description"),
                "details": b.get("p_details") or None, "due_date": b.get("p_due_date") or base.get("due_date"),
                "lesson_id": b.get("p_lesson_id")}}
        elif u.path == "/rest/v1/rpc/v2_delete_task":
            answer = {"status": "ok", "task": {"id": b.get("p_task_id")}}
        if answer is not None:
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(answer, ensure_ascii=False))
        if u.path == "/rest/v1/rpc/v2_set_task_status":
            ok = self.save_status == 200
            answer = ({"status": "ok", "task": {"id": (body or {}).get("p_task_id"),
                                                "status": (body or {}).get("p_status")}}
                      if ok else {"code": "XX000", "message": "boom", "details": None, "hint": None})
            return route.fulfill(status=self.save_status, content_type="application/json",
                                 body=json.dumps(answer))
        if u.path == "/auth/v1/logout":
            return route.fulfill(status=204, body="")
        return route.fulfill(status=404, content_type="application/json", body="{}")

    def count(self, path: str) -> int:
        return sum(1 for c in self.calls if c["path"] == path)


def _dmy(s: str) -> date:
    d, m, y = (int(x) for x in s.split("."))
    return date(y, m, d)


def late_home(demo: dict) -> tuple[dict, list[tuple[int, int, int]]]:
    """The demo home with tasks made late against the browser's real today
    (signed in, «today» is the clock, not as_of): two evenings that are not the
    hero — the earlier one late in two phases, the later in one — plus one late
    task of the hero itself, which belongs in the hero, never in the section.
    Returns the home and the expected groups: (mishmar id, tasks, phases)."""
    home = json.loads(json.dumps(demo))
    today = date.today()
    ms = sorted(home["mishmarim"], key=lambda m: _dmy(m["gregorian_date"]))
    upcoming = [m for m in ms if _dmy(m["gregorian_date"]) >= today]
    hero = upcoming[0] if upcoming else ms[-1]
    a, b = [m for m in ms if m["id"] != hero["id"]][-2:]
    overdue = (today - timedelta(days=3)).isoformat()
    picked: set[int] = set()

    def make_late(mid: int, categories: tuple[str, ...]) -> None:
        for cat in categories:
            t = next(t for t in home["tasks"] if t["mishmar_id"] == mid and t["category"] == cat
                     and t["id"] not in picked)
            picked.add(t["id"])
            t.update(status="TO DO", due_date=overdue)
    make_late(a["id"], ("נושא", "כיבוד"))
    make_late(b["id"], ("כיבוד",))
    hero_cat = next(t["category"] for t in home["tasks"] if t["mishmar_id"] == hero["id"] and t["category"])
    make_late(hero["id"], (hero_cat,))
    return home, [(a["id"], 2, 2), (b["id"], 1, 1)]


def auth_page(browser, base: str, mock: MockSupabase, width: int, signed_in: bool):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, locale="he-IL")
    ctx.route(f"{MOCK}/**", mock)
    if signed_in:
        key = f"sb-{urlparse(MOCK).hostname.split('.')[0]}-auth-token"
        ctx.add_init_script(f"localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(session()))})")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    return ctx, page, errors


def check_auth(browser, base: str, shots: Path, checks: dict, facts: dict) -> None:
    demo = json.loads((WEB / "src/demo.json").read_text(encoding="utf-8"))

    # signed out → the Google door, with PKCE
    mock = MockSupabase()
    ctx, page, errors = auth_page(browser, base, mock, 390, signed_in=False)
    page.get_by_role("button", name="כניסה עם Google").wait_for()
    page.screenshot(path=str(shots / "v2-signin-390.png"), full_page=True)

    # the privacy policy Google's consent screen links to: linked under the
    # button, relative (so it resolves under the sub-path), and the page itself
    # static — no script, nothing fetched from anywhere else
    href = page.get_by_role("link", name="מדיניות פרטיות").get_attribute("href")
    checks["auth: the sign-in screen links the privacy page, relative to the site"] = href == "privacy.html"
    pctx = browser.new_context(viewport={"width": 390, "height": 900}, locale="he-IL")
    ppage = pctx.new_page()
    fetched: list[str] = []
    ppage.on("request", lambda r: fetched.append(r.url))
    resp = ppage.goto(f"{base}/{href}")
    pf = ppage.evaluate("""() => ({
      dir: document.documentElement.dir, lang: document.documentElement.lang,
      h1: document.querySelector('h1')?.textContent, scripts: document.scripts.length,
      overflowX: document.documentElement.scrollWidth - window.innerWidth,
      home: document.querySelector('a[href="./"]')?.href,
    })""")
    ppage.screenshot(path=str(shots / "v2-privacy-390.png"), full_page=True)
    pctx.close()
    facts["privacy"] = {**pf, "fetched": fetched}
    checks["privacy: served under the sub-path, Hebrew RTL, no script, nothing from elsewhere"] = (
        bool(resp) and resp.status == 200 and pf["dir"] == "rtl" and pf["lang"] == "he"
        and pf["h1"] == "מדיניות פרטיות" and pf["scripts"] == 0 and pf["overflowX"] <= 0
        and pf["home"] == base + "/" and all(u.startswith(base + "/") for u in fetched))

    page.get_by_role("button", name="כניסה עם Google").click()
    page.wait_for_url(f"{MOCK}/auth/v1/authorize**")
    q = parse_qs(next(c["query"] for c in mock.calls if c["path"] == "/auth/v1/authorize"))
    facts["signin.authorize"] = {k: v[0] for k, v in q.items() if k != "code_challenge"}
    checks["auth: the Google button asks for provider=google with PKCE, back to this site"] = (
        q.get("provider") == ["google"] and q.get("redirect_to") == [base + "/"]
        and bool(q.get("code_challenge")) and q.get("code_challenge_method", [""])[0].lower() == "s256")
    checks["auth: the sign-in screen raised no page error"] = not errors
    ctx.close()

    # a stored session → one call, the user's token; ✓ saves; sign-out works
    token = session()["access_token"].split(".")[0]
    for w in WIDTHS:
        mock = MockSupabase(rpc_body=demo)
        ctx, page, errors = auth_page(browser, base, mock, w, signed_in=True)
        page.wait_for_selector("h1")
        page.wait_for_timeout(1200)                       # let any second fetch show itself
        f = page.evaluate("""() => ({
          ticks: [...document.querySelectorAll('button[aria-label]')].length,
          enabledTicks: [...document.querySelectorAll('button[aria-label]:not([disabled])')].length,
          banner: [...document.querySelectorAll('[role=note]')].some(n => n.textContent.includes('מצב הדגמה')),
          overflowX: document.documentElement.scrollWidth - window.innerWidth,
        })""")
        page.screenshot(path=str(shots / f"v2-signedin-{w}.png"), full_page=True)
        rpc = [c for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_my_home"]
        k = f"auth@{w}: "
        checks[k + "exactly one rpc/v2_my_home on load"] = len(rpc) == 1
        checks[k + "the call carries the user's token and the anon key"] = bool(rpc) and \
            (rpc[0]["auth"] or "").startswith("Bearer " + token) and rpc[0]["apikey"] == ANON
        checks[k + "every ✓ is live"] = f["ticks"] > 0 and f["enabledTicks"] == f["ticks"]
        checks[k + "no demo banner, no sideways scroll"] = not f["banner"] and f["overflowX"] <= 0

        # ✓ on the hero's first open task: on screen within a frame, then ONE
        # save naming that very task; undoing it saves «in progress», as the
        # Streamlit home's «↩ החזר לתהליך» does
        tick = page.evaluate(TICK)
        page.wait_for_timeout(600)
        hero_mid = int(re.search(r"#(\d+)", tick["hero"]).group(1)) if tick else None
        desc = tick["label"].split(": ", 1)[1] if tick else None
        task = next((t for t in demo["tasks"] if t["mishmar_id"] == hero_mid
                     and t["task_description"].replace("*", "").replace("`", "").strip() == desc), None)
        saves = [c for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_set_task_status"]
        page.locator("summary", has_text="הושלמו").click()          # the done list starts folded
        page.get_by_role("button", name=f"החזר לתהליך: {desc}", exact=True).first.click()
        page.wait_for_timeout(600)
        undo = [c for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_set_task_status"][len(saves):]
        facts[f"signedin@{w}"] = {**f, "rpc_calls": len(rpc), "tick": tick,
                                  "saves": [c["body"] for c in saves], "undo": [c["body"] for c in undo],
                                  "errors": errors}
        checks[k + "✓ on screen within a frame, then one save of that task"] = bool(tick) and bool(task) \
            and tick["gone"] and tick["ms"] < 100 and len(saves) == 1 \
            and saves[0]["body"] == {"p_task_id": task["id"], "p_status": "DONE"} \
            and (saves[0]["auth"] or "").startswith("Bearer " + token)
        checks[k + "undo saves «IN PROGRESS»"] = len(undo) == 1 and bool(task) \
            and undo[0]["body"] == {"p_task_id": task["id"], "p_status": "IN PROGRESS"}
        if w == WIDTHS[0]:
            page.get_by_role("button", name="התנתקות").click()
            page.get_by_role("button", name="כניסה עם Google").wait_for(timeout=5000)
            checks[k + "«התנתקות» → logout call, back to sign-in"] = mock.count("/auth/v1/logout") == 1
        checks[k + "no page errors"] = not errors
        ctx.close()

    # a save that fails: the task goes back to where it was, and the screen says so
    mock = MockSupabase(rpc_body=demo, save_status=500)
    ctx, page, errors = auth_page(browser, base, mock, 390, signed_in=True)
    page.wait_for_selector("h1")
    tick = page.evaluate(TICK)
    try:
        page.get_by_role("alert").wait_for(timeout=5000)
        alert = page.get_by_role("alert").inner_text()
    except Exception:
        alert = ""
    back = bool(tick) and page.evaluate(
        "(label) => [...document.querySelectorAll('button')].some(b => b.getAttribute('aria-label') === label)",
        tick["label"])
    page.screenshot(path=str(shots / "v2-save-failed-390.png"))
    saves = [c for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_set_task_status"]
    facts["save-failed"] = {"alert": alert, "back": back, "saves": len(saves), "errors": errors}
    # not tick["gone"]: the mock fails at once, so the task may already be back
    # by the next frame — what matters is one save tried, the task back, the alert
    checks["auth: a failed save puts the task back and says so"] = \
        bool(tick) and len(saves) == 1 and back and "לא נשמר" in alert and not errors
    ctx.close()

    # late tasks: one folding row per Mishmar, in date order, phases inside
    home, expected = late_home(demo)
    for w in WIDTHS:
        mock = MockSupabase(rpc_body=home)
        ctx, page, errors = auth_page(browser, base, mock, w, signed_in=True)
        page.wait_for_selector("h1")
        groups = page.evaluate("""() => [...document.querySelectorAll('details')]
          .filter(d => d.querySelector('summary').textContent.includes('באיחור'))
          .map(d => ({summary: d.querySelector('summary').textContent.replace(/\\s+/g, ' ').trim(),
                      open: d.open,
                      phases: [...d.querySelectorAll('p.mb-2')].map(p => p.textContent.replace(/\\s+/g, ' ').trim()),
                      rows: d.querySelectorAll('li').length}))""")
        heading = page.evaluate("[...document.querySelectorAll('h2')].map(h => h.textContent).find(t => t.includes('עבר התאריך')) || ''")
        page.screenshot(path=str(shots / f"v2-late-{w}.png"), full_page=True)
        page.locator("details summary", has_text="באיחור").first.click()
        opened = page.evaluate("[...document.querySelectorAll('details')].find(d => d.textContent.includes('באיחור')).open")
        if w == WIDTHS[0]:
            page.locator("details", has_text="באיחור").first.screenshot(path=str(shots / f"v2-late-open-{w}.png"))
        facts[f"late@{w}"] = {"heading": heading, "groups": groups, "opened": opened}
        k = f"late@{w}: "
        checks[k + "one row per Mishmar, in date order"] = \
            [re.search(r"משמר #\d+", g["summary"]).group() for g in groups] == \
            [f"משמר #{mid:02d}" for mid, _, _ in expected]
        checks[k + "each row: its count, its phases inside"] = len(groups) == len(expected) and all(
            f"{n} באיחור" in g["summary"] and len(g["phases"]) == ph and g["rows"] == n
            for g, (_, n, ph) in zip(groups, expected))
        checks[k + "the hero's own late task stays in the hero"] = \
            f"({sum(n for _, n, _ in expected)})" in heading
        checks[k + "several rows start folded, a tap opens one"] = \
            all(not g["open"] for g in groups) and opened is True
        checks[k + "no page errors"] = not errors
        ctx.close()

    # the three answers that are not a home
    for name, status, body, expect in (
        ("not_linked", 200, {"status": "not_linked", "email": "someone@example.org"}, "someone@example.org"),
        ("wrong_provider", 200, {"status": "wrong_provider"}, "Google בלבד"),
        ("error", 500, {"code": "XX000", "message": "boom", "details": None, "hint": None}, "משהו השתבש"),
    ):
        mock = MockSupabase(rpc_status=status, rpc_body=body)
        ctx, page, errors = auth_page(browser, base, mock, 390, signed_in=True)
        try:
            page.get_by_text(expect).first.wait_for(timeout=5000)
            shown = True
        except Exception:
            shown = False
        checks[f"auth: {name} screen"] = shown and not errors
        if name == "not_linked":
            # the instructor signs in first and lands here (their row is not a
            # 'student'): the screen must hand them the demo, not read as a fault
            page.screenshot(path=str(shots / "v2-not-linked-390.png"), full_page=True)
            link = page.get_by_role("link", name="למסך החניך במצב הדגמה")
            try:
                href = link.get_attribute("href", timeout=3000)
                link.click()
                page.get_by_text("מצב הדגמה").first.wait_for(timeout=5000)
                landed = page.evaluate("new URLSearchParams(location.search).has('demo')") \
                    and page.locator("h1").count() == 1
            except Exception:
                href, landed = None, False
            checks["auth: not_linked → the instructor's way to the demo"] = href == "?demo" and landed
        ctx.close()

    # the instructor: the trainees to choose from, then one trainee's home as
    # that trainee will see it — read-only: a ✓ there changes the screen only
    trainee = demo["me"]["name"]
    roster = {"status": "instructor", "me": {"id": 100, "name": "מדריך/ה לדוגמה"},
              "trainees": [{"id": 1, "name": "חניך/ה א"}, {"id": 2, "name": trainee}]}
    for w in WIDTHS:
        mock = MockSupabase(rpc_body=roster, as_body=demo)
        ctx, page, errors = auth_page(browser, base, mock, w, signed_in=True)
        k = f"instructor@{w}: "
        f: dict = {}
        try:
            page.get_by_role("heading", name="החניכים").wait_for(timeout=5000)
            f["names"] = page.locator("main button").all_inner_texts()
            page.screenshot(path=str(shots / f"v2-instructor-{w}.png"), full_page=True)
            page.get_by_role("button", name=trainee).click()
            page.get_by_text("מצב מדריך").first.wait_for(timeout=5000)
            f["asked"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_home_as"]
            f["h1"] = page.locator("h1").inner_text()
            f["overflowX"] = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            page.screenshot(path=str(shots / f"v2-instructor-view-{w}.png"), full_page=True)
            f["tick"] = page.evaluate(TICK)
            page.wait_for_timeout(600)                     # a save, if one were sent, shows by now
            f["saves"] = mock.count("/rest/v1/rpc/v2_set_task_status")
            page.get_by_role("button", name="לרשימת החניכים").click()
            page.get_by_role("heading", name="החניכים").wait_for(timeout=5000)
            f["back"] = page.get_by_role("button", name=trainee).is_visible()
        except Exception as e:                             # a missing step fails the checks below
            f["failed_at"] = str(e).splitlines()[0]
        facts[f"instructor@{w}"] = {k2: v for k2, v in f.items() if k2 != "tick"}
        checks[k + "the trainees to choose from"] = f.get("names") == ["חניך/ה א", trainee]
        checks[k + "one v2_home_as, for that trainee"] = f.get("asked") == [{"p_student_id": 2}]
        checks[k + "that trainee's own home, under the instructor's note"] = f.get("h1") == f"שלום, {trainee}"
        checks[k + "✓ redrawn, nothing saved"] = bool(f.get("tick")) and f["tick"]["gone"] and f.get("saves") == 0
        checks[k + "back to the list"] = f.get("back") is True
        checks[k + "no sideways scroll, no page errors"] = f.get("overflowX", 1) <= 0 and not errors
        ctx.close()


def workfile_fixture() -> dict:
    """The demo evening, made worth testing: open tasks in every phase, people
    with phones on its slots, a חבורות round with rooms — and one row with a
    «javascript:» link that must never become a link."""
    wf = json.loads((WEB / "src/demo_workfile.json").read_text(encoding="utf-8"))
    wf["viewer"] = "trainee"
    for t in wf["tasks"]:
        t["status"] = "TO DO"
    slots = [l for l in wf["lessons"] if not l["is_break"]]
    slots[0]["people"] = [{"id": 501, "name": "מועמד/ת א", "status": "📩 נשלחה פנייה", "phone": "050-111-2222",
                           "room": None, "source_url": None}]
    slots[0]["source_url"] = "javascript:alert(1)"
    rounds = [l for l in slots if "חבורות" in (l.get("lesson_role") or "")]
    if rounds:
        rounds[0]["people"] = [{"id": 502, "name": "מעביר/ה א", "status": None, "phone": None,
                                "room": "כיתת שבייד", "source_url": "https://example.org/sheet"}]
    return wf


def wf_page(browser, base: str, mock: MockSupabase, width: int, mid: int):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, locale="he-IL")
    ctx.route(f"{MOCK}/**", mock)
    key = f"sb-{urlparse(MOCK).hostname.split('.')[0]}-auth-token"
    ctx.add_init_script(f"localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(session()))})")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())            # «למחוק את המשימה…?» → yes
    page.goto(f"{base}/#/m/{mid}")
    return ctx, page, errors


def check_workfile(browser, demo_base: str, auth_base: str, shots: Path, checks: dict, facts: dict) -> None:
    demo_home = json.loads((WEB / "src/demo.json").read_text(encoding="utf-8"))
    wf = workfile_fixture()
    mid = wf["mishmar"]["id"]

    # the demo: a door from the home, three tabs, a local add
    for w in WIDTHS:
        ctx = browser.new_context(viewport={"width": w, "height": 900}, locale="he-IL")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{demo_base}/?demo")
        page.get_by_role("link", name=re.compile(rf"#{mid:02d}")).first.click()
        k = f"workfile demo@{w}: "
        try:
            page.get_by_role("heading", name=re.compile(rf"משמר #{mid:02d}")).wait_for(timeout=5000)
            tabs = page.get_by_role("tab").all_inner_texts()
            page.fill("#new-task", "משימה מקומית")
            page.get_by_role("button", name="הוסף").click()
            added = page.get_by_text("משימה מקומית").count() > 0
            page.get_by_role("tab", name="הערב").click()
            times = page.locator("section[id^=slot-]").first.inner_text()
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            page.screenshot(path=str(shots / f"v2-workfile-demo-{w}.png"), full_page=True)
        except Exception as e:
            tabs, added, times, overflow = [], False, f"failed: {str(e).splitlines()[0]}", 1
        facts[f"workfile demo@{w}"] = {"tabs": tabs, "first_slot": times[:80]}
        checks[k + "the home's card opens it; three tabs; an add shows; slots with times"] = \
            tabs == ["המשימות", "הערב", "לוגיסטיקה"] and added and bool(re.search(r"\d{2}:\d{2}–\d{2}:\d{2}", times))
        checks[k + "no sideways scroll, no page errors"] = overflow <= 0 and not errors
        ctx.close()

    # signed in: one read, and every write is exactly one call that says what it does
    for w in WIDTHS:
        mock = MockSupabase(rpc_body=demo_home, wf_body=wf)
        ctx, page, errors = wf_page(browser, auth_base, mock, w, mid)
        k = f"workfile@{w}: "
        f: dict = {}
        try:
            page.get_by_role("heading", name=re.compile(rf"משמר #{mid:02d}")).wait_for(timeout=5000)
            page.wait_for_timeout(800)
            f["reads"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_workfile"]
            # ✓ on the first open task of the open phase
            tid = int(page.locator("details[open] [data-task]").first.get_attribute("data-task"))
            page.locator(f"[data-task='{tid}'] button[aria-label^='סמן שבוצע']").click()
            page.wait_for_timeout(400)
            f["tick"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_set_task_status"]
            f["tid"] = tid
            # add
            page.fill("#new-task", "משימה מהבדיקה")
            page.select_option("select[aria-label='קטגוריה']", "קישוט")
            page.get_by_role("button", name="הוסף").click()
            page.locator("[data-task='9999']").wait_for(state="attached", timeout=5000)
            f["add"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_add_task"]
            # edit the ✓'d task: a new title, through the sheet
            row = page.locator("[data-task]").filter(has=page.locator("button[aria-label^='עריכה']")).first
            eid = int(row.get_attribute("data-task"))
            row.locator("button[aria-label^='עריכה']").click()
            sheet = page.get_by_role("dialog", name="עריכת משימה")
            sheet.locator("input").first.fill("כותרת שנערכה")
            sheet.get_by_role("button", name="💾 שמור").click()
            page.get_by_text("כותרת שנערכה").first.wait_for(timeout=5000)
            f["edit"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_edit_task"]
            f["eid"] = eid
            # delete the added one (the confirm is accepted by the page's dialog handler)
            page.locator("[data-task='9999'] button[aria-label^='מחיקה']").click()
            page.locator("[data-task='9999']").wait_for(state="detached", timeout=5000)
            f["delete"] = [c["body"] for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_delete_task"]
            # what was done is split by phase too, like the open board
            done_box = page.locator("details", has=page.locator("summary", has_text="בוצעו"))
            done_box.locator("summary").click()
            f["done_groups"] = [t.strip() for t in done_box.locator("p.mb-1\\.5").all_inner_texts()]
            f["done_rows"] = done_box.locator("[data-task]").count()
            # the evening: a phone to tap, and no link made of a «javascript:» URL
            page.get_by_role("tab", name="הערב").click()
            f["tel"] = page.locator("a[href^='tel:']").evaluate_all("els => els.map(e => e.getAttribute('href'))")
            f["js_links"] = page.locator("a[href^='javascript']").count()
            f["https_links"] = page.locator("a[href^='https://example.org']").count()
            f["overflowX"] = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            page.screenshot(path=str(shots / f"v2-workfile-evening-{w}.png"), full_page=True)
        except Exception as e:
            f["failed_at"] = str(e).splitlines()[0]
        facts[f"workfile@{w}"] = f
        checks[k + "exactly one v2_workfile, for that evening"] = f.get("reads") == [{"p_mishmar_id": mid}]
        checks[k + "✓ → one v2_set_task_status for that task"] = \
            f.get("tick") == [{"p_task_id": f.get("tid"), "p_status": "DONE"}]
        checks[k + "add → one v2_add_task (text, category), the card appears"] = f.get("add") == [
            {"p_mishmar_id": mid, "p_text": "משימה מהבדיקה", "p_category": "קישוט"}]
        checks[k + "edit → one v2_edit_task with the new title, shown"] = bool(f.get("edit")) and len(f["edit"]) == 1 \
            and f["edit"][0].get("p_task_id") == f.get("eid") and f["edit"][0].get("p_text") == "כותרת שנערכה"
        checks[k + "delete → confirmed, one v2_delete_task, the card gone"] = f.get("delete") == [{"p_task_id": 9999}]
        phase_names = ("נושא", "מרצים ותוכן", "לוגיסטיקה", "יום המשמר עצמו", "אחרי הערב")
        checks[k + "«בוצעו» is split by phase, every done task under one heading"] = \
            bool(f.get("done_groups")) and f.get("done_rows", 0) >= 1 \
            and all(any(n in g for n in phase_names) for g in f["done_groups"])
        checks[k + "a phone is a tel: link; a «javascript:» URL never a link"] = \
            f.get("tel") == ["tel:0501112222"] and f.get("js_links") == 0 and f.get("https_links", 0) >= 1
        checks[k + "no sideways scroll, no page errors"] = f.get("overflowX", 1) <= 0 and not errors
        ctx.close()

    # the instructor: everything visible, nothing to write with
    seen = dict(wf, viewer="instructor")
    mock = MockSupabase(rpc_body={"status": "instructor", "me": {"id": 100, "name": "מדריך/ה לדוגמה"},
                                  "trainees": []}, wf_body=seen)
    ctx, page, errors = wf_page(browser, auth_base, mock, 390, mid)
    try:
        page.get_by_role("heading", name=re.compile(rf"משמר #{mid:02d}")).wait_for(timeout=5000)
        g = page.evaluate("""() => ({
          add: !!document.querySelector('#new-task'),
          edits: document.querySelectorAll('button[aria-label^="עריכה"], button[aria-label^="מחיקה"]').length,
          live: [...document.querySelectorAll('button[aria-label^="סמן שבוצע"]')].filter(b => !b.disabled).length,
          note: document.body.innerText.includes('צפייה בלבד'),
        })""")
    except Exception as e:
        g = {"failed_at": str(e).splitlines()[0]}
    writes = [c["path"] for c in mock.calls if c["path"] in (
        "/rest/v1/rpc/v2_add_task", "/rest/v1/rpc/v2_edit_task", "/rest/v1/rpc/v2_delete_task",
        "/rest/v1/rpc/v2_set_task_status")]
    facts["workfile instructor"] = g
    checks["workfile instructor: view-only — no add, no edit/delete, no live ✓, says so; no write sent"] = \
        g.get("add") is False and g.get("edits") == 0 and g.get("live") == 0 and g.get("note") is True \
        and not writes and not errors
    ctx.close()


STRUCTURE_DOORS = ("v2_set_topic", "v2_add_slot", "v2_save_slot", "v2_delete_slot", "v2_reopen_slot",
                   "v2_add_person", "v2_edit_person", "v2_set_person_status", "v2_remove_person")
CLOSED = "✅ סגור"


class StructureMock(MockSupabase):
    """The workfile's mock, now also answering the nine structure doors the
    way v2.sql does — {status, workfile, result}, the workfile being the
    evening after the change. What a door WRITES is test_v2_structure.py's
    business; here the question is whether the screen sends the right call
    and draws the answer. `refuse` makes a door say no; `fail` makes it 500."""

    def __init__(self, wf: dict, **kw):
        super().__init__(wf_body=wf, **kw)
        self.wf = json.loads(json.dumps(wf))
        self.refuse: dict[str, str] = {}
        self.fail = False
        self.next_id = 7000

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _lesson(self, lid):
        return next((l for l in self.wf["lessons"] if l["id"] == lid), None)

    def _person(self, pid):
        for l in self.wf["lessons"]:
            for p in l["people"]:
                if p["id"] == pid:
                    return l, p
        return None, None

    def _apply(self, door: str, b: dict) -> dict:
        wf, result = self.wf, {}
        if door == "v2_set_topic" or (door == "v2_add_slot" and b["p_kind"] == "skeleton"):
            if door == "v2_set_topic":
                wf["mishmar"]["topic"] = b["p_topic"].strip()
            if not wf["lessons"]:
                for n, (brk, mins, role) in enumerate([(False, 75, None), (True, 30, None), (False, 75, None),
                                                       (True, 30, None), (False, 75, None), (True, 15, None),
                                                       (False, 60, "חבורות")], 1):
                    wf["lessons"].append({"id": self._id(), "slot_order": n, "start_time": None,
                                          "duration_minutes": mins, "is_break": brk, "title": None,
                                          "description": None, "lesson_role": role, "format": None,
                                          "speaker_name": None, "source_url": None, "people": []})
        elif door == "v2_add_slot":
            k = b["p_kind"]
            wf["lessons"].append({"id": self._id(), "slot_order": len(wf["lessons"]) + 1, "start_time": "02:00",
                                  "duration_minutes": 15 if k == "break" else 60, "is_break": k == "break",
                                  "title": None, "description": None,
                                  "lesson_role": "חבורות" if k == "chavurot" else None, "format": None,
                                  "speaker_name": None, "source_url": None, "people": []})
        elif door == "v2_save_slot":
            l = self._lesson(b["p_lesson_id"])
            l["duration_minutes"] = b["p_duration"]
            if not l["is_break"]:
                l.update(title=b["p_title"], lesson_role=b["p_role"], format=b["p_format"],
                         description=b["p_description"], source_url=b["p_source_url"] or None)
        elif door == "v2_delete_slot":
            wf["lessons"] = [l for l in wf["lessons"] if l["id"] != b["p_lesson_id"]]
        elif door == "v2_reopen_slot":
            self._lesson(b["p_lesson_id"])["speaker_name"] = None
        elif door == "v2_add_person":
            l = self._lesson(b["p_lesson_id"])
            p = {"id": self._id(), "name": b["p_name"], "status": "⬜ לא פנינו", "phone": b["p_phone"] or None,
                 "room": b["p_room"] or None, "source_url": None}
            l["people"].append(p)
            result["person"] = p["id"]
            if b["p_close"]:
                result.update(closed=p["name"], removed=[x["name"] for x in l["people"] if x is not p], logged=True)
                l["people"], l["speaker_name"] = [dict(p, status=CLOSED)], p["name"]
        elif door == "v2_edit_person":
            _, p = self._person(b["p_person_id"])
            for k in ("phone", "room", "source_url"):
                if b[f"p_{k}"] is not None:
                    p[k] = b[f"p_{k}"] or None
        elif door == "v2_set_person_status":
            l, p = self._person(b["p_person_id"])
            if b["p_status"] == CLOSED and "פאנל" not in (l.get("format") or ""):
                result.update(closed=p["name"], removed=[x["name"] for x in l["people"] if x is not p], logged=True)
                l["people"], l["speaker_name"] = [dict(p, status=CLOSED)], p["name"]
            else:
                p["status"] = b["p_status"]
                result["logged"] = True
        elif door == "v2_remove_person":
            l, p = self._person(b["p_person_id"])
            l["people"] = [x for x in l["people"] if x is not p]
            result["removed"] = p["name"]
        result["sync"] = {"created": 0, "removed": 0, "adopted": 0, "completed": 0, "renamed": 0}
        return {"status": "ok", "workfile": json.loads(json.dumps(wf)), "result": result}

    def __call__(self, route, request):
        u = urlparse(request.url)
        door = u.path.rsplit("/", 1)[-1]
        if u.path.startswith("/rest/v1/rpc/") and door in STRUCTURE_DOORS:
            body = json.loads(request.post_data or "{}")
            self.calls.append({"path": u.path, "body": body})
            if self.fail:
                return route.fulfill(status=500, content_type="application/json",
                                     body=json.dumps({"code": "XX000", "message": "boom"}))
            answer = {"status": self.refuse[door]} if door in self.refuse else self._apply(door, body)
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(answer, ensure_ascii=False))
        if u.path == "/rest/v1/rpc/v2_workfile":
            self.wf_body = self.wf                      # a reload reads what was written
        return super().__call__(route, request)

    def sent(self, door: str) -> list:
        return [c["body"] for c in self.calls if c["path"] == f"/rest/v1/rpc/{door}"]


def check_structure(browser, demo_base: str, auth_base: str, shots: Path, checks: dict, facts: dict) -> None:
    """Stage 2ב: every editor of the evening sends ONE call with what it says,
    and draws the evening the answer carries; a refusal and a failure say so
    and change nothing; the instructor sees no editor; the demo changes the
    screen and sends nothing."""
    demo_home = json.loads((WEB / "src/demo.json").read_text(encoding="utf-8"))
    base_wf = workfile_fixture()
    mid = base_wf["mishmar"]["id"]
    slot0 = next(l for l in base_wf["lessons"] if not l["is_break"])
    rnd = next(l for l in base_wf["lessons"] if "חבורות" in (l.get("lesson_role") or ""))

    for w in WIDTHS:
        mock = StructureMock(base_wf, rpc_body=demo_home)
        ctx, page, errors = wf_page(browser, auth_base, mock, w, mid)
        k = f"structure@{w}: "
        f: dict = {}
        notice = page.get_by_role("status")
        alert = page.get_by_role("alert")
        try:
            page.get_by_role("heading", name=re.compile(rf"משמר #{mid:02d}")).wait_for(timeout=5000)
            page.get_by_role("tab", name="הערב").click()
            card = page.locator(f"#slot-{slot0['id']}")
            # a candidate
            form = page.locator(f"[data-add='{slot0['id']}']")
            form.get_by_label("שם מרצה אפשרי").fill("מועמד/ת ב")
            form.get_by_label("טלפון").fill("052-333-4444")
            form.get_by_role("button", name="➕ מועמד").click()
            card.get_by_text("מועמד/ת ב").first.wait_for(timeout=5000)
            f["add"] = mock.sent("v2_add_person")
            f["notice"] = notice.inner_text(timeout=3000)
            new_id = f["new_id"] = mock.next_id
            # its status, its phone
            card.get_by_label("סטטוס: מועמד/ת ב").select_option("📩 נשלחה פנייה")
            page.wait_for_timeout(400)
            f["status"] = mock.sent("v2_set_person_status")
            card.get_by_role("button", name="עריכת טלפון: מועמד/ת ב").click()
            card.get_by_label("טלפון: מועמד/ת ב").fill("053-1")
            card.get_by_role("button", name="💾").click()
            card.locator("a[href='tel:0531']").wait_for(timeout=5000)
            f["phone"] = mock.sent("v2_edit_person")
            # close the first — the other goes (the confirm is accepted)
            card.get_by_role("button", name="סגירה: מועמד/ת א").click()
            card.get_by_role("button", name="🔄 החלפה").wait_for(timeout=5000)
            f["close"] = mock.sent("v2_set_person_status")[1:]
            f["closed_view"] = card.inner_text()
            card.get_by_role("button", name="🔄 החלפה").click()
            card.get_by_role("button", name="סגירה: מועמד/ת א").wait_for(timeout=5000)
            f["reopen"] = mock.sent("v2_reopen_slot")
            card.get_by_role("button", name="הסרה: מועמד/ת א").click()
            card.get_by_text("מועמד/ת א").first.wait_for(state="detached", timeout=5000)
            f["remove"] = mock.sent("v2_remove_person")
            # the slot's editor: a title, and it becomes a panel
            card.get_by_role("button", name="עריכת המקטע: שיעור 1").click()
            sheet = page.get_by_role("dialog", name="עריכת מקטע")
            sheet.get_by_label("כותרת").fill("פתיחה מהבדיקה")
            sheet.get_by_label("פורמט").select_option("פאנל")
            sheet.get_by_label("📎 קישור לדף מקורות").fill("javascript:alert(1)")
            f["bad_link_blocked"] = sheet.get_by_role("button", name="💾 שמירה").is_disabled()
            sheet.get_by_label("📎 קישור לדף מקורות").fill("https://example.org/sheet-1")
            sheet.get_by_role("button", name="💾 שמירה").click()
            card.get_by_text("פתיחה מהבדיקה").wait_for(timeout=5000)
            f["save"] = mock.sent("v2_save_slot")
            f["panel_form"] = card.get_by_role("button", name="➕ לפאנל").count()
            # a break: added at the end, its length, then gone
            breaks = page.locator("[data-break]").count()
            page.get_by_role("button", name="➕ הפסקה").click()
            page.wait_for_function(f"document.querySelectorAll('[data-break]').length > {breaks}", timeout=5000)
            brk = f["brk"] = mock.next_id
            f["add_break"] = mock.sent("v2_add_slot")
            page.locator(f"[data-break='{brk}'] select").select_option("20")
            page.wait_for_timeout(400)
            f["break_len"] = [c for c in mock.sent("v2_save_slot") if c["p_lesson_id"] == brk]
            page.locator(f"[data-break='{brk}'] button[aria-label='מחיקת ההפסקה']").click()
            page.locator(f"[data-break='{brk}']").wait_for(state="detached", timeout=5000)
            f["del_break"] = mock.sent("v2_delete_slot")
            # חבורות: a room, a presenter with a room
            rcard = page.locator(f"#slot-{rnd['id']}")
            rcard.get_by_label("חלל: מעביר/ה א").select_option("ספריית שבייד")
            page.wait_for_timeout(400)
            f["room"] = [c for c in mock.sent("v2_edit_person") if c["p_room"] is not None]
            rform = page.locator(f"[data-add='{rnd['id']}']")
            rform.get_by_label("שם המעביר").fill("מעביר/ה ב")
            rform.get_by_label("חלל", exact=True).select_option("כיתת בית מדרש")
            rform.get_by_role("button", name="➕ מעביר").click()
            rcard.get_by_text("מעביר/ה ב").first.wait_for(timeout=5000)
            f["presenter"] = mock.sent("v2_add_person")[1:]
            page.screenshot(path=str(shots / f"v2-evening-edit-{w}.png"), full_page=True)
            # a refusal: said, nothing redrawn
            mock.refuse["v2_add_person"] = "too_many"
            before_people = page.locator("[data-person]").count()
            form.get_by_label("שם מרצה לפאנל").fill("אחד יותר מדי")
            form.get_by_role("button", name="➕ לפאנל").click()
            page.wait_for_function("() => document.querySelector('[role=alert]')?.textContent.includes('המקסימום')",
                                   timeout=5000)
            f["refused"] = alert.inner_text()
            f["refused_same"] = page.locator("[data-person]").count() == before_people
            # a failure: said
            mock.refuse.clear()
            mock.fail = True
            page.get_by_role("button", name="➕ שיעור").click()
            page.wait_for_function("() => document.querySelector('[role=alert]')?.textContent.includes('לא נשמר')",
                                   timeout=5000)
            f["failed"] = alert.inner_text()
            f["overflowX"] = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        except Exception as e:
            f["failed_at"] = str(e).splitlines()[0]
            page.screenshot(path=str(shots / f"v2-evening-edit-failed-{w}.png"), full_page=True)
        facts[f"structure@{w}"] = {key: v for key, v in f.items() if key != "closed_view"}
        checks[k + "a candidate → one v2_add_person (name, phone), drawn, said"] = f.get("add") == [{
            "p_lesson_id": slot0["id"], "p_name": "מועמד/ת ב", "p_phone": "052-333-4444", "p_room": "",
            "p_close": False}] and "נוסף כמועמד" in f.get("notice", "")
        checks[k + "a status → one v2_set_person_status"] = (f.get("status") or [None])[:1] == [
            {"p_person_id": f.get("new_id"), "p_status": "📩 נשלחה פנייה"}]
        checks[k + "a phone → one v2_edit_person (phone only), drawn as tel:"] = f.get("phone") == [
            {"p_person_id": f.get("new_id"), "p_phone": "053-1", "p_room": None, "p_source_url": None}]
        checks[k + "close → confirmed, one call with ✅, the closed view with «🔄 החלפה»"] = \
            f.get("close") == [{"p_person_id": 501, "p_status": CLOSED}] and "✅ סגור" in f.get("closed_view", "")
        checks[k + "reopen / remove → one call each, drawn"] = f.get("reopen") == [{"p_lesson_id": slot0["id"]}] \
            and f.get("remove") == [{"p_person_id": 501}]
        checks[k + "the slot's editor → one v2_save_slot with every field; a javascript: link blocked; "
                   "a panel's form drawn"] = f.get("bad_link_blocked") is True and f.get("save") == [{
            "p_lesson_id": slot0["id"], "p_title": "פתיחה מהבדיקה", "p_duration": slot0["duration_minutes"],
            "p_role": "", "p_format": "פאנל", "p_description": "", "p_source_url": "https://example.org/sheet-1"}] \
            and f.get("panel_form") == 1
        checks[k + "a break: added, its length, deleted — one call each"] = \
            f.get("add_break") == [{"p_mishmar_id": mid, "p_kind": "break"}] \
            and len(f.get("break_len", [])) == 1 and f["break_len"][0]["p_duration"] == 20 \
            and f.get("del_break") == [{"p_lesson_id": f.get("brk")}]
        checks[k + "חבורות: a room → one v2_edit_person (room only); a presenter with a room"] = \
            f.get("room") == [{"p_person_id": 502, "p_phone": None, "p_room": "ספריית שבייד", "p_source_url": None}] \
            and f.get("presenter") == [{"p_lesson_id": rnd["id"], "p_name": "מעביר/ה ב", "p_phone": "",
                                        "p_room": "כיתת בית מדרש", "p_close": False}]
        checks[k + "a refusal is said, and nothing redrawn"] = "המקסימום" in f.get("refused", "") \
            and f.get("refused_same") is True
        checks[k + "a failed call is said"] = "לא נשמר" in f.get("failed", "")
        checks[k + "no sideways scroll, no page errors"] = f.get("overflowX", 1) <= 0 and not errors
        ctx.close()

    # an evening with no topic: the first step closes it; then ✏️ renames it
    blank = json.loads(json.dumps(base_wf))
    blank["mishmar"]["topic"], blank["lessons"] = None, []
    mock = StructureMock(blank, rpc_body=demo_home)
    ctx, page, errors = wf_page(browser, auth_base, mock, 390, mid)
    g: dict = {}
    try:
        page.locator("#topic-new").fill("נושא מהבדיקה")
        page.get_by_role("button", name="🎯 סגירת הנושא").click()
        page.get_by_role("button", name="עריכת הנושא").wait_for(timeout=5000)
        g["close"] = mock.sent("v2_set_topic")
        page.get_by_role("tab", name="הערב").click()
        g["slots"] = page.locator("section[id^=slot-]").count()
        page.get_by_role("button", name="עריכת הנושא").click()
        page.get_by_label("שם הנושא").fill("נושא שני")
        page.get_by_role("button", name="💾 שמירה").click()
        page.get_by_text("נושא שני").wait_for(timeout=5000)
        g["rename"] = mock.sent("v2_set_topic")[1:]
        page.screenshot(path=str(shots / "v2-topic-390.png"), full_page=True)
    except Exception as e:
        g["failed_at"] = str(e).splitlines()[0]
    facts["structure topic"] = g
    checks["structure topic: closed → one v2_set_topic, the skeleton drawn; ✏️ → one more"] = \
        g.get("close") == [{"p_mishmar_id": mid, "p_topic": "נושא מהבדיקה"}] and g.get("slots") == 4 \
        and g.get("rename") == [{"p_mishmar_id": mid, "p_topic": "נושא שני"}] and not errors
    ctx.close()

    # a topic and no structure: «✨ יצירת שלד הערב»
    bare = dict(json.loads(json.dumps(base_wf)), lessons=[])
    mock = StructureMock(bare, rpc_body=demo_home)
    ctx, page, errors = wf_page(browser, auth_base, mock, 390, mid)
    try:
        page.get_by_role("tab", name="הערב").click()
        page.get_by_role("button", name=re.compile("יצירת שלד הערב")).click()
        page.locator("section[id^=slot-]").first.wait_for(timeout=5000)
        built = mock.sent("v2_add_slot")
    except Exception as e:
        built = [str(e).splitlines()[0]]
    checks["structure skeleton: one v2_add_slot(skeleton), the slots drawn"] = \
        built == [{"p_mishmar_id": mid, "p_kind": "skeleton"}] and not errors
    ctx.close()

    # the instructor: the same evening, not one editor, not one write
    mock = StructureMock(dict(base_wf, viewer="instructor"),
                         rpc_body={"status": "instructor", "me": {"id": 100, "name": "מדריך/ה לדוגמה"}, "trainees": []})
    ctx, page, errors = wf_page(browser, auth_base, mock, 390, mid)
    try:
        page.get_by_role("tab", name="הערב").click()
        page.locator("section[id^=slot-]").first.wait_for(timeout=5000)
        h = page.evaluate("""() => ({
          editors: document.querySelectorAll('[data-add], select, button[aria-label^="עריכת"], '
                   + 'button[aria-label^="סגירה"], button[aria-label^="הסרה"], button[aria-label="מחיקת ההפסקה"]').length,
          adds: [...document.querySelectorAll('button')].filter(b => b.textContent.startsWith('➕')).length,
          topicEdit: !!document.querySelector('button[aria-label="עריכת הנושא"]'),
          phones: document.querySelectorAll('a[href^="tel:"]').length,
        })""")
    except Exception as e:
        h = {"failed_at": str(e).splitlines()[0]}
    facts["structure instructor"] = h
    checks["structure instructor: phones shown, not one editor, no write sent"] = \
        h.get("editors") == 0 and h.get("adds") == 0 and h.get("topicEdit") is False and h.get("phones", 0) >= 1 \
        and not any(c["path"].rsplit("/", 1)[-1] in STRUCTURE_DOORS for c in mock.calls) and not errors
    ctx.close()

    # the demo: the change on the screen, said, nothing sent anywhere
    for w in WIDTHS:
        ctx = browser.new_context(viewport={"width": w, "height": 900}, locale="he-IL")
        sent: list[str] = []
        ctx.on("request", lambda r: sent.append(r.url) if "/rpc/" in r.url else None)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        d: dict = {}
        try:
            page.goto(f"{demo_base}/?demo#/m/{mid}")
            page.get_by_role("tab", name="הערב").click()
            d["note"] = page.get_by_text("בהדגמה השינויים לא נשמרים").count()
            demo_slot = page.locator("section[id^=slot-]").first
            demo_form = demo_slot.locator("[data-add]")
            demo_form.get_by_label("שם מרצה אפשרי").fill("מועמד/ת בהדגמה")
            demo_form.get_by_role("button", name="➕ מועמד").click()
            demo_slot.get_by_text("מועמד/ת בהדגמה").wait_for(timeout=5000)
            demo_slot.get_by_role("button", name="סגירה: מועמד/ת בהדגמה").click()
            demo_slot.get_by_role("button", name="🔄 החלפה").wait_for(timeout=5000)
            d["closed_alone"] = demo_slot.locator("[data-person]").count() == 0 \
                and "מועמד/ת בהדגמה" in demo_slot.inner_text()
            first_times = page.locator("section[id^=slot-]").nth(1).inner_text()
            page.locator("[data-break] select").first.select_option("45")
            page.wait_for_timeout(300)
            d["reflowed"] = page.locator("section[id^=slot-]").nth(1).inner_text() != first_times
            d["overflowX"] = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            page.screenshot(path=str(shots / f"v2-evening-demo-{w}.png"), full_page=True)
        except Exception as e:
            d["failed_at"] = str(e).splitlines()[0]
        facts[f"structure demo@{w}"] = d
        checks[f"structure demo@{w}: says it saves nothing; add, close, a break's length — on the screen; "
               "no call sent"] = d.get("note") == 1 and d.get("closed_alone") is True and d.get("reflowed") is True \
            and not sent and d.get("overflowX", 1) <= 0 and not errors
        ctx.close()


def check_settings(browser, messy: str, badurl: str, shots: Path, checks: dict, facts: dict) -> None:
    """Hand-pasted settings: cleaned when they can be, named when they cannot —
    never a blank page."""
    mock = MockSupabase()
    ctx, page, errors = auth_page(browser, messy, mock, 390, signed_in=False)
    try:
        page.get_by_role("button", name="כניסה עם Google").click(timeout=5000)
        page.wait_for_url(f"{MOCK}/auth/v1/authorize**", timeout=5000)
        cleaned = True
    except Exception:
        cleaned = False
    calls = [c for c in mock.calls if c["path"] == "/auth/v1/authorize"]
    checks["settings: quotes, spaces and /rest/v1/ are cleaned — sign-in works"] = \
        cleaned and len(calls) == 1 and not errors
    ctx.close()

    ctx, page, errors = auth_page(browser, badurl, MockSupabase(), 390, signed_in=False)
    try:
        page.get_by_role("alert").wait_for(timeout=5000)
        alert = page.get_by_role("alert").inner_text()
    except Exception:
        alert = ""
    page.screenshot(path=str(shots / "v2-bad-setting-390.png"))
    page.get_by_role("link", name="למסך החניך במצב הדגמה").click()
    try:
        page.get_by_text("מצב הדגמה").first.wait_for(timeout=5000)
        demo_ok = page.locator("h1").count() == 1
    except Exception:
        demo_ok = False
    facts["settings.bad_url"] = {"alert": alert, "demo_after": demo_ok, "errors": errors}
    checks["settings: a URL that is not one names the setting, no blank page; the demo still opens"] = \
        "כתובת הפרויקט" in alert and demo_ok and not errors
    ctx.close()


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright
    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else Path(tempfile.mkdtemp(prefix="v2shots-"))
    shots.mkdir(parents=True, exist_ok=True)
    # the path the site lives under — GitHub Pages serves it at /mishmar/
    under = argv[argv.index("--under") + 1] if "--under" in argv else "mishmar"
    r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=WEB, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({"ok": False, "tsc": (r.stdout + r.stderr)[-800:]}))
        return 1
    checks: dict[str, bool] = {}
    facts: dict = {}
    tmp = Path(tempfile.mkdtemp(prefix="v2build-"))
    build(tmp / "demo", "", "")
    build(tmp / "auth", MOCK, ANON)
    # the settings as a person pastes them: quotes, a space, the REST path
    build(tmp / "messy", f' "{MOCK}/rest/v1/" ', f'"{ANON}"')
    build(tmp / "badurl", "mock-project", ANON)
    # a secret key must never reach a page: the build itself refuses it
    secret_jwt = ".".join([b64({"alg": "HS256", "typ": "JWT"}),
                           b64({"role": "service_role", "iss": "supabase"}), "c2ln"])
    refused = [build(tmp / "secret", MOCK, k, must_fail=True) for k in (secret_jwt, "sb_secret_mock")]
    checks["build: a secret key (service_role JWT, sb_secret_) fails the build"] = \
        all("SECRET Supabase key" in out for out in refused)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        demo_base, auth_base = serve(tmp / "demo", under), serve(tmp / "auth", under)
        check_demo(browser, demo_base, shots, checks, facts)
        check_auth(browser, auth_base, shots, checks, facts)
        check_workfile(browser, demo_base, auth_base, shots, checks, facts)
        check_structure(browser, demo_base, auth_base, shots, checks, facts)
        check_settings(browser, serve(tmp / "messy", under), serve(tmp / "badurl", under),
                       shots, checks, facts)
        browser.close()
    ok = all(checks.values())
    print(json.dumps({"ok": ok, "checks": checks, "facts": facts, "shots": str(shots)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
