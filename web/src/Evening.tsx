// The evening — its slots on the clock and the people on each — and, since
// stage 2ב, the editors: everything the Streamlit workfile's «מבנה הערב»
// panel does (app._topic_and_structure, _lesson_edit_dialog, _candidate_rows,
// _panel_rows, _chavurot_rows), through the doors in web/supabase/v2.sql.
// A write waits for the database, whose answer is the whole evening —
// reconciled with its tasks — and the screen is drawn from that answer.
import { useState, type FormEvent } from "react";
import {
  CHAVUROT_ROOMS, CLOSED, DEFAULT_ROOM, DURATION_OPTIONS, LESSON_FORMATS, LESSON_ROLES, SPEAKER_STATUSES,
  clean, deadline, isChavurot, isPanel, slotNames, slotTimes, type Lesson, type Person, type Task, type Workfile,
} from "./model";
import type { SlotKind, StructureCall } from "./structure";
import { demoMode } from "./supabase";
import { Card, CheckButton, Chip, safeUrl, type ChipKind } from "./ui";

// null: nothing on this screen writes (the instructor)
export type Editor = { run: (call: StructureCall) => Promise<boolean>; busy: boolean } | null;

const STATUS_KIND: Record<string, ChipKind> = {
  "✅ סגור": "green", "📩 נשלחה פנייה": "blue", "⚠️ בתנאי": "yellow", "❌ לא יכול/ה": "red", "⬜ לא פנינו": "gray",
};

const FIELD = "rounded-lg border border-line bg-[#fbfaf6] px-3 py-2 disabled:opacity-60";
const PRIMARY = "rounded-lg bg-navy px-3 py-2 text-sm font-bold text-white disabled:opacity-50";
const SECONDARY = "rounded-lg border border-line bg-white px-3 py-2 text-sm hover:bg-sand disabled:opacity-50";
const ICON = "grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-white hover:bg-late-bg disabled:opacity-50";
const HTTP = /^https?:\/\/\S+$/i;

// a list plus the value a row already holds, when the list does not have it:
// a role typed in the archive's days stays as it is
function withCurrent<T>(list: T[], current: T | null | undefined): T[] {
  if (current === null || current === undefined || (current as unknown) === "" || list.includes(current)) return list;
  return [current, ...list];
}

// ---------------------------------------------------------------- the topic

// «הצעד הראשון: לסגור נושא» — app._topic_and_structure's hero form
export function TopicCard({ wf, edit }: { wf: Workfile; edit: NonNullable<Editor> }) {
  const [topic, setTopic] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    if (await edit.run({ door: "v2_set_topic", args: { p_mishmar_id: wf.mishmar.id, p_topic: topic.trim() } })) setTopic("");
  };
  return (
    <Card className="mt-3 border-navy/40">
      <p className="font-display text-lg font-extrabold text-navy">הצעד הראשון: לסגור נושא</p>
      <p className="mt-1 text-sm text-muted">
        הנושא הוא מנוע הערב כולו — מומלץ לסגור אותו כשלושה שבועות לפני. אין רעיון? בדקו בארכיון אם היה משמר דומה, ודברו עם המדריך.
        {!wf.lessons.length && ` הסגירה בונה את שלד הערב: שלושה שיעורים, הפסקות ושעת חבורות, מ-${wf.mishmar.start_time || "20:00"}.`}
      </p>
      <form onSubmit={submit} className="mt-3 flex flex-wrap gap-2">
        <input id="topic-new" aria-label="שם הנושא" value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200}
               placeholder="למשל: כרוניקה של שינוי — האם אדם יכול לשכתב את העבר?"
               className={`min-w-0 flex-[3_1_14rem] ${FIELD}`} />
        <button type="submit" disabled={edit.busy || !topic.trim()} className={PRIMARY}>🎯 סגירת הנושא</button>
      </form>
    </Card>
  );
}

