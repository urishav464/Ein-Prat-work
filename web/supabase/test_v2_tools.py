"""Prove the v2-tools Edge Function — no Supabase needed.

    python3 web/supabase/test_v2_tools.py [--deno PATH]

The function (web/supabase/functions/v2-tools) stores a source sheet for the
v2 site. Checked by running the TypeScript itself — under Node, which strips
the types, and with --deno under Deno, the runtime Supabase runs it on:

  the twins — upload.ts against data_manager, on the same inputs:
    safeFilename   = dm._safe_filename   (Hebrew, spaces, dots, emoji, empty …)
    a slot's key   = the key dm.upload_source_sheet stores the same file under
                     (mishmar-NN/lesson-<id>-<sha1[:8]>-<safe name>)
  the handler — handler.ts on real Requests, with the database and Storage
    stood in (test_v2_tools.mjs): CORS for the site only; no token, an
    expired one, the anon role → signed_out; v2_workfile's refusals passed
    through; the instructor refused; a break, another evening's slot or
    person → forbidden; malformed fields → invalid before the database is
    asked; empty / over 20MB / not a sheet → refused; and a sheet → stored
    once at the twin key, with its type, answered with its public link.
  the wiring (--deno) — index.ts served by Deno against a local stand-in of
    Supabase's REST and Storage APIs: the evening is read with the CALLER'S
    token and the public key, never the service key; the file is stored with
    the service key, at the twin key, with its type; the bucket is made when
    missing; the link is the public one; an expired token stores nothing.
    (Deno: `npm i deno` in a scratch folder gives node_modules/.bin/deno.)

Who may call v2_workfile, and what it answers, is test_v2.py's business.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FUNCTION = HERE / "functions" / "v2-tools"
sys.path.insert(0, str(ROOT))

NAMES = [
    "דף מקורות.pdf", "הסוד_על_המקורות.pdf", "שיעור 1 - דף.PDF", "sheet.pdf", "Sheet Final (2).docx",
    "a..b.pdf", "x.tar.gz", "file.PDF ", "  spaced name.jpg  ", "—.pdf", "a__--b.pdf", "-_-a-_-.Docx",
    "📄 sheet.pdf", "file.p d f", "noext", ".hidden", "a.", "UPPER.JPEG", "א.ב", "...", "", " ",
    "דף", "mixed-עברית_and English.pptx", "tab\tname.png", "x" * 80 + ".webp", "a.b.c.d.doc",
    "__init__.py", "a__b.pdf", "c--d.png", "e_-f.doc", "C:\\fakepath\\sheet.pdf", "../../etc/passwd",
    "נ.pdf.exe",
]


def node(mode: str, payload: dict | None = None) -> dict:
    r = subprocess.run(["node", str(HERE / "test_v2_tools.mjs"), mode], cwd=HERE,
                       input=json.dumps(payload or {}), capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(json.dumps({"ok": False, "node": (r.stdout + r.stderr)[-1500:]}))
    return json.loads(r.stdout)


# ---------------------------------------------------------------- --deno

PUBLIC, SECRET = "sb_publishable_test-public", "sb_secret_test-secret"


class StandIn(BaseHTTPRequestHandler):
    """Supabase's REST and Storage, as far as index.ts uses them."""
    calls: list[dict] = []
    bucket = False
    evening: dict = {}

    def log_message(self, *a):   # quiet
        pass

    def _reply(self, code: int, body) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        size = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(size)
        call = {"path": self.path, "authorization": self.headers.get("authorization"),
                "apikey": self.headers.get("apikey"), "content_type": self.headers.get("content-type"),
                "upsert": self.headers.get("x-upsert"), "size": len(body)}
        StandIn.calls.append(call)
        if self.path == "/rest/v1/rpc/v2_workfile":
            call["body"] = json.loads(body or b"{}")
            if self.headers.get("authorization") != "Bearer user-token":
                return self._reply(401, {"code": "PGRST303", "message": "JWT expired"})
            return self._reply(200, StandIn.evening)
        if self.path == "/storage/v1/bucket":
            call["body"] = json.loads(body or b"{}")
            StandIn.bucket = True
            return self._reply(200, {"name": "sources"})
        if self.path.startswith("/storage/v1/object/sources/"):
            if not StandIn.bucket:
                return self._reply(400, {"statusCode": "404", "error": "Bucket not found",
                                         "message": "Bucket not found"})
            return self._reply(200, {"Key": self.path.removeprefix("/storage/v1/object/")})
        return self._reply(404, {})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def multipart(fields: dict, filename: str, data: bytes) -> tuple[bytes, str]:
    b = "----v2toolsboundary"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def deno_stage(deno: str, checks: dict, facts: dict, want_key: str, sheet: bytes) -> None:
    import urllib.request
    StandIn.evening = json.loads((ROOT / "web/src/demo_workfile.json").read_text(encoding="utf-8"))
    supa = ThreadingHTTPServer(("127.0.0.1", free_port()), StandIn)
    threading.Thread(target=supa.serve_forever, daemon=True).start()
    port = free_port()
    env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{supa.server_port}",
               SUPABASE_PUBLISHABLE_KEYS=json.dumps({"default": PUBLIC}),
               SUPABASE_SECRET_KEYS=json.dumps({"default": SECRET}),
               DENO_SERVE_ADDRESS=f"tcp:127.0.0.1:{port}", NO_COLOR="1")
    proc = subprocess.Popen([deno, "run", "--allow-net", "--allow-env", "index.ts"], cwd=FUNCTION, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def post(token: str | None, fields: dict, name: str, data: bytes) -> dict:
        body, ctype = multipart(fields, name, data)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=body, method="POST",
                                     headers={"Content-Type": ctype, "Origin": "https://urishav464.github.io",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"http": r.status, "cors": r.headers.get("access-control-allow-origin"),
                    **json.loads(r.read())}

    try:
        for _ in range(150):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
        fields = {"action": "upload", "mishmar": "5", "target": "lesson", "id": "8"}
        ok = post("user-token", fields, "דף מקורות.PDF", sheet)
        reads = [c for c in StandIn.calls if c["path"] == "/rest/v1/rpc/v2_workfile"]
        made = [c for c in StandIn.calls if c["path"] == "/storage/v1/bucket"]
        stores = [c for c in StandIn.calls if c["path"].startswith("/storage/v1/object/")]
        before = len(StandIn.calls)
        expired = post("old-token", fields, "a.pdf", sheet)
        after = StandIn.calls[before:]
        facts["deno"] = {"ok": ok, "expired": expired, "calls": StandIn.calls}
        checks["deno: the evening is read once — the caller's token, the PUBLIC key, mishmar 5"] = \
            len(reads) == 1 and reads[0]["authorization"] == "Bearer user-token" and reads[0]["apikey"] == PUBLIC \
            and reads[0]["body"] == {"p_mishmar_id": 5}
        checks["deno: no bucket → made public, with the service key"] = \
            len(made) == 1 and made[0]["body"].get("public") is True and made[0]["body"].get("name") == "sources" \
            and made[0]["apikey"] == SECRET
        checks["deno: stored with the service key, at the twin key, as application/pdf, upsert, every byte"] = \
            len(stores) == 2 and stores[-1]["path"] == f"/storage/v1/object/sources/{want_key}" \
            and stores[-1]["apikey"] == SECRET and stores[-1]["content_type"] == "application/pdf" \
            and stores[-1]["upsert"] == "true" and stores[-1]["size"] == len(sheet)
        checks["deno: answered ok with the public link, to the site's origin"] = \
            ok.get("status") == "ok" and ok.get("path") == want_key and ok.get("cors") == "https://urishav464.github.io" \
            and ok.get("url") == f"http://127.0.0.1:{supa.server_port}/storage/v1/object/public/sources/{want_key}"
        checks["deno: an expired token → signed_out, nothing stored"] = \
            expired.get("status") == "signed_out" and not any("/storage/" in c["path"] for c in after)
        checks["deno: the service key never goes with the caller's read"] = \
            all(c["apikey"] != SECRET and SECRET not in (c["authorization"] or "") for c in StandIn.calls
                if c["path"].startswith("/rest/"))
    except Exception as e:   # noqa: BLE001 — reported as a failed check
        checks["deno: served and answered"] = False
        facts["deno_error"] = f"{type(e).__name__}: {e}"
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0]
        facts["deno_log"] = (out or "")[-1500:]
        supa.shutdown()


