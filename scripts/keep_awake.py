"""Keep the Streamlit Community Cloud app awake: visit it, and wake it if it slept.

Community Cloud puts an app to sleep after 12 hours without traffic; the first
trainee of the morning then met «Zzzz … Yes, get this app back up!» and waited
for a cold boot. Streamlit's own docs say a visit keeps an app awake, so a
scheduled visit every few hours (.github/workflows/keep-awake.yml) is the whole
fix. It is a workaround, not a Streamlit feature.

    python scripts/keep_awake.py https://<app>.streamlit.app

Prints one JSON line — {"state": "awake" | "woken" | "skipped", ...} — and
exits 1 only when the app could not be seen running, so a failed run shows up
in the Actions tab instead of passing quietly. No URL → «skipped», exit 0.

A real browser is needed: the sleep page is a client-side app and its button is
what wakes the container — a plain HTTP request is not a visit."""
import json
import os
import re
import sys
import time

WAKE = re.compile(r"get this app back up", re.I)
APP_READY = '[data-testid="stApp"], [data-testid="stAppViewContainer"]'


def _frames(page):
    # Community Cloud serves the app inside an iframe of its own shell page;
    # the sleep page and the app can sit in either, so look in every frame.
    return [page.main_frame, *page.main_frame.child_frames]


def _wake_button(page):
    for f in _frames(page):
        btn = f.get_by_role("button", name=WAKE)
        try:
            if btn.count() and btn.first.is_visible():
                return btn.first
        except Exception:
            pass
    return None


def _app_running(page) -> bool:
    for f in _frames(page):
        try:
            if f.locator(APP_READY).count():
                return True
        except Exception:
            pass
    return False


def visit(url: str, boot_timeout: float = 240.0) -> dict:
    from playwright.sync_api import sync_playwright

    t0 = time.time()
    with sync_playwright() as p:
        # CHROME_PATH: a local test against an already-installed browser (the
        # sandbox's); the workflow installs Playwright's own and leaves it unset
        chrome = os.environ.get("CHROME_PATH")
        browser = p.chromium.launch(executable_path=chrome or None,
                                    args=["--no-sandbox"] if chrome else None)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        state = None
        # first minute: either the app shows up, or the sleep page's button does
        deadline = time.time() + 60
        while time.time() < deadline:
            if _app_running(page):
                state = "awake"
                break
            btn = _wake_button(page)
            if btn is not None:
                btn.click()
                state = "woken"
                break
            time.sleep(3)
        if state == "woken":
            # a cold boot installs the requirements first — give it minutes
            deadline = time.time() + boot_timeout
            while time.time() < deadline and not _app_running(page):
                time.sleep(5)
        running = _app_running(page)
        browser.close()
    return {"url": url, "state": state or "unknown", "running": running,
            "seconds": round(time.time() - t0, 1)}


def main(argv: list[str]) -> int:
    url = (argv[1] if len(argv) > 1 else "").strip()
    if not url:
        print(json.dumps({"state": "skipped",
                          "why": "no app URL — set the STREAMLIT_APP_URL repository variable"}))
        return 0
    try:
        result = visit(url)
    except Exception as exc:              # unreachable, DNS, a browser crash
        result = {"url": url, "state": "error", "running": False,
                  "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["running"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
