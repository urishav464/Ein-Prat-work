import { useEffect, useMemo, useState, type ReactNode } from "react";
import demoData from "./demo.json";
import { demoMode, supabase } from "./supabase";
import {
  clean, countdown, deadline, fmtDate, heTasks, heroOf, lateByMishmar, parseDate, phaseDue, progress,
  type Home, type LateGroup, type Mishmar, type Progress, type Task,
} from "./model";

type Load =
  | { kind: "loading" }
  | { kind: "signed_out" }
  | { kind: "not_linked"; email: string }
  | { kind: "wrong_provider" }
  | { kind: "error"; message: string }
  | { kind: "ok"; home: Home };

function localToday(): Date {
  const n = new Date();
  return new Date(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()));
}

// ---------------------------------------------------------------- data

function useHome(): [Load, (fn: (h: Home) => Home) => void] {
  const [load, setLoad] = useState<Load>(
    demoMode ? { kind: "ok", home: demoData as Home } : { kind: "loading" },
  );
  useEffect(() => {
    if (demoMode || !supabase) return;
    const sb = supabase;
    const fetchHome = async (signedIn: boolean) => {
      if (!signedIn) return setLoad({ kind: "signed_out" });
      const { data, error } = await sb.rpc("v2_my_home");
      if (error) return setLoad({ kind: "error", message: error.message });
      const status = (data as { status?: string })?.status;
      if (status === "ok") return setLoad({ kind: "ok", home: data as Home });
      if (status === "not_linked") return setLoad({ kind: "not_linked", email: (data as { email: string }).email });
      if (status === "wrong_provider") return setLoad({ kind: "wrong_provider" });
      setLoad({ kind: "signed_out" });
    };
    // One fetch per session. INITIAL_SESSION arrives as soon as the stored
    // session is read (so there is no separate first fetch), often right after a
    // SIGNED_IN that carries the very same token — that one is skipped. A token
    // refresh (hourly) does refetch. Deferred: a Supabase call made inside this
    // callback can deadlock the auth lock.
    let last: string | null | undefined;
    const { data: sub } = sb.auth.onAuthStateChange((_event, session) => {
      const token = session?.access_token ?? null;
      if (token === last) return;
      last = token;
      setTimeout(() => fetchHome(token !== null), 0);
    });
    return () => sub.subscription.unsubscribe();
  }, []);
  const update = (fn: (h: Home) => Home) =>
    setLoad((l) => (l.kind === "ok" ? { kind: "ok", home: fn(l.home) } : l));
  return [load, update];
}

const signIn = () =>
  // back to this very page — the site may live under a path, not at the root
  supabase?.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.origin + window.location.pathname },
  });
const signOut = () => supabase?.auth.signOut();

// ---------------------------------------------------------------- primitives

type ChipKind = "red" | "yellow" | "green" | "gray" | "gold" | "blue";
const CHIP: Record<ChipKind, string> = {
  red: "bg-late-bg text-late",
  yellow: "bg-[#fff4d6] text-[#8a5a00]",
  green: "bg-[#e6f4ea] text-[#137333]",
  gray: "bg-[#edeae1] text-[#5a564c]",
  gold: "bg-[#f6ecd2] text-[#7a5b12]",
  blue: "bg-navy-soft text-navy",
};

function Chip({ kind, children }: { kind: ChipKind; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[kind]}`}>
      {children}
    </span>
  );
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-white p-4 sm:p-5 ${className}`}>{children}</section>;
}

function H2({ children }: { children: ReactNode }) {
  return (
    <h2 className="mt-8 mb-3 border-s-4 border-navy ps-3 font-display text-xl font-extrabold text-navy">
      {children}
    </h2>
  );
}