def main(argv: list[str]) -> int:
    import data_manager as dm
    checks: dict[str, bool] = {}
    facts: dict = {}

    # the names
    ts = node("twins", {"names": NAMES, "files": []})["safe"]
    py = [dm._safe_filename(n, "source") for n in NAMES]
    wrong = [{"name": n, "py": p, "ts": t} for n, p, t in zip(NAMES, py, ts) if p != t]
    facts["names"] = dict(zip(NAMES, py))
    checks[f"twin: safeFilename = dm._safe_filename on {len(NAMES)} names"] = not wrong and len(ts) == len(NAMES)
    if wrong:
        facts["names_wrong"] = wrong

    # the keys: what dm.upload_source_sheet would store the same file under
    stored: list[str] = []
    dm._storage_upload = lambda path, data, content_type="application/octet-stream": (stored.append(path), (None, None))[1]
    files = [(5, 8, "דף מקורות.PDF", b"%PDF-1.4 a sheet"), (12, 301, "sheet.docx", bytes(range(256)) * 9),
             (3, 7, "", b"\x89PNG\r\n"), (21, 1, "שיעור.ב", b"x")]
    for mid, lid, name, data in files:
        dm.upload_source_sheet(mid, lid, name, data)
    tsp = node("twins", {"names": [], "files": [{"mid": m, "id": i, "name": n, "b64": base64.b64encode(d).decode()}
                                                for m, i, n, d in files]})["paths"]
    facts["keys"] = stored
    checks["twin: a slot's key = dm.upload_source_sheet's, byte for byte"] = stored == tsp and len(stored) == len(files)

    out = node("handler")
    checks.update({f"handler: {k}": v for k, v in out["checks"].items()})
    facts["handler"] = out["facts"]

    if "--deno" in argv:
        deno_stage(argv[argv.index("--deno") + 1], checks, facts, stored[0], files[0][3])

    print(json.dumps({"ok": all(checks.values()), "passed": sum(checks.values()), "total": len(checks),
                      "checks": checks, "facts": facts}, ensure_ascii=False, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