// the topic in the card on top — with ✏️ for the pair once it is closed
export function TopicLine({ wf, edit }: { wf: Workfile; edit: Editor }) {
  const [open, setOpen] = useState(false);
  const [topic, setTopic] = useState("");
  const m = wf.mishmar;
  if (open && edit && m.topic) {
    const save = async (e: FormEvent) => {
      e.preventDefault();
      if (topic.trim() && await edit.run({ door: "v2_set_topic", args: { p_mishmar_id: m.id, p_topic: topic.trim() } })) setOpen(false);
    };
    return (
      <form onSubmit={save} className="mt-2 flex flex-wrap gap-2">
        <input aria-label="שם הנושא" value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200}
               className={`min-w-0 flex-[3_1_14rem] font-bold ${FIELD}`} />
        <button type="submit" disabled={edit.busy || !topic.trim()} className={PRIMARY}>💾 שמירה</button>
        <button type="button" onClick={() => setOpen(false)} className={SECONDARY}>ביטול</button>
      </form>
    );
  }
  return (
    <p className="mt-2 text-lg font-bold">
      {m.topic ?? <span className="font-normal text-muted">הנושא עוד לא נסגר</span>}
      {m.topic && edit && (
        <button type="button" aria-label="עריכת הנושא" disabled={edit.busy}
                onClick={() => { setTopic(m.topic ?? ""); setOpen(true); }}
                className="ms-2 rounded-lg border border-line px-2 py-0.5 align-middle text-sm font-normal hover:bg-sand">
          ✏️
        </button>
      )}
    </p>
  );
}

// ---------------------------------------------------------------- small pieces

export function Phone({ phone }: { phone: string | null }) {
  if (!phone) return null;
  const dial = phone.replace(/[^\d+]/g, "");
  return dial ? <a href={`tel:${dial}`} dir="ltr" className="text-sm font-semibold text-navy underline underline-offset-2">📞 {phone}</a> : null;
}

export function SheetLink({ url }: { url: string | null }) {
  const href = safeUrl(url);
  return href ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-navy underline underline-offset-2">📎 דף מקורות</a> : null;
}

// a phone: the number to dial, and for the pair a field behind ✏️
function PhoneField({ p, edit }: { p: Person; edit: Editor }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (open && edit) {
    const save = async (e: FormEvent) => {
      e.preventDefault();
      const ok = await edit.run({ door: "v2_edit_person", args: { p_person_id: p.id, p_phone: value.trim(), p_room: null, p_source_url: null } });
      if (ok) setOpen(false);
    };
    return (
      <form onSubmit={save} className="flex flex-wrap items-center gap-1">
        <input type="tel" dir="ltr" aria-label={`טלפון: ${p.name}`} value={value} maxLength={40}
               onChange={(e) => setValue(e.target.value)} className={`w-40 ${FIELD} py-1`} />
        <button type="submit" disabled={edit.busy} className={SECONDARY}>💾</button>
        <button type="button" onClick={() => setOpen(false)} className={SECONDARY}>ביטול</button>
      </form>
    );
  }
  return (
    <>
      <Phone phone={p.phone} />
      {edit && (
        <button type="button" disabled={edit.busy} onClick={() => { setValue(p.phone ?? ""); setOpen(true); }}
                aria-label={`עריכת טלפון: ${p.name}`} className="rounded-lg px-1.5 py-0.5 text-sm text-navy hover:bg-navy-soft disabled:opacity-50">
          {p.phone ? "✏️" : "＋ טלפון"}
        </button>
      )}
    </>
  );
}

// a presenter's own source sheet — a link, behind 📎 for the pair
function SheetField({ p, edit }: { p: Person; edit: NonNullable<Editor> }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const bad = value.trim() !== "" && !HTTP.test(value.trim());
  if (!open) {
    return (
      <button type="button" disabled={edit.busy} onClick={() => { setValue(p.source_url ?? ""); setOpen(true); }}
              aria-label={`דף מקורות: ${p.name}`} className="rounded-lg px-1.5 py-0.5 text-sm text-navy hover:bg-navy-soft disabled:opacity-50">
        {p.source_url ? "✏️ קישור" : "📎 קישור לדף מקורות"}
      </button>
    );
  }
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (bad) return;
    const ok = await edit.run({ door: "v2_edit_person", args: { p_person_id: p.id, p_phone: null, p_room: null, p_source_url: value.trim() } });
    if (ok) setOpen(false);
  };
  return (
    <form onSubmit={save} className="flex w-full flex-wrap items-center gap-1">
      <input type="url" dir="ltr" aria-label={`קישור לדף המקורות של ${p.name}`} value={value} placeholder="https://…"
             onChange={(e) => setValue(e.target.value)} className={`min-w-0 flex-[1_1_12rem] ${FIELD} py-1`} />
      <button type="submit" disabled={edit.busy || bad} className={SECONDARY}>💾</button>
      <button type="button" onClick={() => setOpen(false)} className={SECONDARY}>ביטול</button>
      {bad && <span className="w-full text-sm text-late">קישור צריך להתחיל ב-https://</span>}
    </form>
  );
}