function CheckButton({ task, onToggle }: { task: Task; onToggle?: (t: Task) => void }) {
  const done = task.status === "DONE";
  const label = done ? `החזר לתהליך: ${clean(task.task_description)}` : `סמן שבוצע: ${clean(task.task_description)}`;
  return (
    <button
      type="button"
      onClick={onToggle ? () => onToggle(task) : undefined}
      disabled={!onToggle}
      aria-label={label}
      title={onToggle ? label : "בשלב הזה של הניסיון — לצפייה בלבד. מסמנים באפליקציה הרגילה."}
      className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border text-base transition
        ${done ? "border-navy bg-navy text-white" : "border-navy/40 bg-white text-navy hover:bg-navy-soft"}
        disabled:cursor-not-allowed disabled:opacity-40`}
    >
      ✓
    </button>
  );
}

// ---------------------------------------------------------------- pieces

function Stepper({ prog }: { prog: Progress }) {
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

function TaskCard({ t, today, onToggle }: { t: Task; today: Date; onToggle?: (t: Task) => void }) {
  const dl = deadline(t, today);
  const soon = dl.daysLeft !== null && dl.daysLeft >= 0 && dl.daysLeft <= 7;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-white p-3">
      <div className="min-w-0 flex-1">
        <p className="font-semibold leading-snug">{clean(t.task_description)}</p>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {t.category && <Chip kind="gold">{t.category}</Chip>}
          {dl.overdue && <Chip kind="red">באיחור</Chip>}
          {!dl.overdue && soon && <Chip kind="yellow">השבוע</Chip>}
        </div>
        {(dl.nudge || t.due_date) && (
          <p className={`mt-1 text-sm ${dl.overdue ? "text-late" : "text-muted"}`}>
            🕒 {dl.nudge || `מומלץ עד ${fmtDate(t.due_date)}`}
          </p>
        )}
      </div>
      <CheckButton task={t} onToggle={onToggle} />
    </div>
  );
}

function Hero({ m, prog, me, today, onToggle }: {
  m: Mishmar; prog: Progress; me: string; today: Date; onToggle?: (t: Task) => void;
}) {
  const cd = countdown(m, today);
  const partners = m.owners.filter((n) => n !== me);
  const cur = prog.phases[prog.current];
  const open = cur.tasks.filter((t) => t.status !== "DONE")
    .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
  const next = prog.phases[prog.current + 1];
  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-display text-2xl font-extrabold text-navy">🕯️ משמר #{String(m.id).padStart(2, "0")}</span>
        <span className="text-muted">{m.gregorian_date} · {m.hebrew_date}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {cd && <Chip kind={cd.kind}>{cd.text}</Chip>}
        {!m.is_staff_built && <Chip kind="blue">👥 {partners.length ? `עם ${partners.join(" · ")}` : "צוות"}</Chip>}
        {m.mishmar_type && <Chip kind="gold">{m.mishmar_type}</Chip>}
      </div>
      <p className="mt-3"><span className="font-bold">הנושא:</span> {m.topic ?? <span className="text-muted">עוד לא נסגר</span>}</p>

      <Stepper prog={prog} />
      {prog.total > 0 && (
        <div>
          <div className="h-2 overflow-hidden rounded-full bg-line" role="progressbar"
               aria-valuenow={Math.round(prog.pct * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full bg-navy transition-all" style={{ width: `${prog.pct * 100}%` }} />
          </div>
          <p className="mt-1 text-sm text-muted">{prog.done}/{prog.total} משימות הושלמו</p>
        </div>
      )}

      {prog.nextTask && (
        <div className="mt-4 rounded-xl bg-navy-soft px-4 py-3">
          ⭐ <span className="font-bold">הצעד הבא:</span> {clean(prog.nextTask.task_description)}
          {prog.nextTask.due_date && (
            <span className="ms-2 text-sm text-muted">מומלץ עד {fmtDate(prog.nextTask.due_date)}</span>
          )}
        </div>
      )}

      {open.length > 0 ? (
        <>
          <p className="mt-5 mb-2 font-bold">המשימות של שלב «{cur.label}» ({open.length}):</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {open.map((t) => <TaskCard key={t.id} t={t} today={today} onToggle={onToggle} />)}
          </div>
          {next && next.total > 0 && (
            <p className="mt-3 text-sm text-muted">
              🔒 אחרי שלב «{cur.label}» ייפתח שלב «{next.label}» — {heTasks(next.total)}{" "}
              {next.total === 1 ? "מחכה" : "מחכות"} שם בשקט.
            </p>
          )}
        </>
      ) : prog.total > 0 && (
        <p className="mt-4 rounded-xl bg-[#e6f4ea] px-4 py-3 text-[#137333]">כל המשימות של השלב הנוכחי סגורות. 🎉</p>
      )}
    </Card>
  );
}

function LateSection({ groups, today, onToggle }: {
  groups: LateGroup[]; today: Date; onToggle?: (t: Task) => void;
}) {
  const n = groups.reduce((s, g) => s + g.count, 0);
  return (
    <>
      <H2>עבר התאריך המומלץ במשמרים אחרים ({n})</H2>
      <p className="mb-3 text-sm text-muted">המלצה — לא חוק. אבל אלה קודמים לכל השאר.</p>
      <div className="space-y-2">
        {groups.map((g) => {
          const m = g.mishmar;
          return (
            <details key={m.id} open={groups.length === 1} className="rounded-2xl border border-line bg-white">
              <summary className="flex items-center gap-2 px-4 py-3">
                <span className="chev text-muted" aria-hidden>‹</span>
                <span className="min-w-0 flex-1">
                  <span className="font-bold">משמר #{String(m.id).padStart(2, "0")}</span>
                  <span className="text-muted"> · {fmtDate(m.gregorian_date)} · {m.topic ?? "בלי נושא"}</span>
                </span>
                <Chip kind="red">{g.count} באיחור</Chip>
              </summary>
              <div className="space-y-4 px-4 pb-4">
                {g.phases.map(({ phase, tasks }) => (
                  <div key={phase.key}>
                    <p className="mb-2 font-bold">{phase.icon} {phase.label} <span className="text-muted">({tasks.length})</span></p>
                    <ul className="space-y-2">
                      {tasks.map((t) => (
                        <li key={t.id} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2">
                          <div className="min-w-0 flex-1">
                            <p>⏰ <span className="font-bold">{clean(t.task_description)}</span></p>
                            <p className="text-sm text-late">{deadline(t, today).nudge}</p>
                          </div>
                          <CheckButton task={t} onToggle={onToggle} />
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </>
  );
}

function MiniCard({ m, prog, today }: { m: Mishmar; prog: Progress; today: Date }) {
  const cd = countdown(m, today);
  return (
    <Card className="!p-4">
      <p className="font-bold">#{String(m.id).padStart(2, "0")} · {fmtDate(m.gregorian_date)}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {cd && <Chip kind={cd.kind}>{cd.text}</Chip>}
        {m.owners.length ? <Chip kind="blue">👥 {m.owners.join(" · ")}</Chip> : <Chip kind="gray">צוות</Chip>}
      </div>
      <ol className="mt-3 flex items-start" aria-label="שלבים ותאריכים">
        {prog.phases.map((ph, i) => {
          const due = phaseDue(ph);
          const late = Boolean(due && !ph.complete && due < today);
          return (
            <li key={ph.key} className="flex flex-1 items-start">
              <div className="flex w-full flex-col items-center text-center">
                <span aria-hidden className={`grid h-7 w-7 place-items-center rounded-full border text-xs
                  ${ph.complete ? "border-navy bg-navy text-white" : i === prog.current ? "border-navy bg-navy-soft" : "border-line"}`}>
                  {ph.complete ? "✓" : ph.icon}
                </span>
                <span className="mt-0.5 text-[11px] text-muted">{ph.label}</span>
                <span className={`text-[11px] ${late ? "font-bold text-late" : "text-muted"}`}>
                  {due ? `${due.getUTCDate()}.${due.getUTCMonth() + 1}` : "—"}
                </span>
              </div>
              {i < prog.phases.length - 1 && <span aria-hidden className={`mt-3.5 h-px flex-1 ${ph.complete ? "bg-navy" : "bg-line"}`} />}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

// ---------------------------------------------------------------- screens

function Shell({ children, name }: { children: ReactNode; name?: string }) {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sand/70">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
          <span className="font-display font-extrabold text-navy">🕯️ משמרים · עין פרת</span>
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
      {/* a tooltip never shows on a phone, and a ✓ that does nothing reads as broken */}
      {name && !demoMode && (
        <div className="bg-navy-soft px-4 py-2 text-center text-sm text-navy" role="note">
          גרסת ניסיון לצפייה בלבד — את המשימות מסמנים ✓ באפליקציה הרגילה.
        </div>
      )}
      <main className="mx-auto max-w-4xl px-4 pb-16 pt-6">{children}</main>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <Shell>
      <div className="mx-auto mt-10 max-w-sm"><Card className="text-center">{children}</Card></div>
    </Shell>
  );
}

function HomeScreen({ home, today, onToggle }: { home: Home; today: Date; onToggle?: (t: Task) => void }) {
  const data = useMemo(() => {
    const byMid = new Map<number, Task[]>();
    for (const t of home.tasks) byMid.set(t.mishmar_id, [...(byMid.get(t.mishmar_id) ?? []), t]);
    const prog = new Map(home.mishmarim.map((m) => [m.id, progress(m, byMid.get(m.id) ?? [])]));
    const hero = heroOf(home.mishmarim, today);
    // overdue anywhere is the one thing allowed to jump the phase queue
    const late = home.tasks.filter((t) => t.mishmar_id !== hero?.id && deadline(t, today).overdue);
    const others = home.mishmarim.filter((m) => m.id !== hero?.id)
      .sort((a, b) => (parseDate(a.gregorian_date)?.getTime() ?? 0) - (parseDate(b.gregorian_date)?.getTime() ?? 0));
    const done = home.tasks.filter((t) => t.status === "DONE");
    return { prog, hero, late: lateByMishmar(late, home.mishmarim), others, done };
  }, [home, today]);

  return (
    <Shell name={home.me.name}>
      <h1 className="font-display text-3xl font-extrabold text-navy">שלום, {home.me.name}</h1>
      {data.late.length > 0 && <LateSection groups={data.late} today={today} onToggle={onToggle} />}
      {data.hero && (
        <>
          <H2>המשמר הבא שלי</H2>
          <Hero m={data.hero} prog={data.prog.get(data.hero.id)!} me={home.me.name} today={today} onToggle={onToggle} />
        </>
      )}
      {data.others.length > 0 && (
        <>
          <H2>שאר המשמרים שלי</H2>
          <p className="mb-3 text-sm text-muted">הם מחכים בתור — כל אחד ייפתח כשיגיע זמנו.</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.others.map((m) => <MiniCard key={m.id} m={m} prog={data.prog.get(m.id)!} today={today} />)}
          </div>
        </>
      )}
      {data.done.length > 0 && (
        <details className="mt-8 rounded-2xl border border-line bg-white">
          <summary className="flex items-center gap-2 px-4 py-3">
            <span className="chev text-muted" aria-hidden>‹</span>
            <span className="font-bold">✅ הושלמו ({data.done.length})</span>
          </summary>
          <div className="grid gap-2 px-4 pb-4 sm:grid-cols-2">
            {data.done.map((t) => <TaskCard key={t.id} t={t} today={today} onToggle={onToggle} />)}
          </div>
        </details>
      )}
    </Shell>
  );
}

export default function App() {
  const [load, update] = useHome();
  const today = useMemo(
    () => (demoMode && load.kind === "ok" ? parseDate(load.home.as_of) ?? localToday() : localToday()),
    [load],
  );
  // demo: ✓ flips the task on screen at once — nothing is sent anywhere.
  // Signed in, the prototype is read-only (writes come after the gate).
  const onToggle = demoMode
    ? (t: Task) => update((h) => ({
        ...h,
        tasks: h.tasks.map((x) => x.id === t.id ? { ...x, status: x.status === "DONE" ? "TO DO" : "DONE" } : x),
      }))
    : undefined;

  switch (load.kind) {
    case "loading":
      return <Centered><p className="text-muted">טוען…</p></Centered>;
    case "signed_out":
      return (
        <Centered>
          <p className="font-display text-xl font-extrabold text-navy">משמרים · מדרשת עין פרת</p>
          <p className="mt-2 text-sm text-muted">היכנסו עם חשבון הגוגל שאיתו נרשמתם אצל המדריך.</p>
          <button type="button" onClick={signIn}
                  className="mt-5 w-full rounded-xl bg-navy px-4 py-3 font-bold text-white hover:bg-navy/90">
            כניסה עם Google
          </button>
        </Centered>
      );
    case "not_linked":
      return (
        <Centered>
          <p>התחברת בתור <span dir="ltr" className="font-bold">{load.email}</span>, אבל הכתובת הזו עדיין לא משויכת לאף חניך.</p>
          <p className="mt-2 text-sm text-muted">בקשו מהמדריך לשייך אותה בלוח הבקרה, תחת «שיוך חשבונות».</p>
          {/* the instructor is a students row with role 'instructor', so this
              screen is exactly what they get — and it must not read as a fault */}
          <div className="mt-5 rounded-xl bg-navy-soft px-4 py-3 text-sm">
            <p><span className="font-bold">חשבון של המדריך?</span> אב־הטיפוס הזה הוא המסך של החניכים, ולכן הכתובת לא מופיעה כאן.</p>
            <a href="?demo" className="mt-2 inline-block font-bold text-navy underline underline-offset-2">
              למסך החניך במצב הדגמה ←
            </a>
          </div>
          <button type="button" onClick={signOut} className="mt-4 text-sm underline">התנתקות</button>
        </Centered>
      );
    case "wrong_provider":
      return (
        <Centered>
          <p>הכניסה היא עם חשבון Google בלבד.</p>
          <button type="button" onClick={signOut} className="mt-4 text-sm underline">התנתקות</button>
        </Centered>
      );
    case "error":
      return <Centered><p className="text-late">משהו השתבש: {load.message}</p></Centered>;
    case "ok":
      return <HomeScreen home={load.home} today={today} onToggle={onToggle} />;
  }
}
