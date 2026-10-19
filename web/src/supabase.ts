import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Both values come from the host's build settings (Cloudflare Pages → Settings
// → Variables): the project URL and its PUBLIC anon key. The anon key is meant
// to be public — what it can do is decided in the database, and there it can
// do nothing at all; a browser signed in with Google can call only the doors
// in web/supabase/v2.sql (read the home, ✓ a task of its own evenings) and
// still read no table.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

// PKCE: Google sends back a one-time code, not the tokens themselves, so no
// token ever sits in the address bar or the browser history.
export const supabase: SupabaseClient | null =
  url && anonKey ? createClient(url, anonKey, { auth: { flowType: "pkce" } }) : null;

// No Supabase configured, or ?demo in the address: the prototype runs on the
// bundled demo data (real-shaped, names replaced) and nothing is sent anywhere.
export const demoMode = !supabase || new URLSearchParams(window.location.search).has("demo");
