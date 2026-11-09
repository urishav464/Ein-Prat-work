// The workfile (תיק המשמר) — one evening whole: who and when, the task board,
// the evening's structure (Evening.tsx), its logistics and its after-work —
// every one of them to work on, through the doors. A port of
// app._workfile_body: the same phases, the same task rules, the same names.
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import demoWorkfile from "./demo_workfile.json";
import { demoApply } from "./demoEdits";
import { EveningTab, TopicCard, TopicLine, UploadButton, type Editor } from "./Evening";
import {
  PER_MISHMAR_BUDGET_NIS, PHASES, TASK_CATEGORIES, budgetSpeakers, clean, countdown, deadline, fmtDate, fmtNis,
  isChavurot, isFeedbackTask, localToday, parseDate, phaseOf, progress, slotLabel, slotNames, slotTimes,
  type Lesson, type LogisticsItem, type Progress, type Status, type Task, type Workfile,
} from "./model";
import {
  NOT_SAVED, describe, refusal, type BudgetEntry, type FeedbackEntry, type StructureAnswer, type StructureCall,
} from "./structure";
import { demoMode, supabase } from "./supabase";
import {
  DEMO_INVITATION, DEMO_UPLOAD, IMAGE_ACCEPT, UPLOAD_FAILED, checkFile, uploadRefusal, type Target, type UploadAnswer,
} from "./uploads";
import { Card, Centered, CheckButton, Chip, H2, Shell, Stepper, safeUrl, type Preview } from "./ui";

type Tab = "tasks" | "evening" | "logistics" | "after";

type WfLoad =
  | { kind: "loading" }
  | { kind: "ok"; wf: Workfile }
  | { kind: "missing" }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

// a database whose v2.sql predates stage 2ג answers without these: the
// screen draws empty lists rather than breaking
function complete(wf: Workfile): Workfile {
  return {
    ...wf, feedback: wf.feedback ?? [], budget: wf.budget ?? [],
    mishmar: { ...wf.mishmar, budget_used: Number(wf.mishmar.budget_used ?? 0) },
  };
}

// One fetch per evening opened. The demo has one evening bundled (#05).
function useWorkfile(mid: number): [WfLoad, (fn: (wf: Workfile) => Workfile) => void] {
  const [load, setLoad] = useState<WfLoad>({ kind: "loading" });
  useEffect(() => {
    let alive = true;
    if (demoMode || !supabase) {
      const wf = complete(demoWorkfile as unknown as Workfile);
      setLoad(wf.mishmar.id === mid ? { kind: "ok", wf } : { kind: "missing" });
      return;
    }
    setLoad({ kind: "loading" });
    supabase.rpc("v2_workfile", { p_mishmar_id: mid }).then(({ data, error }) => {
      if (!alive) return;
      if (error) return setLoad({ kind: "error", message: error.message });
      const status = (data as { status?: string } | null)?.status;
      if (status === "ok") return setLoad({ kind: "ok", wf: complete(data as Workfile) });
      setLoad(status === "not_found" ? { kind: "missing" } : { kind: "forbidden" });
    });
    return () => { alive = false; };
  }, [mid]);
  const update = (fn: (wf: Workfile) => Workfile) =>
    setLoad((l) => (l.kind === "ok" ? { kind: "ok", wf: fn(l.wf) } : l));
  return [load, update];
}

export default function WorkfileScreen({ mid, preview }: { mid: number; preview?: Preview }) {
  const [load, update] = useWorkfile(mid);
  if (load.kind === "loading") return <Centered><p className="text-muted">טוען…</p></Centered>;
  if (load.kind !== "ok") {
    const text = load.kind === "missing" ? (demoMode ? "בהדגמה יש תיק משמר מלא רק למשמר #05." : "המשמר הזה לא נמצא.")
      : load.kind === "forbidden" ? "זה לא אחד מהמשמרים שלך."
      : `משהו השתבש: ${load.message}`;
    return (
      <Centered>
        <p>{text}</p>
        <a href={demoMode ? "#/m/5" : "#/"} className="mt-4 inline-block font-bold text-navy underline underline-offset-2">
          {demoMode ? "לתיק של משמר #05 ←" : "למסך הבית ←"}
        </a>
      </Centered>
    );
  }
  return <WorkfileBody wf={load.wf} update={update} preview={preview} />;
}

