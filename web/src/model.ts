// The trainee home's rules — a port of data_manager.py, so v2 and the Streamlit
// app answer the same questions the same way: dm.PHASES, dm.mishmar_progress,
// dm.annotate_deadline, the hero choice in app._student_body, and the late
// tasks folded per Mishmar (app._late_by_mishmar). Pure functions, no I/O.

export type Status = "TO DO" | "IN PROGRESS" | "DONE";

export interface Task {
  id: number;
  mishmar_id: number;
  task_description: string;
  status: Status;
  category: string | null;
  due_date: string | null; // ISO yyyy-mm-dd
}

export interface Mishmar {
  id: number;
  gregorian_date: string; // d.m.yyyy — the repo's convention
  hebrew_date: string;
  mishmar_type: string | null;
  topic: string | null;
  is_staff_built: boolean;
  owners: string[];
}

export interface Home {
  status: "ok";
  as_of: string;
  me: { id: number; name: string };
  mishmarim: Mishmar[];
  tasks: Task[];
}

export type PhaseKey = "topic" | "content" | "logistics" | "after";

export interface PhaseSpec {
  key: PhaseKey;
  label: string;
  icon: string;
  categories: string[];
}

// dm.PHASES — the four build phases and the task categories each one owns
export const PHASES: PhaseSpec[] = [
  { key: "topic", label: "נושא", icon: "🎯", categories: ["נושא"] },
  { key: "content", label: "מרצים ותוכן", icon: "🎤", categories: ["מרצים", "תוכן"] },
  { key: "logistics", label: "לוגיסטיקה", icon: "📦", categories: ["הזמנה", "כיבוד", "קישוט", "לוגיסטיקה", "יום המשמר"] },
  { key: "after", label: "אחרי הערב", icon: "🌙", categories: ["אחרי"] },
];

const PHASE_OF_CATEGORY: Record<string, PhaseKey> = Object.fromEntries(
  PHASES.flatMap((p) => p.categories.map((c) => [c, p.key])),
);

// A task with no category counts as content — the middle of the build — so an
// unclassified task can never silently vanish from every phase.
export function phaseOf(t: Task): PhaseKey {
  return PHASE_OF_CATEGORY[t.category ?? "תוכן"] ?? "content";
}

