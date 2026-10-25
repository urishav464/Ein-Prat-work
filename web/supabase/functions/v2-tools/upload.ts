// The rules of an uploaded source sheet — shared by the Edge Function that
// stores it (handler.ts) and the site that offers it (web/src/uploads.ts), and
// twins of data_manager's: `safeFilename` is `_safe_filename`, `contentTag` is
// `_content_tag`, and a slot's path is `upload_source_sheet`'s.
// web/supabase/test_v2_tools.py holds them to it. No imports: Deno, Node and
// the browser all run this file as it is.

export const MAX_BYTES = 20 * 1024 * 1024;

// what a source sheet may be, and the type it is served as — a PDF opens in
// the browser instead of downloading as a nameless blob
export const TYPES = new Map<string, string>([
  ["pdf", "application/pdf"],
  ["doc", "application/msword"],
  ["docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  ["ppt", "application/vnd.ms-powerpoint"],
  ["pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
  ["png", "image/png"],
  ["jpg", "image/jpeg"],
  ["jpeg", "image/jpeg"],
  ["webp", "image/webp"],
]);

// the file picker's filter
export const ACCEPT = [...TYPES.keys()].map((e) => `.${e}`).join(",");

// a slot's sheet, or one presenter's in a round of חבורות
export type Target = "lesson" | "presenter";

// dm._safe_filename: a Storage key must be ASCII, and every sheet a pair
// uploads is named in Hebrew — the stem is rebuilt from [A-Za-z0-9_-], a stem
// that was all Hebrew becomes `fallback`, and the extension survives on its own
export function safeFilename(filename: string | null | undefined, fallback: string): string {
  const name = (filename || fallback).trim();
  const dot = name.lastIndexOf(".");
  let stem = dot < 0 ? name : name.slice(0, dot);
  let ext = dot < 0 ? "" : name.slice(dot + 1);
  stem = stem.replace(/[^A-Za-z0-9_-]+/g, "_");
  stem = stem.replace(/[_-]{2,}/g, "_").replace(/^[_-]+|[_-]+$/g, "") || fallback;
  ext = ext.replace(/[^A-Za-z0-9]+/g, "").toLowerCase();
  return ext ? `${stem}.${ext}` : stem;
}

// dm._content_tag: eight hex chars of the bytes, in the key — a re-upload gets
// a NEW public URL, so no browser or CDN keeps serving the old file under it
export async function contentTag(bytes: ArrayBuffer): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", bytes));
  return [...digest.slice(0, 4)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// dm.upload_source_sheet's key for a slot; a presenter's sheet sits beside it
export function objectPath(mishmarId: number, target: Target, id: number, tag: string, safe: string): string {
  return `mishmar-${String(mishmarId).padStart(2, "0")}/${target}-${id}-${tag}-${safe}`;
}

export type Checked =
  | { ok: true; safe: string; contentType: string }
  | { ok: false; status: "empty" | "too_large" | "bad_type" };

// what the browser checks before sending, and the function again on arrival
export function checkFile(name: string, size: number): Checked {
  if (!(size > 0)) return { ok: false, status: "empty" };
  if (size > MAX_BYTES) return { ok: false, status: "too_large" };
  const safe = safeFilename(name, "source");
  const contentType = safe.includes(".") ? TYPES.get(safe.slice(safe.lastIndexOf(".") + 1)) : undefined;
  return contentType ? { ok: true, safe, contentType } : { ok: false, status: "bad_type" };
}
