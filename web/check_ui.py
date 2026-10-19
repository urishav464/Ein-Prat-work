"""The v2 prototype in a real browser — two builds, every screen, one JSON line.

    python3 web/check_ui.py [--shots DIR]

Needs `npm install` done in web/ and the harness's Python Playwright (the same
pre-installed Chromium as scripts/harness/). Builds the app twice:

  demo  no Supabase configured → the bundled demo data (names replaced)
  auth  pointed at a MOCK Supabase host that does not exist; every request the
        browser sends it is answered here (route interception), so the
        signed-in code path runs for real with no account and no network

and checks, at 390px and 1500px:

  demo  Hebrew + RTL, no sideways scroll, the hero and its four-step stepper,
        a ✓ redrawn within a frame, no markdown markers on screen
  auth  signed out → «כניסה עם Google» asks for provider=google with PKCE;
        a stored session → exactly ONE rpc/v2_my_home, carrying the user's
        token; every ✓ disabled (read-only); late tasks (made late against
        today) folded one <details> per Mishmar in date order, phases inside,
        the hero's own late task kept out; not_linked / wrong_provider / error
        screens, not_linked with a working link to the demo (where the
        instructor lands); «התנתקות» → back to the sign-in screen

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
ANON = "mock-anon-key"
WIDTHS = (390, 1500)


def build(out: Path, url: str, key: str) -> None:
    env = dict(os.environ, VITE_SUPABASE_URL=url, VITE_SUPABASE_ANON_KEY=key)
    r = subprocess.run(["npx", "vite", "build", "--outDir", str(out), "--emptyOutDir"],
                       cwd=WEB, env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(json.dumps({"ok": False, "build": r.stderr[-800:]}))


def serve(root: Path, under: str = "v2") -> str:
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
          gone: ![...hero.querySelectorAll('button')].some(b => b.getAttribute('aria-label') === label)};
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

    def __init__(self, rpc_status: int = 200, rpc_body: dict | None = None):
        self.rpc_status, self.rpc_body = rpc_status, rpc_body or {}
        self.calls: list[dict] = []

    def __call__(self, route, request):
        u = urlparse(request.url)
        self.calls.append({"path": u.path, "query": u.query, "method": request.method,
                           "auth": request.headers.get("authorization"),
                           "apikey": request.headers.get("apikey")})
        if u.path == "/auth/v1/authorize":
            return route.fulfill(status=200, content_type="text/html", body="<p>mock Google</p>")
        if u.path == "/rest/v1/rpc/v2_my_home":
            return route.fulfill(status=self.rpc_status, content_type="application/json",
                                 body=json.dumps(self.rpc_body, ensure_ascii=False))
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
    page.get_by_role("button", name="כניסה עם Google").click()
    page.wait_for_url(f"{MOCK}/auth/v1/authorize**")
    q = parse_qs(next(c["query"] for c in mock.calls if c["path"] == "/auth/v1/authorize"))
    facts["signin.authorize"] = {k: v[0] for k, v in q.items() if k != "code_challenge"}
    checks["auth: the Google button asks for provider=google with PKCE, back to this site"] = (
        q.get("provider") == ["google"] and q.get("redirect_to") == [base + "/"]
        and bool(q.get("code_challenge")) and q.get("code_challenge_method", [""])[0].lower() == "s256")
    checks["auth: the sign-in screen raised no page error"] = not errors
    ctx.close()

    # a stored session → one call, the user's token, read-only, sign-out works
    for w in WIDTHS:
        mock = MockSupabase(rpc_body=demo)
        ctx, page, errors = auth_page(browser, base, mock, w, signed_in=True)
        page.wait_for_selector("h1")
        page.wait_for_timeout(1200)                       # let any second fetch show itself
        f = page.evaluate("""() => ({
          ticks: [...document.querySelectorAll('button[aria-label]')].length,
          enabledTicks: [...document.querySelectorAll('button[aria-label]:not([disabled])')].length,
          banner: [...document.querySelectorAll('[role=note]')].some(n => n.textContent.includes('מצב הדגמה')),
          readOnlyNote: [...document.querySelectorAll('[role=note]')].some(n => n.textContent.includes('לצפייה בלבד')),
          overflowX: document.documentElement.scrollWidth - window.innerWidth,
        })""")
        page.screenshot(path=str(shots / f"v2-signedin-{w}.png"), full_page=True)
        rpc = [c for c in mock.calls if c["path"] == "/rest/v1/rpc/v2_my_home"]
        token = session()["access_token"].split(".")[0]
        facts[f"signedin@{w}"] = {**f, "rpc_calls": len(rpc), "errors": errors}
        k = f"auth@{w}: "
        checks[k + "exactly one rpc/v2_my_home on load"] = len(rpc) == 1
        checks[k + "the call carries the user's token and the anon key"] = bool(rpc) and \
            (rpc[0]["auth"] or "").startswith("Bearer " + token) and rpc[0]["apikey"] == ANON
        checks[k + "read-only: every ✓ disabled, and the screen says so"] = \
            f["ticks"] > 0 and f["enabledTicks"] == 0 and f["readOnlyNote"]
        checks[k + "no demo banner, no sideways scroll"] = not f["banner"] and f["overflowX"] <= 0
        if w == WIDTHS[0]:
            page.get_by_role("button", name="התנתקות").click()
            page.get_by_role("button", name="כניסה עם Google").wait_for(timeout=5000)
            checks[k + "«התנתקות» → logout call, back to sign-in"] = mock.count("/auth/v1/logout") == 1
        checks[k + "no page errors"] = not errors
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


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright
    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else Path(tempfile.mkdtemp(prefix="v2shots-"))
    shots.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=WEB, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({"ok": False, "tsc": (r.stdout + r.stderr)[-800:]}))
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="v2build-"))
    build(tmp / "demo", "", "")
    build(tmp / "auth", MOCK, ANON)
    checks: dict[str, bool] = {}
    facts: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        check_demo(browser, serve(tmp / "demo"), shots, checks, facts)
        check_auth(browser, serve(tmp / "auth"), shots, checks, facts)
        browser.close()
    ok = all(checks.values())
    print(json.dumps({"ok": ok, "checks": checks, "facts": facts, "shots": str(shots)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