function WorkfileBody({ wf, update, preview }: {
  wf: Workfile; update: (fn: (wf: Workfile) => Workfile) => void; preview?: Preview;
}) {
  const [tab, setTab] = useState<Tab>("tasks");
  const [focus, setFocus] = useState<number | null>(null);
  const [alert, setAlert] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  useEffect(() => {
    if (!alert && !notice) return;
    const timer = setTimeout(() => { setAlert(null); setNotice(null); }, 6000);
    return () => clearTimeout(timer);
  }, [alert, notice]);
  // a door to a slot lands on it once its tab has drawn
  useEffect(() => {
    if (tab !== "evening" || focus === null) return;
    document.getElementById(`slot-${focus}`)?.scrollIntoView({ block: "start" });
    setFocus(null);
  }, [tab, focus]);

  const m = wf.mishmar;
  const readOnly = wf.viewer === "instructor";
  const today = useMemo(() => (demoMode ? parseDate(wf.as_of) ?? localToday() : localToday()), [wf.as_of]);
  const prog = useMemo(() => progress(m, wf.tasks), [m, wf.tasks]);
  const slots = useMemo(() => wf.lessons.filter((l) => !l.is_break), [wf.lessons]);

  // ---- writes: the screen changes first for ✓ (as on the home); an add or
  // an edit waits for the database's answer, which carries the derived fields
  const queue = useRef(new Map<number, Promise<void>>());
  const setTasks = (fn: (ts: Task[]) => Task[]) => update((w) => ({ ...w, tasks: fn(w.tasks) }));
  const setStatus = (id: number, status: Status, onlyIf?: Status) =>
    setTasks((ts) => ts.map((x) => (x.id === id && (onlyIf === undefined || x.status === onlyIf) ? { ...x, status } : x)));

  // while a change to the structure is on its way, a ✓ waits — its answer
  // redraws the whole evening, tasks included
  const onToggle = readOnly || busy ? undefined : (t: Task) => {
    const next: Status = t.status === "DONE" ? "IN PROGRESS" : "DONE";
    setAlert(null);
    setStatus(t.id, next);
    if (demoMode || !supabase) return;
    const sb = supabase;
    const job = (queue.current.get(t.id) ?? Promise.resolve()).then(async () => {
      const { data, error } = await sb.rpc("v2_set_task_status", { p_task_id: t.id, p_status: next });
      if (error || (data as { status?: string } | null)?.status !== "ok") {
        setStatus(t.id, t.status, next);
        setAlert("הסימון לא נשמר. בדקו את החיבור ונסו שוב.");
      }
    });
    queue.current.set(t.id, job);
  };

  const onAdd = async (text: string, category: string | null): Promise<boolean> => {
    setAlert(null);
    if (demoMode || !supabase) {
      setTasks((ts) => [...ts, {
        id: -Date.now(), mishmar_id: m.id, task_description: text, status: "TO DO",
        category, due_date: null, details: null, lesson_id: null,
      }]);
      return true;
    }
    const { data, error } = await supabase.rpc("v2_add_task", { p_mishmar_id: m.id, p_text: text, p_category: category });
    const res = data as { status?: string; task?: Task } | null;
    if (error || res?.status !== "ok" || !res.task) {
      setAlert("המשימה לא נוספה. בדקו את החיבור ונסו שוב.");
      return false;
    }
    const added = res.task;
    setTasks((ts) => [...ts, added]);
    return true;
  };

  const onSave = async (t: Task, patch: { text: string; details: string; due: string; lesson: number | null }) => {
    setAlert(null);
    if (demoMode || !supabase) {
      setTasks((ts) => ts.map((x) => (x.id !== t.id ? x : {
        ...x, task_description: patch.text.trim() || x.task_description, details: patch.details.trim() || null,
        due_date: patch.due || x.due_date, lesson_id: patch.lesson,
      })));
      return true;
    }
    const { data, error } = await supabase.rpc("v2_edit_task", {
      p_task_id: t.id, p_text: patch.text, p_details: patch.details, p_due_date: patch.due || null, p_lesson_id: patch.lesson,
    });
    const res = data as { status?: string; task?: Task } | null;
    if (error || res?.status !== "ok" || !res.task) {
      setAlert("השינוי לא נשמר. בדקו את החיבור ונסו שוב.");
      return false;
    }
    const saved = res.task;
    setTasks((ts) => ts.map((x) => (x.id === t.id ? saved : x)));
    return true;
  };

  const onDelete = async (t: Task) => {
    if (!window.confirm(`למחוק את המשימה «${clean(t.task_description)}»?`)) return;
    setAlert(null);
    if (!demoMode && supabase) {
      const { data, error } = await supabase.rpc("v2_delete_task", { p_task_id: t.id });
      if (error || (data as { status?: string } | null)?.status !== "ok") {
        setAlert("המשימה לא נמחקה. בדקו את החיבור ונסו שוב.");
        return;
      }
    }
    setTasks((ts) => ts.filter((x) => x.id !== t.id));
  };

  // ---- the evening's structure: one door per change, one change at a time.
  // The answer is the whole evening, reconciled with its tasks by the
  // database, and the screen is redrawn from it. In the demo the same change
  // is made on the screen only (demoEdits.ts).
  const run = async (call: StructureCall): Promise<boolean> => {
    if (busy) return false;
    setAlert(null);
    setNotice(null);
    let answer: StructureAnswer | null;
    if (demoMode || !supabase) {
      answer = demoApply(wf, call);
    } else {
      setBusy(true);
      try {
        await Promise.all([...queue.current.values()]);          // a ✓ on its way lands first
        const { data, error } = await supabase.rpc(call.door, call.args);
        answer = error ? null : (data as StructureAnswer | null);
      } catch {
        answer = null;
      } finally {
        setBusy(false);
      }
    }
    if (!answer) {
      setAlert(NOT_SAVED);
      return false;
    }
    if (answer.status !== "ok" || !answer.workfile) {
      setAlert(refusal(answer.status, call.door));
      return false;
    }
    const next = complete(answer.workfile);
    const said = describe(call, wf, answer.result ?? {});
    update(() => next);
    if (said.warning) setAlert(said.warning);
    else if (said.notice) setNotice(said.notice);
    return true;
  };

  // ---- a source sheet as a file: the v2-tools function stores it and answers
  // with its public link, which the caller then saves through a door. The
  // function asks the database who is calling, as every door does.
  const upload = async (target: Target, id: number, file: File): Promise<string | null> => {
    if (busy) return null;
    setAlert(null);
    setNotice(null);
    const checked = checkFile(file.name, file.size, target);
    if (!checked.ok) {
      setAlert(uploadRefusal(checked.status, target));
      return null;
    }
    if (demoMode || !supabase) {
      setNotice(target === "invitation" ? DEMO_INVITATION : DEMO_UPLOAD);
      return null;
    }
    const form = new FormData();
    form.set("action", "upload");
    form.set("mishmar", String(m.id));
    form.set("target", target);
    form.set("id", String(id));
    form.set("file", file);
    let answer: UploadAnswer | null;
    setBusy(true);
    try {
      const { data, error } = await supabase.functions.invoke("v2-tools", { body: form });
      answer = error ? null : (data as UploadAnswer | null);
    } catch {
      answer = null;
    } finally {
      setBusy(false);
    }
    if (!answer) {
      setAlert(target === "invitation" ? uploadRefusal("unavailable", target) : UPLOAD_FAILED);
      return null;
    }
    if (answer.status !== "ok" || !answer.url) {
      setAlert(uploadRefusal(answer.status, target));
      return null;
    }
    return answer.url;
  };
  const editor: Editor = readOnly ? null : { run, upload, busy };

  // «פתח ↗» — to where the task is done (app._wf_task_card's door)
  const onOpen = (t: Task) => {
    if (t.lesson_id && slots.some((l) => l.id === t.lesson_id)) {
      setTab("evening");
      setFocus(t.lesson_id);
    } else if (["מרצים", "תוכן", "נושא"].includes(t.category ?? "")) {
      setTab("evening");
      window.scrollTo(0, 0);
    } else if (t.category === "אחרי") {
      setTab("after");
      window.scrollTo(0, 0);
    } else {
      setTab("logistics");
      window.scrollTo(0, 0);
    }
  };

  const actions = readOnly ? null : { onEdit: setEditing, onDelete };
  return (
    <Shell name={wf.viewer} alert={alert} notice={notice} preview={preview}>
      <a href="#/" className="text-sm font-bold text-navy underline underline-offset-2">→ למסך הבית</a>
      {readOnly && !preview && (
        <p className="mt-3 rounded-xl bg-navy-soft px-4 py-2 text-sm text-navy" role="note">
          מצב מדריך — צפייה בלבד. השינויים נעשים על ידי הזוג.
        </p>
      )}
      <IdentityCard wf={wf} prog={prog} today={today} edit={editor} />
      {!m.topic && editor && <TopicCard wf={wf} edit={editor} />}

      <div role="tablist" aria-label="חלקי התיק" className="mt-6 grid grid-cols-4 gap-1 rounded-xl bg-sand p-1">
        {([["tasks", "המשימות"], ["evening", "הערב"], ["logistics", "לוגיסטיקה"], ["after", "משוב וסיכום"]] as [Tab, string][])
          .map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                    className={`rounded-lg px-1 py-2 text-sm font-bold leading-tight ${tab === k ? "bg-white text-navy shadow-sm" : "text-muted"}`}>
              {label}
            </button>
          ))}
      </div>

      {tab === "tasks" && (
        <TasksTab wf={wf} prog={prog} today={today} slots={slots} onToggle={onToggle} actions={actions}
                  onOpen={onOpen} onAdd={readOnly ? null : onAdd} />
      )}
      {tab === "evening" && <EveningTab wf={wf} today={today} onToggle={onToggle} edit={editor} />}
      {tab === "logistics" && <LogisticsTab wf={wf} edit={editor} onEvening={() => setTab("evening")} />}
      {tab === "after" && <AfterTab wf={wf} today={today} edit={editor} />}

      {editing && (
        <EditSheet t={editing} slots={slots} onClose={() => setEditing(null)}
                   onSave={async (patch) => { if (await onSave(editing, patch)) setEditing(null); }} />
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- the card on top

function IdentityCard({ wf, prog, today, edit }: { wf: Workfile; prog: Progress; today: Date; edit: Editor }) {
  const m = wf.mishmar;
  const cd = countdown(m, today);
  return (
    <Card className="mt-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="font-display text-2xl font-extrabold text-navy">🕯️ משמר #{String(m.id).padStart(2, "0")}</h1>
        <span className="text-muted">{m.gregorian_date} · {m.hebrew_date}</span>
      </div>
      <TopicLine wf={wf} edit={edit} />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {cd && <Chip kind={cd.kind}>{cd.text}</Chip>}
        {m.owners.length > 0 && <Chip kind="blue">👥 {m.owners.join(" · ")}</Chip>}
        {m.mishmar_type && <Chip kind="gold">{m.mishmar_type}</Chip>}
        {m.start_time && <Chip kind="gray"><span dir="ltr">{m.start_time}</span>&nbsp;פתיחה</Chip>}
      </div>
      {m.note && <p className="mt-2 text-sm text-muted">{clean(m.note)}</p>}
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
          {prog.nextTask.due_date && <span className="ms-2 text-sm text-muted">מומלץ עד {fmtDate(prog.nextTask.due_date)}</span>}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- tasks

type Actions = { onEdit: (t: Task) => void; onDelete: (t: Task) => void } | null;

function TasksTab({ wf, prog, today, slots, onToggle, actions, onOpen, onAdd }: {
  wf: Workfile; prog: Progress; today: Date; slots: Lesson[]; onToggle?: (t: Task) => void;
  actions: Actions; onOpen: (t: Task) => void; onAdd: ((text: string, category: string | null) => Promise<boolean>) | null;
}) {
  const byDue = (a: Task, b: Task) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999");
  const open = wf.tasks.filter((t) => t.status !== "DONE");
  const done = wf.tasks.filter((t) => t.status === "DONE");
  // what was done, in the order the evening is built — the same groups as
  // the open board above it, the day itself between logistics and after
  const doneGroups = [
    ...PHASES.slice(0, 3).map((p) => ({
      key: p.key, icon: p.icon, label: p.label,
      tasks: done.filter((t) => phaseOf(t) === p.key && t.category !== "יום המשמר"),
    })),
    { key: "day", icon: "🕯️", label: "יום המשמר עצמו", tasks: done.filter((t) => t.category === "יום המשמר") },
    { key: "after", icon: PHASES[3].icon, label: PHASES[3].label, tasks: done.filter((t) => phaseOf(t) === "after") },
  ].filter((g) => g.tasks.length).map((g) => ({ ...g, tasks: [...g.tasks].sort(byDue) }));
  const dayOf = open.filter((t) => t.category === "יום המשמר").sort(byDue);
  const evening = parseDate(wf.mishmar.gregorian_date);
  const onlyFeedback = evening && evening < today && open.every(isFeedbackTask);
  const row = (t: Task) => (
    <TaskRow key={t.id} t={t} today={today} slots={slots} onToggle={onToggle} actions={actions} onOpen={onOpen} />
  );
  return (
    <div className="mt-4 space-y-2">
      {onlyFeedback && <p className="text-sm text-muted">🌙 הערב התקיים — כל המשימות נסגרו, נשאר רק המשוב.</p>}
      {prog.phases.map((ph, i) => {
        const ts = ph.tasks.filter((t) => t.status !== "DONE" && t.category !== "יום המשמר").sort(byDue);
        if (!ts.length) return null;
        const late = ts.filter((t) => deadline(t, today).overdue).length;
        const state = i === prog.current ? "▸" : ph.complete ? "✓" : "🔒";
        return (
          <details key={ph.key} open={i === prog.current || late > 0} className="rounded-2xl border border-line bg-white">
            <summary className="flex items-center gap-2 px-4 py-3">
              <span className="chev text-muted" aria-hidden>‹</span>
              <span className="min-w-0 flex-1 font-bold">{state} {ph.icon} {ph.label} <span className="font-normal text-muted">({ts.length})</span></span>
              {late > 0 && <Chip kind="red">{late} באיחור</Chip>}
            </summary>
            <div className="space-y-2 px-3 pb-3">{ts.map(row)}</div>
          </details>
        );
      })}
      {dayOf.length > 0 && (
        <details className="rounded-2xl border border-line bg-white">
          <summary className="flex items-center gap-2 px-4 py-3">
            <span className="chev text-muted" aria-hidden>‹</span>
            <span className="font-bold">🕯️ יום המשמר עצמו <span className="font-normal text-muted">({dayOf.length})</span></span>
          </summary>
          <p className="px-4 pb-2 text-sm text-muted">הדברים שנעשים בערב עצמו — לא לוגיסטיקה מוקדמת.</p>
          <div className="space-y-2 px-3 pb-3">{dayOf.map(row)}</div>
        </details>
      )}
      {onAdd && <AddTaskForm onAdd={onAdd} />}
      {done.length > 0 && (
        <details className="rounded-2xl border border-line bg-white">
          <summary className="flex items-center gap-2 px-4 py-3">
            <span className="chev text-muted" aria-hidden>‹</span>
            <span className="font-bold">✅ בוצעו <span className="font-normal text-muted">({done.length})</span></span>
          </summary>
          <div className="space-y-3 px-3 pb-3">
            {doneGroups.map((g) => (
              <div key={g.key}>
                <p className="mb-1.5 text-sm font-bold text-muted">
                  {g.icon} {g.label} <span className="font-normal">({g.tasks.length})</span>
                </p>
                <div className="space-y-2">{g.tasks.map(row)}</div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function TaskRow({ t, today, slots, onToggle, actions, onOpen }: {
  t: Task; today: Date; slots: Lesson[]; onToggle?: (t: Task) => void; actions: Actions; onOpen: (t: Task) => void;
}) {
  const dl = deadline(t, today);
  const slotIndex = slots.findIndex((l) => l.id === t.lesson_id);
  const slot = slotIndex >= 0 ? slots[slotIndex] : null;
  // the invitation is designed and sent outside the app: nowhere for «פתח» to
  // lead (app._wf_task_card); the after-evening tasks lead to «משוב וסיכום»
  const door = t.status !== "DONE" && t.category !== "הזמנה";
  return (
    <div className="rounded-xl border border-line bg-white p-3" data-task={t.id}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold leading-snug">{clean(t.task_description)}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {t.category && <Chip kind="gold">{t.category}</Chip>}
            {dl.overdue && <Chip kind="red">באיחור</Chip>}
            {slot && <Chip kind="blue">🔗 {slotLabel(slot, slotIndex + 1)}</Chip>}
          </div>
          {t.details && <p className="mt-1 text-sm text-muted">{clean(t.details).slice(0, 160)}</p>}
          {(dl.nudge || t.due_date) && (
            <p className={`mt-1 text-sm ${dl.overdue ? "text-late" : "text-muted"}`}>
              🕒 {dl.nudge || `מומלץ עד ${fmtDate(t.due_date)}`}
            </p>
          )}
        </div>
        <CheckButton task={t} onToggle={onToggle} />
      </div>
      {(door || actions) && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2 text-sm">
          {door && (
            <button type="button" onClick={() => onOpen(t)} className="rounded-lg px-2 py-1 font-bold text-navy hover:bg-navy-soft">
              פתח ↗
            </button>
          )}
          {actions && (
            <>
              <button type="button" onClick={() => actions.onEdit(t)} aria-label={`עריכה: ${clean(t.task_description)}`}
                      className="ms-auto rounded-lg border border-line px-2 py-1 hover:bg-sand">✏️ עריכה</button>
              <button type="button" onClick={() => actions.onDelete(t)} aria-label={`מחיקה: ${clean(t.task_description)}`}
                      className="rounded-lg border border-line px-2 py-1 hover:bg-late-bg">🗑</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function AddTaskForm({ onAdd }: { onAdd: (text: string, category: string | null) => Promise<boolean> }) {
  const [text, setText] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    const ok = await onAdd(text.trim(), category || null);
    setBusy(false);
    if (ok) {
      setText("");
      setCategory("");
      setAdded(true);
    }
  };
  return (
    <form onSubmit={submit} className="rounded-2xl border border-dashed border-navy/40 bg-white p-3">
      <label className="block text-sm font-bold" htmlFor="new-task">➕ משימה חדשה</label>
      <div className="mt-2 flex flex-wrap gap-2">
        <input id="new-task" value={text} onChange={(e) => { setText(e.target.value); setAdded(false); }} maxLength={300}
               placeholder="מה צריך לעשות?" className="min-w-0 flex-[3_1_12rem] rounded-lg border border-line bg-[#fbfaf6] px-3 py-2" />
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="קטגוריה"
                className="flex-[1_1_8rem] rounded-lg border border-line bg-[#fbfaf6] px-2 py-2">
          <option value="">(אוטומטי)</option>
          {TASK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button type="submit" disabled={busy || !text.trim()}
                className="rounded-lg bg-navy px-4 py-2 font-bold text-white disabled:opacity-50">
          {busy ? "מוסיף…" : "הוסף"}
        </button>
      </div>
      {added && <p className="mt-2 text-sm text-[#137333]">נוספה משימה — שובצה לשלב לפי הקטגוריה.</p>}
    </form>
  );
}

function EditSheet({ t, slots, onClose, onSave }: {
  t: Task; slots: Lesson[]; onClose: () => void;
  onSave: (patch: { text: string; details: string; due: string; lesson: number | null }) => Promise<void>;
}) {
  const [text, setText] = useState(t.task_description);
  const [details, setDetails] = useState(t.details ?? "");
  const [due, setDue] = useState(t.due_date ?? "");
  const [lesson, setLesson] = useState<string>(t.lesson_id ? String(t.lesson_id) : "");
  const [busy, setBusy] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    await onSave({ text, details, due, lesson: lesson ? Number(lesson) : null });
    setBusy(false);
  };
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/30 sm:items-center" role="dialog"
         aria-modal="true" aria-label="עריכת משימה" onClick={onClose}>
      <form onSubmit={save} onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md space-y-3 rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:rounded-2xl">
        <p className="font-display text-lg font-extrabold text-navy">עריכת משימה</p>
        <label className="block text-sm font-bold">כותרת
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={300}
                 className="mt-1 w-full rounded-lg border border-line bg-[#fbfaf6] px-3 py-2 font-normal" />
        </label>
        <label className="block text-sm font-bold">תיאור
          <textarea value={details} onChange={(e) => setDetails(e.target.value)} rows={3} maxLength={2000}
                    className="mt-1 w-full rounded-lg border border-line bg-[#fbfaf6] px-3 py-2 font-normal" />
        </label>
        <label className="block text-sm font-bold">מומלץ עד
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
                 className="mt-1 w-full rounded-lg border border-line bg-[#fbfaf6] px-3 py-2 font-normal" />
        </label>
        {slots.length > 0 && (
          <label className="block text-sm font-bold">שייך למקטע בערב
            <select value={lesson} onChange={(e) => setLesson(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-line bg-[#fbfaf6] px-2 py-2 font-normal">
              <option value="">— לא שייך למקטע —</option>
              {slots.map((l, i) => <option key={l.id} value={l.id}>{slotLabel(l, i + 1)}</option>)}
            </select>
          </label>
        )}
        <div className="flex gap-2 pt-1">
          <button type="submit" disabled={busy} className="flex-1 rounded-lg bg-navy px-4 py-2 font-bold text-white disabled:opacity-50">
            {busy ? "שומר…" : "💾 שמור"}
          </button>
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2">ביטול</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- logistics

// a card that opens with its heading: the heading's top margin is the card's padding
const SECTION = "[&>h2:first-child]:mt-1";
const FIELD = "rounded-lg border border-line bg-[#fbfaf6] px-3 py-2";
const PRIMARY = "rounded-lg bg-navy px-4 py-2 font-bold text-white disabled:opacity-50";
const ICON_BOX = "grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-white hover:bg-late-bg disabled:opacity-50";

// app._logistics_panel: what to buy, which room each חבורה sits in (derived
// from the presenters — edited in the evening's structure), the invitation
function LogisticsTab({ wf, edit, onEvening }: { wf: Workfile; edit: Editor; onEvening: () => void }) {
  const food = wf.logistics.filter((i) => i.kind === "כיבוד");
  const other = wf.logistics.filter((i) => i.kind !== "כיבוד" && i.kind !== "חלל");
  const legacyRooms = wf.logistics.filter((i) => i.kind === "חלל");
  const rounds = wf.lessons.filter((l) => !l.is_break && isChavurot(l));
  const names = slotNames(wf.lessons);
  const invitation = safeUrl(wf.mishmar.invitation_url);
  const [label, setLabel] = useState("");
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit || !label.trim()) return;
    if (await edit.run({ door: "v2_add_logistics", args: { p_mishmar_id: wf.mishmar.id, p_label: label } })) setLabel("");
  };
  const remove = (i: LogisticsItem) => {
    if (edit && window.confirm(`להסיר את «${i.label}» מהרשימה?`)) {
      edit.run({ door: "v2_delete_logistics", args: { p_item_id: i.id } });
    }
  };
  const row = (i: LogisticsItem, checkable = true) => (
    <li key={i.id} className="flex items-center gap-2" data-logistics={i.id}>
      {checkable && (
        <button type="button" disabled={!edit || edit.busy} aria-pressed={i.done}
                aria-label={`${i.done ? "בטל סימון" : "סמן שנקנה"}: ${i.label}`}
                onClick={() => edit?.run({ door: "v2_set_logistics_done", args: { p_item_id: i.id, p_done: !i.done } })}
                className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border
                  ${i.done ? "border-navy bg-navy text-white" : "border-navy/40 bg-white text-navy hover:bg-navy-soft"}
                  disabled:cursor-not-allowed disabled:opacity-40`}>✓</button>
      )}
      <span className={`min-w-0 flex-1 ${i.done ? "text-muted line-through" : ""}`}>
        {i.label}{i.detail ? <span className="text-sm text-muted"> — {i.detail}</span> : null}
      </span>
      {edit && (
        <button type="button" disabled={edit.busy} onClick={() => remove(i)} aria-label={`הסרה: ${i.label}`}
                className={ICON_BOX}>🗑</button>
      )}
    </li>
  );
  const removeInvitation = () => {
    if (edit && window.confirm("להסיר את ההזמנה מהתיק?")) {
      edit.run({ door: "v2_set_invitation", args: { p_mishmar_id: wf.mishmar.id, p_url: "" } });
    }
  };
  return (
    <div className="mt-4 space-y-3">
      <Card className={SECTION}>
        <H2>🍎 רשימת הכיבוד</H2>
        <p className="mb-2 text-sm text-muted">מה קונים לערב. סימון ✓ = נקנה.</p>
        {food.length ? <ul className="space-y-2">{food.map((i) => row(i))}</ul>
          : <p className="text-muted">הרשימה עוד ריקה.</p>}
        {edit && (
          <form onSubmit={add} className="mt-3 flex flex-wrap gap-2">
            <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={300} aria-label="פריט לכיבוד"
                   placeholder="למשל: עוגות · פיצוחים · שתייה חמה" className={`min-w-0 flex-[3_1_12rem] ${FIELD}`} />
            <button type="submit" disabled={edit.busy || !label.trim()} className={PRIMARY}>➕ הוסף</button>
          </form>
        )}
      </Card>
      <Card className={SECTION}>
        <H2>🚪 חלוקת החללים לחבורות</H2>
        <p className="mb-2 text-sm text-muted">נגזר ממעבירי החבורות במבנה הערב — כל מעביר וחלל אחד, בתוך הסבב שלו.</p>
        {rounds.some((l) => l.people.length) ? rounds.map((l) => {
          const used = l.people.map((p) => p.room).filter(Boolean);
          return (
            <div key={l.id} className="mb-2">
              {rounds.length > 1 && <p className="text-sm text-muted">🕘 <span dir="ltr">{slotTimes(l)}</span> · {names.get(l.id)}</p>}
              <ul className="space-y-1">
                {l.people.map((p) => (
                  <li key={p.id}>
                    <span className="font-semibold">{p.room ?? "טרם נקבע חלל"}</span> — {p.name}
                    {p.room && used.filter((r) => r === p.room).length > 1 && (
                      <span className="text-sm text-late"> ⚠️ אותו חלל לשניים בסבב הזה</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        }) : <p className="text-muted">אין עדיין מעבירי חבורות. מוסיפים אותם במבנה הערב.</p>}
        <button type="button" onClick={() => { onEvening(); window.scrollTo(0, 0); }}
                className="mt-1 rounded-lg px-2 py-1 text-sm font-bold text-navy hover:bg-navy-soft">↗ למבנה הערב</button>
        {legacyRooms.length > 0 && (
          <details className="mt-3 rounded-xl border border-line px-3 py-2">
            <summary className="text-sm font-bold text-muted">שורות חללים ישנות ({legacyRooms.length})</summary>
            <p className="my-2 text-sm text-muted">נרשמו כשהחללים היו רשימה חופשית. אפשר למחוק אותן.</p>
            <ul className="space-y-2">{legacyRooms.map((i) => row(i, false))}</ul>
          </details>
        )}
      </Card>
      <Card className={SECTION}>
        <H2>✉️ ההזמנה למשמר</H2>
        <p className="mb-2 text-sm text-muted">ההזמנה היא תמונה אחת — הפוסטר שיוצא בוואטסאפ. מעלים אותה כאן.</p>
        {invitation ? <img src={invitation} alt="ההזמנה למשמר" className="max-h-[28rem] w-auto max-w-full rounded-xl border border-line" />
          : <p className="text-muted">עוד לא הועלתה הזמנה.</p>}
        {edit && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <UploadButton target="invitation" id={wf.mishmar.id} edit={edit} accept={IMAGE_ACCEPT}
                          label="העלאת תמונת ההזמנה" text={invitation ? "📤 החלפת התמונה" : "📤 העלאת ההזמנה"}
                          onUploaded={(url) => edit.run({ door: "v2_set_invitation",
                                                          args: { p_mishmar_id: wf.mishmar.id, p_url: url } })} />
            {invitation && (
              <button type="button" disabled={edit.busy} onClick={removeInvitation}
                      className="rounded-lg border border-line px-2 py-1 text-sm hover:bg-late-bg disabled:opacity-50">
                🗑 הסרת ההזמנה
              </button>
            )}
          </div>
        )}
      </Card>
      {other.length > 0 && <Card className={SECTION}><H2>📦 עוד</H2><ul className="space-y-2">{other.map((i) => row(i))}</ul></Card>}
    </div>
  );
}

// ---------------------------------------------------------------- after the evening

// app._after_tab: a rating per slot, then the budget
function AfterTab({ wf, today, edit }: { wf: Workfile; today: Date; edit: Editor }) {
  return (
    <div className="mt-4 space-y-3">
      <FeedbackCard wf={wf} today={today} edit={edit} />
      <BudgetCard wf={wf} edit={edit} />
    </div>
  );
}

function Stars({ value, onChange, name, disabled }: {
  value: number | null; onChange: (v: number | null) => void; name: string; disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={`דירוג: ${name}`} className="flex shrink-0 gap-0.5" dir="ltr">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} disabled={disabled}
                aria-label={n === 1 ? "כוכב אחד" : `${n} כוכבים`}
                // the same star again clears it: unrated is not a 1
                onClick={() => onChange(value === n ? null : n)}
                className={`grid h-9 w-8 place-items-center rounded-md text-xl leading-none hover:bg-navy-soft disabled:opacity-40
                  ${value !== null && n <= value ? "text-[#c58b00]" : "text-line"}`}>
          ★
        </button>
      ))}
    </div>
  );
}

function FeedbackCard({ wf, today, edit }: { wf: Workfile; today: Date; edit: Editor }) {
  const slots = wf.lessons.filter((l) => !l.is_break);
  const names = slotNames(wf.lessons);
  const mine = new Set(wf.feedback.filter((f) => f.mine).map((f) => f.lesson_title));
  const evening = parseDate(wf.mishmar.gregorian_date);
  const open = !evening || evening <= today;
  const [stars, setStars] = useState<Record<number, number | null>>({});
  const [words, setWords] = useState<Record<number, string>>({});
  const rated = slots.filter((l) => stars[l.id] && !mine.has(names.get(l.id) ?? ""));
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    const entries: FeedbackEntry[] = slots
      .filter((l) => !mine.has(names.get(l.id) ?? ""))
      .map((l) => ({ lesson_id: l.id, rating: stars[l.id] ?? null, what_worked: (words[l.id] ?? "").trim() || null }));
    if (await edit.run({ door: "v2_add_feedback", args: { p_mishmar_id: wf.mishmar.id, p_entries: entries } })) {
      setStars({});
      setWords({});
    }
  };
  return (
    <Card className={SECTION}>
      <H2>🌙 משוב על הערב — לפי מקטעים</H2>
      <p className="mb-3 text-sm text-muted">
        המשוב נשמר על שמך ועל המשמר הזה, והופך את מאגר המרצים לזיכרון מוסדי. דרגו רק מקטעים שהייתם
        בהם — מקטע בלי כוכבים לא נשמר. שליחה גם סוגרת את משימת המשוב.
      </p>
      {!open ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-3 text-muted">
          המשוב נפתח ביום הערב. אז אפשר לדרג כל מקטע ולכתוב מה עבד.
        </p>
      ) : !slots.length ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-3 text-muted">
          אין עדיין מבנה ערב. המשוב ייפתח כשיהיו מקטעים.
        </p>
      ) : edit ? (
        <form onSubmit={send} className="space-y-3" aria-label="משוב על הערב">
          {slots.map((l) => {
            const name = names.get(l.id) ?? "מקטע";
            const sent = mine.has(name);
            return (
              <div key={l.id} className="rounded-xl border border-line p-3" data-feedback-slot={l.id}>
                <p className="font-semibold">
                  {name}
                  {l.speaker_name && <span className="font-normal text-muted"> · 🎤 {l.speaker_name}</span>}
                  {sent && <span className="ms-1"><Chip kind="green">✅ כבר נשלח</Chip></span>}
                </p>
                {!sent && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Stars value={stars[l.id] ?? null} name={name} disabled={edit.busy}
                           onChange={(v) => setStars((s) => ({ ...s, [l.id]: v }))} />
                    <input value={words[l.id] ?? ""} onChange={(e) => setWords((w) => ({ ...w, [l.id]: e.target.value }))}
                           maxLength={2000} aria-label={`התייחסות: ${name}`} placeholder="התייחסות — מה עבד, מה פחות"
                           className={`min-w-0 flex-[1_1_12rem] ${FIELD}`} />
                  </div>
                )}
              </div>
            );
          })}
          <button type="submit" disabled={edit.busy || !rated.length} className={PRIMARY}>💾 שמור משוב על הערב</button>
        </form>
      ) : null}
      {wf.feedback.length > 0 && (
        <details className="mt-3 rounded-xl border border-line px-3 py-2">
          <summary className="text-sm font-bold">משוב שנרשם ({wf.feedback.length})</summary>
          <ul className="mt-2 space-y-2">
            {wf.feedback.map((f) => (
              <li key={f.id}>
                <span className="font-semibold">{f.lesson_title || f.speaker_name || "המשמר בכללותו"}</span>
                {" — "}<span aria-label={`${f.rating ?? 0} כוכבים`}>{"⭐".repeat(f.rating ?? 0)}</span>
                {f.mine && <span className="text-sm text-muted"> (שלך)</span>}
                {f.what_worked && <p className="text-sm text-muted">{clean(f.what_worked)}</p>}
                {f.what_didnt && <p className="text-sm text-muted">פחות: {clean(f.what_didnt)}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function BudgetCard({ wf, edit }: { wf: Workfile; edit: Editor }) {
  const paid = new Set(wf.budget.filter((b) => b.expense_type === "מרצה").map((b) => (b.description ?? "").trim()));
  const unpaid = budgetSpeakers(wf).filter((n) => !paid.has(n));
  const [pay, setPay] = useState<Record<string, string>>({});
  const [extraName, setExtraName] = useState("");
  const [extraSum, setExtraSum] = useState("");
  const [food, setFood] = useState("");
  const [other, setOther] = useState("");
  const spent = Number(wf.mishmar.budget_used ?? 0);
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const lines: BudgetEntry[] = [
    ...unpaid.filter((n) => num(pay[n] ?? "") !== null)
      .map((n) => ({ expense_type: "מרצה" as const, description: n, actual_cost: num(pay[n])! })),
    ...(extraName.trim() ? [{ expense_type: "מרצה" as const, description: extraName.trim(), actual_cost: num(extraSum) ?? 0 }] : []),
    ...(num(food) ? [{ expense_type: "כיבוד" as const, description: "", actual_cost: num(food)! }] : []),
    ...(num(other) ? [{ expense_type: "אחר" as const, description: "", actual_cost: num(other)! }] : []),
  ];
  const bad = lines.some((l) => !Number.isFinite(l.actual_cost) || l.actual_cost < 0);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit || !lines.length || bad) return;
    if (await edit.run({ door: "v2_add_budget", args: { p_mishmar_id: wf.mishmar.id, p_lines: lines } })) {
      setPay({});
      setExtraName("");
      setExtraSum("");
      setFood("");
      setOther("");
    }
  };
  const remove = (id: number, what: string) => {
    if (edit && window.confirm(`למחוק את השורה «${what}» מהתקציב?`)) {
      edit.run({ door: "v2_delete_budget", args: { p_line_id: id } });
    }
  };
  const money = (value: string, set: (v: string) => void, label: string) => (
    <input type="number" inputMode="decimal" min={0} step={10} value={value} onChange={(e) => set(e.target.value)}
           aria-label={label} placeholder="₪" className={`w-28 ${FIELD}`} dir="ltr" />
  );
  return (
    <Card className={SECTION}>
      <H2>💰 סיכום תקציב</H2>
      <p className="mb-3 text-sm text-muted">
        האינדיקציה היא {PER_MISHMAR_BUDGET_NIS} ₪ למשמר — ממוצע שכולל מרצים וכיבוד יחד. חריגה במשמר בודד
        אינה שגיאה: היא נמשכת מהסעיף העונתי.
      </p>
      {wf.budget.length > 0 ? (
        <ul className="space-y-2" aria-label="שורות התקציב">
          {wf.budget.map((b) => (
            <li key={b.id} className="flex items-center gap-2" data-budget={b.id}>
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{b.expense_type === "מרצה" ? b.description : b.expense_type}</span>
                {b.expense_type === "מרצה" && <span className="text-sm text-muted"> · מרצה</span>}
              </span>
              <span className="tabular-nums" dir="ltr">
                {Number(b.actual_cost) === 0 && b.expense_type === "מרצה" ? "בהתנדבות" : fmtNis(Number(b.actual_cost))}
              </span>
              {edit && (
                <button type="button" disabled={edit.busy} onClick={() => remove(b.id, b.description ?? b.expense_type)}
                        aria-label={`מחיקת שורה: ${b.description ?? b.expense_type}`} className={ICON_BOX}>🗑</button>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="text-muted">עוד לא נרשמו הוצאות.</p>}
      <p className="mt-3 border-t border-line pt-3 font-bold">
        סה״כ הוצאות למשמר הזה: <span className="tabular-nums" dir="ltr">{fmtNis(spent)}</span>
      </p>
      {spent > PER_MISHMAR_BUDGET_NIS && <p className="text-sm text-muted">מעל האינדיקציה — לידיעה, לא לדאגה.</p>}
      {edit && (
        <form onSubmit={save} className="mt-4 space-y-3 rounded-xl border border-dashed border-navy/40 p-3" aria-label="הוספה לתקציב">
          <p className="text-sm font-bold">מרצים שהגיעו ומה שולם להם <span className="font-normal text-muted">(0 = הגיע בהתנדבות · שדה ריק לא נשמר)</span></p>
          {unpaid.length ? unpaid.map((n) => (
            <label key={n} className="flex flex-wrap items-center justify-between gap-2">
              <span>{n}</span>
              {money(pay[n] ?? "", (v) => setPay((p) => ({ ...p, [n]: v })), `תשלום ל${n}`)}
            </label>
          )) : (
            <p className="text-sm text-muted">
              {budgetSpeakers(wf).length ? "לכל המרצים של הערב כבר יש שורה." : "לא רשומים מרצים במבנה הערב."}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input value={extraName} onChange={(e) => setExtraName(e.target.value)} maxLength={120}
                   aria-label="מרצה נוסף שלא מופיע למעלה" placeholder="מרצה נוסף שלא מופיע למעלה"
                   className={`min-w-0 flex-[1_1_10rem] ${FIELD}`} />
            {money(extraSum, setExtraSum, "תשלום למרצה הנוסף")}
          </div>
          <label className="flex flex-wrap items-center justify-between gap-2"><span>כיבוד</span>{money(food, setFood, "כיבוד (₪)")}</label>
          <label className="flex flex-wrap items-center justify-between gap-2"><span>הוצאות אחרות</span>{money(other, setOther, "הוצאות אחרות (₪)")}</label>
          {bad && <p className="text-sm text-late">סכום צריך להיות 0 ₪ או יותר.</p>}
          <button type="submit" disabled={edit.busy || !lines.length || bad} className={PRIMARY}>💾 שמור סיכום תקציב</button>
        </form>
      )}
    </Card>
  );
}