// ---------------------------------------------------------------- people

// a candidate (a lesson) or a panelist: name, phone, status — and the close
function PersonRow({ p, l, kind, edit }: { p: Person; l: Lesson; kind: "lesson" | "panel"; edit: Editor }) {
  const status = p.status ?? SPEAKER_STATUSES[0];
  const closed = status === CLOSED;
  // a lesson is closed by its own button, which also removes the others — so
  // its list offers no ✅, and the button stays even on a row someone marked ✅
  // in the current app's list without closing the lesson
  const statuses = withCurrent(kind === "lesson" ? SPEAKER_STATUSES.filter((s) => s !== CLOSED) : SPEAKER_STATUSES, status);
  const canClose = kind === "lesson" || !closed;
  const setStatus = (s: string) => edit?.run({ door: "v2_set_person_status", args: { p_person_id: p.id, p_status: s } });
  const close = () => {
    const others = l.people.filter((x) => x.id !== p.id).length;
    if (kind === "lesson" && others
        && !window.confirm(`«${p.name}» ייסגר כמרצה של השיעור, ושאר המועמדים יוסרו מהרשימה. להמשיך?`)) return;
    setStatus(CLOSED);
  };
  const remove = () => {
    if (window.confirm(`להסיר את «${p.name}» מהרשימה?`)) {
      edit?.run({ door: "v2_remove_person", args: { p_person_id: p.id } });
    }
  };
  return (
    <li className="rounded-xl border border-line p-2" data-person={p.id}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1">🎤 <span className="font-semibold">{p.name}</span></span>
        {!edit && p.status && <Chip kind={STATUS_KIND[p.status] ?? "gray"}>{p.status}</Chip>}
        {edit && (
          <select aria-label={`סטטוס: ${p.name}`} value={status} disabled={edit.busy}
                  onChange={(e) => setStatus(e.target.value)} className={`${FIELD} py-1 text-sm`}>
            {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <PhoneField p={p} edit={edit} />
        {edit && (
          <span className="ms-auto flex gap-2">
            {canClose && (
              <button type="button" onClick={close} disabled={edit.busy} aria-label={`סגירה: ${p.name}`} className={PRIMARY}>
                ✅ סגירה
              </button>
            )}
            <button type="button" onClick={remove} disabled={edit.busy} aria-label={`הסרה: ${p.name}`} className={ICON}>🗑</button>
          </span>
        )}
      </div>
    </li>
  );
}

// the add form under a list: a candidate, a panelist, or a presenter with a room
function AddPerson({ l, kind, edit }: { l: Lesson; kind: "lesson" | "panel" | "chavurot"; edit: NonNullable<Editor> }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [room, setRoom] = useState(DEFAULT_ROOM);
  const add = async (close: boolean) => {
    const who = name.trim();
    if (!who) return;
    if (close && kind === "lesson" && l.people.length
        && !window.confirm(`«${who}» ייסגר כמרצה של השיעור, ושאר המועמדים יוסרו מהרשימה. להמשיך?`)) return;
    const ok = await edit.run({ door: "v2_add_person", args: {
      p_lesson_id: l.id, p_name: who, p_phone: kind === "chavurot" ? "" : phone.trim(),
      p_room: kind === "chavurot" ? room : "", p_close: close,
    } });
    if (ok) {
      setName("");
      setPhone("");
      setRoom(DEFAULT_ROOM);
    }
  };
  const label = kind === "chavurot" ? "שם המעביר" : kind === "panel" ? "שם מרצה לפאנל" : "שם מרצה אפשרי";
  return (
    <form onSubmit={(e) => { e.preventDefault(); add(false); }} data-add={l.id}
          className="mt-2 flex flex-wrap gap-2 rounded-xl border border-dashed border-navy/40 bg-white p-2">
      <input aria-label={label} placeholder={label} value={name} maxLength={120} onChange={(e) => setName(e.target.value)}
             className={`min-w-0 flex-[2_1_10rem] ${FIELD}`} />
      {kind === "chavurot" ? (
        <select aria-label="חלל" value={room} onChange={(e) => setRoom(e.target.value)} className={`flex-[1_1_8rem] ${FIELD}`}>
          {CHAVUROT_ROOMS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      ) : (
        <input type="tel" dir="ltr" aria-label="טלפון" placeholder="טלפון (רשות)" value={phone} maxLength={40}
               onChange={(e) => setPhone(e.target.value)} className={`min-w-0 flex-[1_1_8rem] ${FIELD}`} />
      )}
      <button type="submit" disabled={edit.busy || !name.trim()} className={SECONDARY}>
        {kind === "chavurot" ? "➕ מעביר" : kind === "panel" ? "➕ לפאנל" : "➕ מועמד"}
      </button>
      {kind !== "chavurot" && (
        <button type="button" onClick={() => add(true)} disabled={edit.busy || !name.trim()} className={PRIMARY}>
          ✅ הוספה וסגירה
        </button>
      )}
    </form>
  );
}

function Candidates({ l, edit }: { l: Lesson; edit: Editor }) {
  if (l.speaker_name) {
    const p = l.people.find((x) => x.name === l.speaker_name);
    const reopen = () => {
      if (window.confirm(`לשחרר את «${l.speaker_name}» ולחזור לרשימת המועמדים? מה שנרשם ביומן הפניות נשאר.`)) {
        edit?.run({ door: "v2_reopen_slot", args: { p_lesson_id: l.id } });
      }
    };
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>🎤 <span className="font-semibold">{l.speaker_name}</span></span>
        <Chip kind="green">✅ סגור</Chip>
        {p ? <PhoneField p={p} edit={edit} /> : null}
        {edit && (
          <button type="button" onClick={reopen} disabled={edit.busy} className={`ms-auto ${SECONDARY}`}
                  title="משחרר את המקטע וחוזר לרשימת המועמדים">
            🔄 החלפה
          </button>
        )}
      </div>
    );
  }
  return (
    <>
      {l.people.length
        ? <p className="text-sm font-bold">מרצים אופציונליים:</p>
        : <p className="text-sm text-muted">עוד אין מרצה ואין מועמדים.</p>}
      <ul className="space-y-2">
        {l.people.map((p) => <PersonRow key={p.id} p={p} l={l} kind="lesson" edit={edit} />)}
      </ul>
      {edit && <AddPerson l={l} kind="lesson" edit={edit} />}
    </>
  );
}

function Panelists({ l, edit }: { l: Lesson; edit: Editor }) {
  return (
    <>
      {l.people.length ? <p className="text-sm font-bold">מרצי הפאנל:</p> : <p className="text-sm text-muted">עוד לא נוספו מרצים לפאנל.</p>}
      {edit && (
        <p className="text-sm text-muted">כל מרצה נסגר בנפרד, ואף אחד לא מוסר כשאחר נסגר. משימת סגירת המרצה נסגרת כשכל מי שברשימה סגור.</p>
      )}
      <ul className="space-y-2">
        {l.people.map((p) => <PersonRow key={p.id} p={p} l={l} kind="panel" edit={edit} />)}
      </ul>
      {edit && <AddPerson l={l} kind="panel" edit={edit} />}
    </>
  );
}

// a round of חבורות is a LIST of presenters, each with a room and a sheet of
// their own — no «סגרנו» here (app._chavurot_rows)
function Presenters({ l, edit }: { l: Lesson; edit: Editor }) {
  const rooms = l.people.map((p) => p.room).filter(Boolean);
  return (
    <>
      {l.people.length ? <p className="text-sm font-bold">מעבירי החבורות:</p> : <p className="text-sm text-muted">עוד לא נוספו מעבירים.</p>}
      {edit && (
        <p className="text-sm text-muted">מעביר אחד — בבית המדרש. משני מעבירים, כל חלל נוסף מקבל משימת סידור משלו ליום המשמר.</p>
      )}
      <ul className="space-y-2">
        {l.people.map((p) => {
          const clash = !!p.room && rooms.filter((r) => r === p.room).length > 1;
          const remove = () => {
            if (window.confirm(`להסיר את «${p.name}» מהחבורות?`)) edit?.run({ door: "v2_remove_person", args: { p_person_id: p.id } });
          };
          return (
            <li key={p.id} className="rounded-xl border border-line p-2" data-person={p.id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1">👥 <span className="font-semibold">{p.name}</span></span>
                {clash && <Chip kind="red">⚠️ אותו חלל לשניים</Chip>}
                {edit ? (
                  <select aria-label={`חלל: ${p.name}`} value={p.room ?? ""} disabled={edit.busy} className={`${FIELD} py-1 text-sm`}
                          onChange={(e) => edit.run({ door: "v2_edit_person", args: { p_person_id: p.id, p_phone: null, p_room: e.target.value, p_source_url: null } })}>
                    <option value="">— חלל —</option>
                    {withCurrent(CHAVUROT_ROOMS, p.room).map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                ) : (
                  <Chip kind={p.room ? "blue" : "gray"}>{p.room ?? "טרם נקבע חלל"}</Chip>
                )}
                {edit && <button type="button" onClick={remove} disabled={edit.busy} aria-label={`הסרה: ${p.name}`} className={ICON}>🗑</button>}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <SheetLink url={p.source_url} />
                <Phone phone={p.phone} />
                {edit && <SheetField p={p} edit={edit} />}
              </div>
            </li>
          );
        })}
      </ul>
      {edit && <AddPerson l={l} kind="chavurot" edit={edit} />}
    </>
  );
}

// ---------------------------------------------------------------- the slot editor

// app._lesson_edit_dialog — title, length, role, format, description, a link
// to the source sheet (uploading a file comes with stage 2ג), and the delete
function SlotSheet({ l, name, edit, onClose }: { l: Lesson; name: string; edit: NonNullable<Editor>; onClose: () => void }) {
  const [title, setTitle] = useState(l.title ?? "");
  const [duration, setDuration] = useState(l.duration_minutes ?? 75);
  const [role, setRole] = useState(l.lesson_role ?? "");
  const [format, setFormat] = useState(l.format ?? "");
  const [description, setDescription] = useState(l.description ?? "");
  const [link, setLink] = useState(l.source_url ?? "");
  const bad = link.trim() !== "" && !HTTP.test(link.trim());
  // the three lengths the app offers, and the slot's own when it is another
  const own = l.duration_minutes ?? 75;
  const durations = DURATION_OPTIONS.some(([m]) => m === own) ? DURATION_OPTIONS
    : [...DURATION_OPTIONS, [own, `${own} דק׳`] as [number, string]].sort((a, b) => a[0] - b[0]);
  const draft = { ...l, title, lesson_role: role, format };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (bad) return;
    const ok = await edit.run({ door: "v2_save_slot", args: {
      p_lesson_id: l.id, p_title: title, p_duration: duration, p_role: role, p_format: format,
      p_description: description, p_source_url: link,
    } });
    if (ok) onClose();
  };
  const remove = async () => {
    if (!window.confirm(`למחוק את המקטע «${name}»? המשימות הפתוחות שנוצרו לו יימחקו איתו; משימות שבוצעו נשמרות.`)) return;
    if (await edit.run({ door: "v2_delete_slot", args: { p_lesson_id: l.id } })) onClose();
  };
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/30 sm:items-center" role="dialog"
         aria-modal="true" aria-label="עריכת מקטע" onClick={onClose}>
      <form onSubmit={save} onClick={(e) => e.stopPropagation()}
            className="max-h-[92dvh] w-full max-w-md space-y-3 overflow-y-auto rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:rounded-2xl">
        <p className="font-display text-lg font-extrabold text-navy">עריכת מקטע</p>
        <label className="block text-sm font-bold">כותרת
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} className={`mt-1 w-full font-normal ${FIELD}`} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-sm font-bold">משך
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={`mt-1 w-full font-normal ${FIELD}`}>
              {durations.map(([m, text]) => <option key={m} value={m}>{text}</option>)}
            </select>
          </label>
          <label className="block text-sm font-bold">תפקיד בערב
            <select value={role} onChange={(e) => setRole(e.target.value)} className={`mt-1 w-full font-normal ${FIELD}`}>
              <option value="">—</option>
              {withCurrent(LESSON_ROLES, l.lesson_role).map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        </div>
        <label className="block text-sm font-bold">פורמט
          <select value={format} onChange={(e) => setFormat(e.target.value)} className={`mt-1 w-full font-normal ${FIELD}`}>
            <option value="">—</option>
            {withCurrent(LESSON_FORMATS, l.format).map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        {isPanel(draft) && <p className="text-sm text-muted">פאנל: כמה מרצים על הבמה, וכולם נסגרים. מרצה שכבר נסגר נשאר בפאנל.</p>}
        {isChavurot(draft) && <p className="text-sm text-muted">חבורות: מעבירים, חלל ודף מקורות לכל אחד.</p>}
        <label className="block text-sm font-bold">תיאור
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={2000}
                    className={`mt-1 w-full font-normal ${FIELD}`} />
        </label>
        <label className="block text-sm font-bold">📎 קישור לדף מקורות
          <input type="url" dir="ltr" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…"
                 className={`mt-1 w-full font-normal ${FIELD}`} />
          {bad && <span className="mt-1 block font-normal text-late">קישור צריך להתחיל ב-https://</span>}
          <span className="mt-1 block font-normal text-muted">העלאת קובץ — בינתיים באפליקציה הנוכחית.</span>
        </label>
        <div className="flex flex-wrap gap-2 pt-1">
          <button type="submit" disabled={edit.busy || bad} className={`flex-1 ${PRIMARY}`}>{edit.busy ? "שומר…" : "💾 שמירה"}</button>
          <button type="button" onClick={onClose} className={SECONDARY}>ביטול</button>
          <button type="button" onClick={remove} disabled={edit.busy} className={`${SECONDARY} text-late`}>🗑 מחיקת המקטע</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- the evening

function BreakRow({ l, edit }: { l: Lesson; edit: Editor }) {
  const minutes = l.duration_minutes ?? 30;
  const options = withCurrent(Array.from({ length: 18 }, (_, i) => (i + 1) * 5), minutes).sort((a, b) => a - b);
  const remove = () => {
    if (window.confirm("למחוק את ההפסקה? השעות שאחריה יתעדכנו.")) edit?.run({ door: "v2_delete_slot", args: { p_lesson_id: l.id } });
  };
  return (
    <div className="flex flex-wrap items-center gap-2 px-2 text-sm text-muted" id={`slot-${l.id}`} data-break={l.id}>
      <span>☕ הפסקה · <span dir="ltr">{slotTimes(l)}</span></span>
      {edit ? (
        <>
          <select aria-label="משך ההפסקה" value={minutes} disabled={edit.busy} className={`${FIELD} py-1`}
                  onChange={(e) => edit.run({ door: "v2_save_slot", args: {
                    p_lesson_id: l.id, p_title: "", p_duration: Number(e.target.value), p_role: "", p_format: "",
                    p_description: "", p_source_url: "",
                  } })}>
            {options.map((m) => <option key={m} value={m}>{m} דק׳</option>)}
          </select>
          <button type="button" onClick={remove} disabled={edit.busy} aria-label="מחיקת ההפסקה" className={ICON}>✕</button>
        </>
      ) : <span>{minutes} דק׳</span>}
    </div>
  );
}

function SlotCard({ l, name, today, openTasks, onToggle, edit }: {
  l: Lesson; name: string; today: Date; openTasks: Task[]; onToggle?: (t: Task) => void; edit: Editor;
}) {
  const [editing, setEditing] = useState(false);
  const chavurot = isChavurot(l);
  const panel = isPanel(l);
  const n = l.people.length;
  const count = chavurot ? (n === 1 ? "מעביר אחד" : `${n} מעבירים`)
    : panel ? (n === 1 ? "מרצה אחד בפאנל" : `${n} מרצים בפאנל`)
    : !l.speaker_name ? (n === 1 ? "מועמד אחד" : `${n} מועמדים`) : "";
  return (
    <Card id={`slot-${l.id}`} className="scroll-mt-4 !p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip kind="blue"><span dir="ltr">{slotTimes(l)}</span></Chip>
        <span className="font-bold">{name}{!(l.title ?? "").trim() && !chavurot ? <span className="font-normal text-muted"> — ללא כותרת</span> : null}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {l.lesson_role && <Chip kind="gold">{l.lesson_role}</Chip>}
        {l.format && <Chip kind="gray">{l.format}</Chip>}
        {n > 0 && count && <Chip kind="blue">{count}</Chip>}
      </div>
      {l.description && <p className="mt-2 text-sm text-muted">{clean(l.description).slice(0, 180)}</p>}
      {safeUrl(l.source_url) && <p className="mt-1"><SheetLink url={l.source_url} /></p>}
      <div className="mt-2 space-y-1">
        {chavurot ? <Presenters l={l} edit={edit} /> : panel ? <Panelists l={l} edit={edit} /> : <Candidates l={l} edit={edit} />}
      </div>
      {openTasks.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-line pt-2">
          {openTasks.map((t) => {
            const dl = deadline(t, today);
            return (
              <div key={t.id} className="flex items-center gap-2">
                <div className="min-w-0 flex-1 text-sm">
                  <span className="font-semibold">{clean(t.task_description)}</span>
                  {dl.overdue && <span className="block text-late">⏰ {dl.nudge}</span>}
                </div>
                <CheckButton task={t} onToggle={onToggle} />
              </div>
            );
          })}
        </div>
      )}
      {edit && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-2">
          {!chavurot && !safeUrl(l.source_url) && (
            <button type="button" onClick={() => setEditing(true)} disabled={edit.busy} className={SECONDARY}>📎 דף מקורות</button>
          )}
          <button type="button" onClick={() => setEditing(true)} disabled={edit.busy} aria-label={`עריכת המקטע: ${name}`}
                  className={SECONDARY}>
            ✏️ עריכת המקטע
          </button>
        </div>
      )}
      {editing && edit && <SlotSheet l={l} name={name} edit={edit} onClose={() => setEditing(false)} />}
    </Card>
  );
}

export function EveningTab({ wf, today, onToggle, edit }: {
  wf: Workfile; today: Date; onToggle?: (t: Task) => void; edit: Editor;
}) {
  const names = slotNames(wf.lessons);
  const openBySlot = new Map<number, Task[]>();
  for (const t of wf.tasks) {
    if (t.lesson_id && t.status !== "DONE") openBySlot.set(t.lesson_id, [...(openBySlot.get(t.lesson_id) ?? []), t]);
  }
  const add = (kind: SlotKind) => edit?.run({ door: "v2_add_slot", args: { p_mishmar_id: wf.mishmar.id, p_kind: kind } });
  const demoNote = demoMode && edit && (
    <p role="note" className="rounded-xl bg-[#fff4d6] px-4 py-2 text-sm text-[#8a5a00]">
      בהדגמה השינויים לא נשמרים, ומשימות המקטעים לא מתעדכנות. באתר עצמו כל שינוי נשמר, והמשימות מתעדכנות לבד.
    </p>
  );
  if (!wf.lessons.length) {
    return (
      <div className="mt-4 space-y-3">
        {demoNote}
        <p className="text-muted">לערב הזה עוד אין מבנה{wf.mishmar.topic ? "" : " — הוא נבנה כשהנושא נסגר"}.</p>
        {edit && wf.mishmar.topic && (
          <button type="button" onClick={() => add("skeleton")} disabled={edit.busy} className={`w-full ${PRIMARY} py-3 text-base`}>
            ✨ יצירת שלד הערב ({wf.mishmar.start_time || "20:00"}, שלושה שיעורים וחבורות)
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="mt-4 space-y-2">
      {demoNote}
      {edit && <p className="text-sm text-muted">השעות נגזרות מהמשכים — שינוי משך של מקטע מזיז את כל הערב.</p>}
      {wf.lessons.map((l) => l.is_break ? <BreakRow key={l.id} l={l} edit={edit} /> : (
        <SlotCard key={l.id} l={l} name={names.get(l.id) ?? ""} today={today} openTasks={openBySlot.get(l.id) ?? []}
                  onToggle={onToggle} edit={edit} />
      ))}
      {edit && (
        <div className="flex flex-wrap gap-2 pt-2">
          <button type="button" onClick={() => add("lesson")} disabled={edit.busy} className={SECONDARY}>➕ שיעור</button>
          <button type="button" onClick={() => add("chavurot")} disabled={edit.busy} className={SECONDARY}
                  title="סבב חבורות נוסף — מעבירים, חללים ודפי מקורות משלו">➕ חבורות</button>
          <button type="button" onClick={() => add("break")} disabled={edit.busy} className={SECONDARY}>➕ הפסקה</button>
        </div>
      )}
    </div>
  );
}