// app._clean — task text is written as markdown («…והמרצים *(אחרי)*»); outside
// a markdown renderer the markers would show literally. React escapes the rest.
export function clean(text: string | null | undefined): string {
  return (text ?? "").replace(/[`*]/g, "").trim();
}

// ---- dates: d.m.yyyy (mishmarim) and ISO (tasks), both to a UTC midnight

export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  const dmy = /^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$/.exec(s);
  if (dmy) return new Date(Date.UTC(+dmy[3], +dmy[2] - 1, +dmy[1]));
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (iso) return new Date(Date.UTC(+iso[1], +iso[2] - 1, +iso[3]));
  return null;
}

export function daysBetween(from: Date, to: Date): number {
  return Math.round((to.getTime() - from.getTime()) / 86_400_000);
}

export function fmtDate(s: string | null | undefined): string {
  const d = parseDate(s);
  return d ? `${d.getUTCDate()}.${d.getUTCMonth() + 1}.${d.getUTCFullYear()}` : (s ?? "");
}

// '1 ימים' reads as broken Hebrew to every trainee
export function heDays(n: number): string {
  return n === 1 ? "יום" : n === 2 ? "יומיים" : `${n} ימים`;
}

// and so does «1 משימות»
export function heTasks(n: number): string {
  return n === 1 ? "משימה אחת" : `${n} משימות`;
}

export interface Deadline {
  daysLeft: number | null;
  overdue: boolean;
  nudge: string;
}

// dm.annotate_deadline — the deck calls these dates a recommendation, so the
// wording stays soft and a DONE task never nags
export function deadline(t: Task, today: Date): Deadline {
  const out: Deadline = { daysLeft: null, overdue: false, nudge: "" };
  if (t.status === "DONE" || !t.due_date) return out;
  const due = parseDate(t.due_date);
  if (!due) return out;
  const days = daysBetween(today, due);
  out.daysLeft = days;
  if (days < 0) {
    out.overdue = true;
    out.nudge = `מומלץ היה לסגור ${heDays(-days)} קודם`;
  } else if (days === 0) {
    out.nudge = "מומלץ לסגור היום";
  } else if (days <= 3) {
    out.nudge = `מומלץ לסגור בעוד ${heDays(days)}`;
  }
  return out;
}

export interface Phase extends PhaseSpec {
  tasks: Task[];
  done: number;
  total: number;
  complete: boolean;
}

export interface Progress {
  phases: Phase[];
  current: number;
  done: number;
  total: number;
  pct: number;
  nextTask: Task | null;
}

const byDue = (a: Task, b: Task) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999");

// dm.mishmar_progress — phase 1 completes when the topic is SET; an empty
// phase counts as complete only once it has been reached
export function progress(m: Mishmar, tasks: Task[]): Progress {
  const phases: Phase[] = [];
  for (const spec of PHASES) {
    const ts = tasks.filter((t) => phaseOf(t) === spec.key);
    const done = ts.filter((t) => t.status === "DONE").length;
    const reached = phases.every((p) => p.complete);
    let complete = ts.length ? done === ts.length : reached;
    if (spec.key === "topic") complete = Boolean(m.topic) || (ts.length > 0 && done === ts.length);
    phases.push({ ...spec, tasks: ts, done, total: ts.length, complete });
  }
  const firstOpen = phases.findIndex((p) => !p.complete);
  const current = firstOpen === -1 ? phases.length - 1 : firstOpen;
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "DONE").length;
  const openCurrent = phases[current].tasks.filter((t) => t.status !== "DONE").sort(byDue);
  return { phases, current, done, total, pct: total ? done / total : 0, nextTask: openCurrent[0] ?? null };
}

// the hero: the next evening on the calendar; past ones fall to the strip.
// Sorted by the PARSED date — d.m.Y text puts 15.10 before 8.10.
export function heroOf(mishmarim: Mishmar[], today: Date): Mishmar | null {
  if (!mishmarim.length) return null;
  const upcoming = mishmarim.filter((m) => (parseDate(m.gregorian_date) ?? today) >= today);
  if (!upcoming.length) return mishmarim[mishmarim.length - 1];
  return upcoming.reduce((a, b) =>
    (parseDate(a.gregorian_date)?.getTime() ?? 0) <= (parseDate(b.gregorian_date)?.getTime() ?? 0) ? a : b,
  );
}

export interface Countdown {
  text: string;
  kind: "red" | "yellow" | "green" | "gray";
}

export function countdown(m: Mishmar, today: Date): Countdown | null {
  const d = parseDate(m.gregorian_date);
  if (!d) return null;
  const days = daysBetween(today, d);
  if (days < 0) return { text: "התקיים", kind: "gray" };
  if (days === 0) return { text: "הערב!", kind: "red" };
  return { text: `בעוד ${heDays(days)}`, kind: days <= 7 ? "red" : days <= 14 ? "yellow" : "green" };
}

export interface LateGroup {
  mishmar: Mishmar;
  phases: { phase: PhaseSpec; tasks: Task[] }[];
  count: number;
}

// app._late_by_mishmar — one group per Mishmar, in date order, its phases inside
export function lateByMishmar(late: Task[], mishmarim: Mishmar[]): LateGroup[] {
  const byId = new Map(mishmarim.map((m) => [m.id, m]));
  const groups = new Map<number, Task[]>();
  for (const t of late) groups.set(t.mishmar_id, [...(groups.get(t.mishmar_id) ?? []), t]);
  const far = Number.MAX_SAFE_INTEGER;
  return [...groups.entries()]
    .filter(([mid]) => byId.has(mid))
    .sort(([a], [b]) =>
      (parseDate(byId.get(a)!.gregorian_date)?.getTime() ?? far) -
        (parseDate(byId.get(b)!.gregorian_date)?.getTime() ?? far) || a - b)
    .map(([mid, ts]) => ({
      mishmar: byId.get(mid)!,
      count: ts.length,
      phases: PHASES.map((phase) => ({
        phase,
        tasks: ts.filter((t) => phaseOf(t) === phase.key).sort(byDue),
      })).filter((p) => p.tasks.length > 0),
    }));
}

// the phase's own deadline: the earliest due date among its tasks
export function phaseDue(ph: Phase): Date | null {
  const ds = ph.tasks.map((t) => parseDate(t.due_date)).filter((d): d is Date => d !== null);
  return ds.length ? new Date(Math.min(...ds.map((d) => d.getTime()))) : null;
}
