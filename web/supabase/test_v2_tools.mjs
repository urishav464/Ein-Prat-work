// The Node half of test_v2_tools.py — run by it, not by hand.
//
//   node test_v2_tools.mjs twins   < {"names": [...], "files": [{mid, id, name, b64}]}
//   node test_v2_tools.mjs handler
//
// «twins» answers with what upload.ts makes of each name and file, for the
// Python side to hold against data_manager. «handler» runs the Edge Function's
// handler on Requests with the database and Storage stood in — the evening it
// is answered with is the demo's, which test_v2.py exports from a real
// v2_workfile — and answers {checks, facts}.
import { readFileSync } from "node:fs";
import { handle } from "./functions/v2-tools/handler.ts";
import { MAX_BYTES, contentTag, objectPath, safeFilename } from "./functions/v2-tools/upload.ts";

const SITE = "https://urishav464.github.io";
const FN = "https://project.example/functions/v1/v2-tools";

async function twins() {
  const input = JSON.parse(readFileSync(0, "utf8"));
  const safe = input.names.map((n) => safeFilename(n, "source"));
  const paths = [];
  for (const f of input.files) {
    const bytes = Uint8Array.from(Buffer.from(f.b64, "base64"));
    const tag = await contentTag(bytes.buffer);
    paths.push(objectPath(f.mid, "lesson", f.id, tag, safeFilename(f.name, "source")));
  }
  return { safe, paths };
}

// the demo evening (#05, the pair's own), with one presenter on its חבורות
function evening() {
  const wf = JSON.parse(readFileSync(new URL("../src/demo_workfile.json", import.meta.url), "utf8"));
  const round = wf.lessons.find((l) => (l.lesson_role ?? "").includes("חבורות"));
  round.people.push({ id: 777, name: "מעביר/ה", status: null, phone: null, room: "בית מדרש", source_url: null });
  return wf;
}

function stand(over = {}) {
  const calls = { workfile: [], upload: [], bucket: 0 };
  let fails = over.uploadFails ?? 0;
  const deps = {
    workfile: async (auth, mid) => {
      calls.workfile.push({ auth, mid });
      return over.rpc ?? { data: over.wf ?? evening(), error: null, status: 200 };
    },
    upload: async (path, bytes, contentType) => {
      calls.upload.push({ path, size: bytes.byteLength, contentType });
      return fails-- > 0 ? { error: { message: "Bucket not found" } } : { error: null };
    },
    createBucket: async () => { calls.bucket += 1; },
    publicUrl: (path) => `https://project.example/storage/v1/object/public/sources/${path}`,
  };
  return { deps, calls };
}

function request({ method = "POST", origin = SITE, auth = "Bearer user-token", fields, file, headers = {} } = {}) {
  const h = new Headers(headers);
  if (origin) h.set("origin", origin);
  if (auth) h.set("authorization", auth);
  if (method !== "POST") return new Request(FN, { method, headers: h });
  const form = new FormData();
  for (const [k, v] of Object.entries(fields ?? { action: "upload", mishmar: "5", target: "lesson", id: "8" })) {
    form.set(k, v);
  }
  if (file !== null) form.set("file", file ?? new File(["%PDF-1.4 a sheet"], "דף מקורות.PDF"));
  return new Request(FN, { method, headers: h, body: form });
}

async function run(req, over) {
  const { deps, calls } = stand(over);
  const res = await handle(req, deps);
  const text = await res.text();
  let body = null;
  try { body = JSON.parse(text); } catch { body = text; }
  return { http: res.status, body, cors: res.headers.get("access-control-allow-origin"), calls };
}

