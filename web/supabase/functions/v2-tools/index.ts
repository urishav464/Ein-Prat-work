// The v2 site's one server-side piece (Supabase → Edge Functions → v2-tools).
// Deployed with verify_jwt OFF on purpose: the project signs its tokens with
// the new keys, which the platform's own check does not read — the caller is
// checked inside, by the database (handler.ts). The keys come from the
// function's own environment, which Supabase fills in; nothing here is a
// secret of ours.
import { createClient } from "npm:@supabase/supabase-js@2.118.0";
import { handle } from "./handler.ts";

const PROJECT = Deno.env.get("SUPABASE_URL") ?? "";

// the new keys arrive as JSON ({"default": "sb_…"}), the legacy ones by name
function key(json: string, legacy: string): string {
  try {
    const k = JSON.parse(Deno.env.get(json) ?? "{}").default;
    if (typeof k === "string" && k) return k;
  } catch {
    // not JSON — fall through to the legacy name
  }
  return Deno.env.get(legacy) ?? "";
}

const PUBLIC_KEY = key("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY");
const SERVICE_KEY = key("SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY");
const NO_SESSION = { persistSession: false, autoRefreshToken: false };

const admin = createClient(PROJECT, SERVICE_KEY, { auth: NO_SESSION });
const sources = () => admin.storage.from("sources");

Deno.serve((req) => handle(req, {
  // the caller's token, the public key: exactly what the browser could ask
  workfile: (auth, mid) => createClient(PROJECT, PUBLIC_KEY, { auth: NO_SESSION, global: { headers: { Authorization: auth } } })
    .rpc("v2_workfile", { p_mishmar_id: mid }).then(({ data, error, status }) => ({ data, error, status })),
  upload: (path, bytes, contentType) => sources().upload(path, bytes, { contentType, upsert: true }),
  createBucket: () => admin.storage.createBucket("sources", { public: true }),
  publicUrl: (path) => sources().getPublicUrl(path).data.publicUrl,
}));
