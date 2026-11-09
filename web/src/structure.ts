// The workfile's write doors (web/supabase/v2.sql) — the evening's structure
// (stage 2ב), its logistics and after-work (2ג): their calls, their answers,
// and what the screen says about each — the Streamlit app's toasts, in its
// own words where it has them. Every door answers with the whole evening as
// v2_workfile shows it, already reconciled with its tasks.
import { CLOSED, isChavurot, isPanel, type Lesson, type Workfile } from "./model";

export type SlotKind = "lesson" | "chavurot" | "break" | "skeleton";

export type StructureCall =
  | { door: "v2_set_topic"; args: { p_mishmar_id: number; p_topic: string } }
  | { door: "v2_add_slot"; args: { p_mishmar_id: number; p_kind: SlotKind } }
  | { door: "v2_save_slot"; args: {
      p_lesson_id: number; p_title: string; p_duration: number; p_role: string; p_format: string;
      p_description: string; p_source_url: string;
    } }
  | { door: "v2_delete_slot"; args: { p_lesson_id: number } }
  | { door: "v2_reopen_slot"; args: { p_lesson_id: number } }
  | { door: "v2_add_person"; args: {
      p_lesson_id: number; p_name: string; p_phone: string; p_room: string; p_close: boolean;
    } }
  | { door: "v2_edit_person"; args: {
      p_person_id: number; p_phone: string | null; p_room: string | null; p_source_url: string | null;
    } }
  | { door: "v2_set_person_status"; args: { p_person_id: number; p_status: string } }
  | { door: "v2_remove_person"; args: { p_person_id: number } }
  // stage 2ג: the evening's logistics and its after-work — they answer the
  // same way, the whole evening; none of them touches the slots
  | { door: "v2_add_logistics"; args: { p_mishmar_id: number; p_label: string } }
  | { door: "v2_set_logistics_done"; args: { p_item_id: number; p_done: boolean } }
  | { door: "v2_delete_logistics"; args: { p_item_id: number } }
  | { door: "v2_set_invitation"; args: { p_mishmar_id: number; p_url: string } }
  | { door: "v2_add_feedback"; args: { p_mishmar_id: number; p_entries: FeedbackEntry[] } }
  | { door: "v2_add_budget"; args: { p_mishmar_id: number; p_lines: BudgetEntry[] } }
  | { door: "v2_delete_budget"; args: { p_line_id: number } };

export interface FeedbackEntry { lesson_id: number; rating: number | null; what_worked: string | null }
export interface BudgetEntry { expense_type: "מרצה" | "כיבוד" | "אחר"; description: string; actual_cost: number }

export interface SyncCounts { created: number; removed: number; adopted: number; completed: number; renamed: number }

export interface StructureResult {
  closed?: string | boolean | null;   // a topic: closed now? a person: who was closed
  removed?: string[] | string;        // the candidates a close removed / the person removed
  logged?: boolean;                   // false: two index rows share the name — not in the journal
  created?: number;
  tasks?: number;
  person?: number;
  sync?: SyncCounts;
  saved?: number;                     // feedback / budget rows written
  id?: number;                        // a logistics row added
}

export interface StructureAnswer { status: string; workfile?: Workfile; result?: StructureResult }

// app._AMBIGUOUS_WARNING
export function ambiguous(name: string): string {
  return `במאגר יש יותר מרשומה אחת בשם «${name}» — הפנייה לא נרשמה ביומן. המדריך צריך לאחד את הרשומות במאגר.`;
}

const REFUSED: Record<string, string> = {
  forbidden: "השינוי לא נשמר: המקטע או האדם כבר לא שם, או שזה לא משמר שלך. כדאי לרענן את הדף.",
  closed: "המרצה של השיעור כבר נסגר. כדי לשנות, קודם «🔄 החלפה».",
  too_many: "זה כבר המקסימום: 20 שורות בערב, ו-12 אנשים במקטע.",
  exists: "לערב הזה כבר יש מבנה.",
  invalid_text: "השם או הטקסט ריק או ארוך מדי.",
  invalid_url: "קישור לדף מקורות צריך להתחיל ב-https://",
  invalid_room: "החלל הזה לא ברשימה.",
  invalid_duration: "המשך צריך להיות בין 5 ל-240 דקות.",
  instructor: "מצב מדריך — צפייה בלבד.",
  signed_out: "החיבור פג. צריך להיכנס מחדש.",
  wrong_provider: "החיבור פג. צריך להיכנס מחדש.",
  not_linked: "החשבון הזה לא משויך לחניך.",
  too_early: "המשוב נפתח ביום הערב.",
  invalid_rating: "דירוג הוא בין כוכב אחד לחמישה.",
  invalid_slot: "המקטע הזה כבר לא בערב. כדאי לרענן את הדף.",
  invalid_amount: "סכום צריך להיות 0 ₪ או יותר.",
  invalid_type: "סוג ההוצאה לא מוכר.",
  invalid: "השינוי לא נשמר. כדאי לרענן את הדף ולנסות שוב.",
};

// «nothing» is a different sentence at each door — the Streamlit app's toasts
const NOTHING: Partial<Record<StructureCall["door"], string>> = {
  v2_add_feedback: "לא סומנו כוכבים — לא נשמר משוב",
  v2_add_budget: "אין מה לשמור: מרצה צריך שם, וכיבוד או הוצאה אחרת — סכום מעל 0.",
};

export function refusal(status: string | undefined, door?: StructureCall["door"]): string {
  if (status === "nothing" && door && NOTHING[door]) return NOTHING[door]!;
  if (status === "invalid_url" && door === "v2_set_invitation") return "קישור להזמנה צריך להתחיל ב-https://";
  return (status && REFUSED[status]) || "השינוי לא אפשרי כאן.";
}