async function handler() {
  const checks = {};
  const facts = {};
  const fields = (target, id) => ({ action: "upload", mishmar: "5", target, id: String(id) });

  // CORS: the site's address only
  const pre = await run(request({ method: "OPTIONS", headers: { "access-control-request-headers": "authorization, apikey, x-client-info" } }));
  const preOther = await run(request({ method: "OPTIONS", origin: "https://evil.example" }));
  checks["CORS: a preflight from the site → 204, allowed; from elsewhere → not allowed"] =
    pre.http === 204 && pre.cors === SITE && preOther.http === 204 && preOther.cors === null;
  const get = await run(request({ method: "GET" }));
  checks["GET → 405 {status: invalid}"] = get.http === 405 && get.body.status === "invalid";

  // who: nobody gets past the database's answer
  const noAuth = await run(request({ auth: null }));
  checks["no token → signed_out, the database not even asked"] =
    noAuth.body.status === "signed_out" && noAuth.calls.workfile.length === 0;
  const expired = await run(request(), { rpc: { data: null, error: { code: "PGRST303" }, status: 401 } });
  const anon = await run(request(), { rpc: { data: null, error: { code: "42501" }, status: 401 } });
  const down = await run(request(), { rpc: { data: null, error: { code: "57P01" }, status: 503 } });
  checks["an expired token / the anon role → signed_out; the database down → unavailable"] =
    expired.body.status === "signed_out" && anon.body.status === "signed_out" && down.body.status === "unavailable";
  const asked = (await run(request())).calls.workfile;
  checks["the database is asked once, with the caller's own token, for the evening named"] =
    asked.length === 1 && asked[0].auth === "Bearer user-token" && asked[0].mid === 5;
  let passed = true;
  for (const status of ["forbidden", "not_linked", "wrong_provider", "signed_out", "not_found"]) {
    const r = await run(request(), { wf: { status } });
    passed &&= r.body.status === status && r.calls.upload.length === 0;
  }
  checks["v2_workfile's refusals pass through as they are — nothing stored"] = passed;
  const instructor = await run(request(), { wf: { ...evening(), viewer: "instructor" } });
  checks["the instructor (viewer «instructor») → refused, nothing stored"] =
    instructor.body.status === "instructor" && instructor.calls.upload.length === 0;

  // what: a slot or a presenter of THIS evening — never a break
  const outside = [
    await run(request({ fields: fields("lesson", 9) })),        // a break
    await run(request({ fields: fields("lesson", 99999) })),    // not this evening's
    await run(request({ fields: fields("presenter", 99999) })),
  ];
  checks["a break, another evening's slot or person → forbidden, nothing stored"] =
    outside.every((r) => r.body.status === "forbidden" && r.calls.upload.length === 0);
  passed = true;
  for (const f of [{ action: "other", mishmar: "5", target: "lesson", id: "8" }, fields("speaker", 8),
                   { action: "upload", mishmar: "5;", target: "lesson", id: "8" }, fields("lesson", "0"),
                   fields("lesson", "8 OR 1=1")]) {
    const r = await run(request({ fields: f }));
    passed &&= r.body.status === "invalid" && r.calls.workfile.length === 0;
  }
  const noFile = await run(request({ file: null }));
  checks["an unknown action / target, a malformed id, no file → invalid, the database not asked"] =
    passed && noFile.body.status === "invalid" && noFile.calls.workfile.length === 0;

  // the file itself
  const empty = await run(request({ file: new File([], "a.pdf") }));
  const big = await run(request({ file: new File([new Uint8Array(MAX_BYTES + 1)], "big.pdf") }));
  const declared = await run(request({ headers: { "content-length": String(MAX_BYTES * 2) } }));
  checks["empty → empty; over 20MB → too_large (and a declared length over it before reading)"] =
    empty.body.status === "empty" && big.body.status === "too_large" && declared.body.status === "too_large"
    && declared.calls.workfile.length === 0 && big.calls.upload.length === 0;
  passed = true;
  const refusedNames = ["page.html", "x.svg", "run.exe", "noext", "a.constructor", "a.__proto__", "שיעור.ב"];
  for (const name of refusedNames) {
    const r = await run(request({ file: new File(["x"], name) }));
    passed &&= r.body.status === "bad_type" && r.calls.upload.length === 0;
  }
  checks[`not a sheet (${refusedNames.join(", ")}) → bad_type, nothing stored`] = passed;

  // stored: the Streamlit app's key, the right type, the public link
  const bytes = new TextEncoder().encode("%PDF-1.4 a sheet");
  const ok = await run(request());
  const want = objectPath(5, "lesson", 8, await contentTag(bytes.buffer), "source.pdf");
  facts.ok = ok.body;
  checks["a slot's sheet → ok: one upload, at dm.upload_source_sheet's key, as application/pdf, its public link"] =
    ok.body.status === "ok" && ok.body.path === want && ok.calls.upload.length === 1
    && ok.calls.upload[0].path === want && ok.calls.upload[0].contentType === "application/pdf"
    && ok.calls.upload[0].size === bytes.byteLength
    && ok.body.url === `https://project.example/storage/v1/object/public/sources/${want}` && ok.cors === SITE;
  const pres = await run(request({ fields: fields("presenter", 777), file: new File(["\x89PNG"], "Rav Cohen.png") }));
  checks["a presenter's sheet → ok, beside it: mishmar-05/presenter-777-<tag>-Rav_Cohen.png, image/png"] =
    pres.body.status === "ok" && /^mishmar-05\/presenter-777-[0-9a-f]{8}-Rav_Cohen\.png$/.test(pres.body.path)
    && pres.calls.upload[0].contentType === "image/png";
  const again = await run(request({ file: new File(["%PDF-1.4 another sheet"], "דף מקורות.PDF") }));
  checks["other bytes under the same name → another key (no stale CDN copy)"] =
    again.body.status === "ok" && again.body.path !== ok.body.path;
  const first = await run(request(), { uploadFails: 1 });
  const never = await run(request(), { uploadFails: 2 });
  checks["no bucket yet → made, and the upload tried once more; failing still → storage"] =
    first.body.status === "ok" && first.calls.bucket === 1 && first.calls.upload.length === 2
    && never.body.status === "storage" && !("url" in never.body);
  return { checks, facts };
}

const mode = process.argv[2];
const out = mode === "twins" ? await twins() : await handler();
process.stdout.write(JSON.stringify(out));
