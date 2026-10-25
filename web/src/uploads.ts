// A source sheet uploaded as a file: the Edge Function v2-tools stores it
// (web/supabase/functions/v2-tools — the rules of what may be sent live there,
// and are imported here as they are), and the link it answers with is saved
// through the doors, like a pasted one. What the screen says about each answer.
import { refusal } from "./structure";

export { ACCEPT, checkFile, type Target } from "../supabase/functions/v2-tools/upload";

export interface UploadAnswer { status: string; url?: string; path?: string }

const SAID: Record<string, string> = {
  empty: "הקובץ ריק.",
  too_large: "הקובץ גדול מדי — אפשר עד 20MB.",
  bad_type: "אפשר להעלות PDF, Word, PowerPoint או תמונה (JPG, PNG, WEBP).",
  storage: "האחסון לא קיבל את הקובץ. אפשר להדביק קישור במקום — ולספר למדריך.",
  unavailable: "ההעלאה לא הצליחה כרגע. אפשר לנסות שוב בעוד רגע, או להדביק קישור.",
  invalid: "ההעלאה לא הצליחה. כדאי לרענן את הדף ולנסות שוב.",
};

export function uploadRefusal(status: string | undefined): string {
  return (status && SAID[status]) || refusal(status);
}

export const UPLOAD_FAILED = "הקובץ לא הועלה. בדקו את החיבור ונסו שוב, או הדביקו קישור.";
export const DEMO_UPLOAD = "בהדגמה הקובץ לא עולה לשום מקום. באתר עצמו הוא נשמר, והקישור אליו נכנס לדף המקורות.";
