// The two build settings, cleaned and checked — shared by the page
// (supabase.ts) and the build itself (vite.config.ts). Pure functions: no
// browser and no Node APIs beyond atob, which both have.

// A value is pasted by hand into a dashboard field, often straight out of a
// secrets file: `"https://x.supabase.co"` with its quotes, or with a space.
export function cleanValue(v: string | undefined): string {
  return (v ?? "").trim().replace(/^["'“”‘’]+|["'“”‘’]+$/g, "").trim();
}

// The project URL, as createClient wants it: no REST/Auth path, no trailing /
export function cleanUrl(v: string | undefined): string {
  return cleanValue(v).replace(/\/(rest|auth)\/v1\/?$/, "").replace(/\/+$/, "");
}

export type KeyKind = "publishable" | "anon" | "secret" | "unknown";

// Which Supabase key this is. Only `publishable` and `anon` may ever reach a
// browser; a `secret` one (sb_secret_…, or a legacy JWT whose role is
// service_role) opens the whole database to whoever reads the page.
export function keyKind(key: string): KeyKind {
  if (key.startsWith("sb_publishable_")) return "publishable";
  if (key.startsWith("sb_secret_")) return "secret";
  const parts = key.split(".");
  if (parts.length === 3) {
    try {
      const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      const role = JSON.parse(atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4))).role;
      if (role === "anon") return "anon";
      if (role === "service_role") return "secret";
    } catch {
      return "unknown";
    }
  }
  return "unknown";
}