// app._he_count's two phrasings, for the toasts below
const count = (n: number, one: string, many: string) => (n === 1 ? one : `${n} ${many}`);

export const NOT_SAVED = "השינוי לא נשמר. בדקו את החיבור ונסו שוב.";

function lessonOf(wf: Workfile, id: number): Lesson | undefined {
  return wf.lessons.find((l) => l.id === id);
}

function personOf(wf: Workfile, id: number): { l: Lesson; name: string } | undefined {
  for (const l of wf.lessons) {
    const p = l.people.find((x) => x.id === id);
    if (p) return { l, name: p.name };
  }
  return undefined;
}

const closedTo = (l: Lesson | undefined, name: string, res: StructureResult) => {
  const removed = Array.isArray(res.removed) ? res.removed : [];
  if (l && isPanel(l)) {
    return `«${name}» נסגר לפאנל` + (res.sync?.completed ? " · משימת סגירת המרצים סומנה כבוצעה" : "");
  }
  return `«${name}» נסגר לשיעור`
    + (res.sync?.completed ? " · משימת סגירת המרצה סומנה כבוצעה" : "")
    + (removed.length ? ` · הוסרו: ${removed.join(", ")}` : "");
};

// What the screen says after a door said «ok», read against the evening as it
// was before the write: a notice, and the journal's warning when it applies.
export function describe(call: StructureCall, before: Workfile, res: StructureResult): { notice: string; warning: string | null } {
  let notice = "נשמר";
  let who = "";
  switch (call.door) {
    case "v2_set_topic":
      notice = res.closed
        ? (res.created ? `הנושא נסגר! נבנה שלד ערב של ${res.created} משבצות מ-${before.mishmar.start_time || "20:00"}` : "הנושא נסגר!")
        : "הנושא עודכן";
      break;
    case "v2_add_slot":
      notice = {
        lesson: "נוסף שיעור בסוף הערב",
        chavurot: "נוסף סבב חבורות בסוף הערב",
        break: "נוספה הפסקה בסוף הערב",
        skeleton: `נבנה שלד הערב מ-${before.mishmar.start_time || "20:00"}`,
      }[call.args.p_kind];
      break;
    case "v2_save_slot":
      notice = "המקטע נשמר";
      break;
    case "v2_delete_slot": {
      const n = res.tasks ?? 0;
      notice = n === 0 ? "המקטע נמחק"
        : `המקטע נמחק · ${n === 1 ? "נמחקה איתו משימה אחת פתוחה שלו" : `נמחקו איתו ${n} משימות פתוחות שלו`}`;
      break;
    }
    case "v2_reopen_slot":
      notice = "המרצה שוחרר — אפשר לבחור מישהו אחר";
      break;
    case "v2_add_person": {
      const l = lessonOf(before, call.args.p_lesson_id);
      who = call.args.p_name.trim();
      if (l && isChavurot(l)) {
        notice = `«${who}» נוסף כמעביר חבורה${call.args.p_room ? ` — ${call.args.p_room}` : ""}`
          + (res.sync?.created ? " · נוספה משימת סידור" : "");
      } else if (call.args.p_close) {
        notice = closedTo(l, who, res);
      } else {
        notice = `«${who}» נוסף ${l && isPanel(l) ? "לפאנל" : "כמועמד"} — וגם למאגר המשותף`;
      }
      break;
    }
    case "v2_edit_person":
      notice = call.args.p_phone !== null ? "הטלפון נשמר"
        : call.args.p_room !== null ? "החלל עודכן" : "דף המקורות נשמר";
      break;
    case "v2_set_person_status": {
      const p = personOf(before, call.args.p_person_id);
      who = p?.name ?? "";
      notice = call.args.p_status === CLOSED ? closedTo(p?.l, who, res) : `הסטטוס של «${who}» עודכן`;
      break;
    }
    case "v2_remove_person":
      who = personOf(before, call.args.p_person_id)?.name ?? "";
      notice = `«${who}» הוסר`;
      break;
    case "v2_add_logistics":
      notice = `«${call.args.p_label.trim()}» נוסף לרשימת הכיבוד`;
      break;
    case "v2_set_logistics_done":
      notice = "";                    // the row itself shows it — no toast for a ✓
      break;
    case "v2_delete_logistics": {
      const label = before.logistics.find((i) => i.id === call.args.p_item_id)?.label ?? "";
      notice = `«${label}» הוסר מהרשימה`;
      break;
    }
    case "v2_set_invitation":
      notice = call.args.p_url.trim() ? "ההזמנה הועלתה" : "ההזמנה הוסרה";
      break;
    case "v2_add_feedback": {
      // app._save_feedback_clicked's toast
      const n = res.saved ?? 0;
      notice = `${n === 1 ? "נשמר" : "נשמרו"} ${count(n, "משוב אחד", "משובים")} · משימת המשוב נסגרה`;
      break;
    }
    case "v2_add_budget": {
      // app._save_budget_clicked's toast
      const n = res.saved ?? 0;
      notice = `${n === 1 ? "נשמרה" : "נשמרו"} ${count(n, "שורת תקציב אחת", "שורות תקציב")}`;
      break;
    }
    case "v2_delete_budget": {
      const line = before.budget.find((b) => b.id === call.args.p_line_id);
      notice = `השורה «${line?.description ?? ""}» נמחקה מהתקציב`;
      break;
    }
  }
  return { notice, warning: res.logged === false ? ambiguous(typeof res.closed === "string" ? res.closed : who) : null };
}
