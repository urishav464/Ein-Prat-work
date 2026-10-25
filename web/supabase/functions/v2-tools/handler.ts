// What the v2-tools Edge Function does with a request — kept apart from
// index.ts, which only wires it to Supabase, so that test_v2_tools.mjs can run
// it under Node with the database and Storage stood in.
//
// One action today, «upload»: a source sheet for a slot or for one presenter
// of חבורות. Who may upload is decided where every other rule of v2 is — in
// the database: the function asks v2_workfile for the evening WITH THE
// CALLER'S OWN TOKEN, and goes on only if it answers as the pair of that
// evening (viewer «trainee») and the slot or the person is in that answer. The
// file is then stored with the service key, under the key the Streamlit app
// gives a slot's sheet. The link is saved by the site afterwards, through the
// doors (v2_save_slot / v2_edit_person) — this function writes no row.
import { MAX_BYTES, checkFile, contentTag, objectPath, type Target } from "./upload.ts";

interface Person { id: number }
interface Lesson { id: number; is_break: boolean; people?: Person[] }
interface Workfile { status: string; viewer?: string; lessons?: Lesson[] }

export interface Deps {
  // rpc('v2_workfile') as the caller: supabase-js's { data, error, status }
  workfile(auth: string, mishmarId: number): PromiseLike<{ data: unknown; error: { code?: string } | null; status: number }>;
  // Storage, with the service key
  upload(path: string, bytes: ArrayBuffer, contentType: string): PromiseLike<{ error: { message: string } | null }>;
  createBucket(): PromiseLike<unknown>;
  publicUrl(path: string): string;
}

// the site's one address — every urishav464.github.io page shares it
const ORIGIN = "https://urishav464.github.io";

function corsHeaders(req: Request): Record<string, string> {
  if (req.headers.get("origin") !== ORIGIN) return { Vary: "Origin" };
  return {
    "Access-Control-Allow-Origin": ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": req.headers.get("access-control-request-headers")
      ?? "authorization, x-client-info, apikey, content-type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

const ID = /^[1-9]\d{0,9}$/;
// the form's fields beside the file itself
const OVERHEAD = 64 * 1024;

export async function handle(req: Request, deps: Deps): Promise<Response> {
  const cors = corsHeaders(req);
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  // like the doors, every answer is {status, …}: the site reads one shape
  const answer = (body: Record<string, unknown>, http = 200) =>
    new Response(JSON.stringify(body), { status: http, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method !== "POST") return answer({ status: "invalid" }, 405);

  const auth = req.headers.get("authorization") ?? "";
  if (!/^Bearer \S+$/.test(auth)) return answer({ status: "signed_out" });
  if (Number(req.headers.get("content-length") ?? 0) > MAX_BYTES + OVERHEAD) return answer({ status: "too_large" });

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return answer({ status: "invalid" });
  }
  const mid = String(form.get("mishmar") ?? "");
  const target = form.get("target");
  const id = String(form.get("id") ?? "");
  const file = form.get("file");
  if (form.get("action") !== "upload" || !ID.test(mid) || !ID.test(id)
      || (target !== "lesson" && target !== "presenter") || !(file instanceof File)) {
    return answer({ status: "invalid" });
  }

  // who is asking, in the database's own words
  const { data, error, status } = await deps.workfile(auth, Number(mid));
  if (error) {
    const expired = status === 401 || error.code === "42501" || /^PGRST30/.test(error.code ?? "");
    return answer({ status: expired ? "signed_out" : "unavailable" });
  }
  const wf = (data ?? { status: "invalid" }) as Workfile;
  if (wf.status !== "ok") return answer({ status: wf.status });
  if (wf.viewer !== "trainee") return answer({ status: "instructor" });
  const slots = (wf.lessons ?? []).filter((l) => !l.is_break);
  const found = target === "lesson"
    ? slots.some((l) => l.id === Number(id))
    : slots.some((l) => (l.people ?? []).some((p) => p.id === Number(id)));
  if (!found) return answer({ status: "forbidden" });

  const checked = checkFile(file.name, file.size);
  if (!checked.ok) return answer({ status: checked.status });
  const bytes = await file.arrayBuffer();
  const path = objectPath(Number(mid), target as Target, Number(id), await contentTag(bytes), checked.safe);

  // dm._storage_upload: the bucket is made on first use
  let put = await deps.upload(path, bytes, checked.contentType);
  if (put.error) {
    try {
      await deps.createBucket();
    } catch {
      // already there, or not allowed — the second try says which
    }
    put = await deps.upload(path, bytes, checked.contentType);
  }
  if (put.error) {
    console.error(`v2-tools upload ${path}: ${put.error.message}`.slice(0, 300));
    return answer({ status: "storage" });
  }
  return answer({ status: "ok", url: deps.publicUrl(path), path });
}
