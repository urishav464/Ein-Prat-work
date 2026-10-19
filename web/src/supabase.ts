import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { cleanUrl, cleanValue, keyKind } from "./env";

// Both values come from the build's settings (the deploy repo urishav464/mishmar
// → Settings → Secrets and variables → Actions → Variables): the project URL
// and its PUBLIC key. That key is meant to be public — what it can do is
// decided in the database, and there it can do nothing at all; a browser signed
// in with Google can call only the doors in web/supabase/v2.sql (read the home,
// ✓ a task of its own evenings) and still read no table. A secret key never
// gets this far: the build refuses it (vite.config.ts).
const url = cleanUrl(import.meta.env.VITE_SUPABASE_URL as string | undefined);
const anonKey = cleanValue(import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined);

// What is wrong with the settings, if anything. The page names the setting to
// fix instead of going blank — createClient throws on a bad URL, and at import
// time that would stop the page before anything was drawn.
export type ConfigProblem = "url" | "key" | "secret_key";

function connect(): { client: SupabaseClient | null; problem: ConfigProblem | null } {
  if (!url && !anonKey) return { client: null, problem: null };     // not configured: the demo
  if (!/^https:\/\/[^/\s]+$/.test(url)) return { client: null, problem: "url" };
  const kind = keyKind(anonKey);
  if (kind === "secret") return { client: null, problem: "secret_key" };
  if (kind === "unknown") return { client: null, problem: "key" };
  try {
    // PKCE: Google sends back a one-time code, not the tokens themselves, so
    // no token ever sits in the address bar or the browser history.
    return { client: createClient(url, anonKey, { auth: { flowType: "pkce" } }), problem: null };
  } catch {
    return { client: null, problem: "url" };
  }
}

const { client, problem } = connect();
export const supabase: SupabaseClient | null = client;
export const configProblem: ConfigProblem | null = problem;

// ?demo in the address, or no working Supabase: the bundled demo data
// (real-shaped, names replaced), and nothing is sent anywhere.
export const askedForDemo = new URLSearchParams(window.location.search).has("demo");
export const demoMode = !supabase || askedForDemo;
