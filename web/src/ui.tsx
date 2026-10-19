// The pieces every screen is built from — the home, the instructor's list and
// the workfile share them, so they look like one app.
import type { ReactNode } from "react";
import { clean, type Progress, type Task } from "./model";
import { demoMode, signOut } from "./supabase";

export type ChipKind = "red" | "yellow" | "green" | "gray" | "gold" | "blue";
const CHIP: Record<ChipKind, string> = {
  red: "bg-late-bg text-late",
  yellow: "bg-[#fff4d6] text-[#8a5a00]",
  green: "bg-[#e6f4ea] text-[#137333]",
  gray: "bg-[#edeae1] text-[#5a564c]",
  gold: "bg-[#f6ecd2] text-[#7a5b12]",
  blue: "bg-navy-soft text-navy",
};

export function Chip({ kind, children }: { kind: ChipKind; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[kind]}`}>
      {children}
    </span>
  );
}

export function Card({ children, className = "", id }: { children: ReactNode; className?: string; id?: string }) {
  return <section id={id} className={`rounded-2xl border border-line bg-white p-4 sm:p-5 ${className}`}>{children}</section>;
}

export function H2({ children }: { children: ReactNode }) {
  return (
    <h2 className="mt-8 mb-3 border-s-4 border-navy ps-3 font-display text-xl font-extrabold text-navy">
      {children}
    </h2>
  );
}

export function CheckButton({ task, onToggle }: { task: Task; onToggle?: (t: Task) => void }) {
  const done = task.status === "DONE";
  const label = done ? `החזר לתהליך: ${clean(task.task_description)}` : `סמן שבוצע: ${clean(task.task_description)}`;
  return (
    <button
      type="button"
      onClick={onToggle ? () => onToggle(task) : undefined}
      disabled={!onToggle}
      aria-label={label}
      title={label}
      className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border text-base transition
        ${done ? "border-navy bg-navy text-white" : "border-navy/40 bg-white text-navy hover:bg-navy-soft"}
        disabled:cursor-not-allowed disabled:opacity-40`}
    >
      ✓
    </button>
  );
}

export function Stepper({ prog }: { prog: Progress }) {
  return (
    <ol className="my-4 flex items-start" aria-label="שלבי הבנייה">
      {prog.phases.map((ph, i) => {
        const state = ph.complete ? "done" : i === prog.current ? "current" : "later";
        return (
          <li key={ph.key} className="flex flex-1 items-start">
            <div className="flex w-full flex-col items-center text-center">
              <span
                className={`grid h-9 w-9 place-items-center rounded-full border-2 text-sm
                  ${state === "done" ? "border-navy bg-navy text-white" : state === "current" ? "border-navy bg-navy-soft" : "border-line bg-white"}`}
                aria-hidden
              >
                {ph.complete ? "✓" : ph.icon}
              </span>
              <span className={`mt-1 text-xs ${state === "current" ? "font-bold text-navy" : "text-muted"}`}>
                {ph.label}
              </span>
              <span className="text-[11px] text-muted">{ph.total ? `${ph.done}/${ph.total}` : "—"}</span>
            </div>
            {i < prog.phases.length - 1 && (
              <span aria-hidden className={`mt-4 h-0.5 flex-1 ${ph.complete ? "bg-navy" : "bg-line"}`} />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// The instructor looking at one trainee's screen: whose it is, that a ✓ here
// stays on this screen, and the way back to the list.
export type Preview = { name: string; onExit: () => void };

export function Shell({ children, name, alert, preview }: {
  children: ReactNode; name?: string; alert?: string | null; preview?: Preview;
}) {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sand/70">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
          <a href="#/" className="font-display font-extrabold text-navy">🕯️ משמרים · עין פרת</a>
          {name && !demoMode && (
            <button type="button" onClick={signOut} className="text-sm text-muted underline-offset-2 hover:underline">
              התנתקות
            </button>
          )}
        </div>
      </header>
      {demoMode && (
        <div className="bg-[#fff4d6] px-4 py-2 text-center text-sm text-[#8a5a00]" role="note">
          מצב הדגמה — נתונים לדוגמה מהמערכת, השמות הוחלפו. לחיצה על ✓ לא נשמרת.
        </div>
      )}
      {preview && (
        <div className="bg-navy-soft px-4 py-2 text-sm text-navy" role="note">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <span>מצב מדריך: כך {preview.name} רואה את האתר. סימון ✓ כאן לא נשמר.</span>
            <button type="button" onClick={preview.onExit} className="font-bold underline underline-offset-2">
              לרשימת החניכים
            </button>
          </div>
        </div>
      )}
      <main className="mx-auto max-w-4xl px-4 pb-16 pt-6">{children}</main>
      {/* pinned to the bottom: a failed save must be seen wherever the tap was */}
      {alert && (
        <div role="alert" className="fixed inset-x-0 bottom-0 z-10 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <p className="mx-auto max-w-md rounded-xl bg-late px-4 py-3 text-center text-sm font-semibold text-white shadow-lg">
            {alert}
          </p>
        </div>
      )}
    </div>
  );
}

export function Centered({ children }: { children: ReactNode }) {
  return (
    <Shell>
      <div className="mx-auto mt-10 max-w-sm"><Card className="text-center">{children}</Card></div>
    </Shell>
  );
}

// A link someone pasted is shown only if it is a web address: a «javascript:»
// URL in a source-sheet field would otherwise run on the reader's tap.
export function safeUrl(u: string | null | undefined): string | null {
  return u && /^https?:\/\//i.test(u.trim()) ? u.trim() : null;
}
