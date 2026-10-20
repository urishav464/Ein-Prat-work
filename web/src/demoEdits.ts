// The demo's stand-in for the structure doors: the same change, made on the
// screen only. Nothing is sent and nothing is saved. On the site the database
// also reconciles the slots' tasks (v2_private.sync_lesson_tasks); the demo
// leaves the tasks as they were, and says so.
import { CLOSED, PANEL_SEP, isChavurot, isPanel, recomputeTimes, type Lesson, type Person, type Workfile } from "./model";
import type { StructureAnswer, StructureCall, StructureResult } from "./structure";

let nextId = -1;
const ZERO = { created: 0, removed: 0, adopted: 0, completed: 0, renamed: 0 };

function slot(order: number, minutes: number, isBreak: boolean, role: string | null = null): Lesson {
  return {
    id: nextId--, slot_order: order, start_time: null, duration_minutes: minutes, is_break: isBreak,
    title: null, description: null, lesson_role: role, format: null, speaker_name: null, source_url: null,
    people: [],
  };
}

// dm.create_default_timeline: three lessons, the breaks, an hour of חבורות
function skeleton(): Lesson[] {
  return [slot(1, 75, false), slot(2, 30, true), slot(3, 75, false), slot(4, 30, true),
          slot(5, 75, false), slot(6, 15, true), slot(7, 60, false, "חבורות")];
}

export function demoApply(before: Workfile, call: StructureCall): StructureAnswer {
  const wf: Workfile = structuredClone(before);
  let result: StructureResult = {};
  const lesson = (id: number) => wf.lessons.find((l) => l.id === id);
  const find = (id: number): { l: Lesson; p: Person } | null => {
    for (const l of wf.lessons) {
      const p = l.people.find((x) => x.id === id);
      if (p) return { l, p };
    }
    return null;
  };
  // dm.refresh_panel_speakers — the panel's line is every closed panelist
  const refresh = (l: Lesson) => {
    const names = l.people.filter((p) => p.status === CLOSED).map((p) => p.name);
    l.speaker_name = names.length ? names.join(PANEL_SEP) : null;
  };
  // dm.close_lesson_speaker — the slot's speaker; the other candidates go
  const close = (l: Lesson, p: Person) => {
    const removed = l.people.filter((x) => x.id !== p.id).map((x) => x.name);
    l.people = [{ ...p, status: CLOSED }];
    l.speaker_name = p.name;
    return { closed: p.name, removed, logged: true };
  };
  const last = () => Math.max(0, ...wf.lessons.map((l) => l.slot_order)) + 1;

  switch (call.door) {
    case "v2_set_topic": {
      const closing = !wf.mishmar.topic;
      wf.mishmar.topic = call.args.p_topic.trim();
      const built = closing && !wf.lessons.length;
      if (built) wf.lessons = skeleton();
      result = { closed: closing, created: built ? 7 : 0 };
      break;
    }
    case "v2_add_slot": {
      const k = call.args.p_kind;
      if (k === "skeleton") {
        if (wf.lessons.length) return { status: "exists" };
        wf.lessons = skeleton();
      } else {
        wf.lessons.push(slot(last(), k === "break" ? 15 : 60, k === "break", k === "chavurot" ? "חבורות" : null));
      }
      break;
    }
    case "v2_save_slot": {
      const l = lesson(call.args.p_lesson_id);
      if (!l) return { status: "forbidden" };
      l.duration_minutes = call.args.p_duration;
      if (!l.is_break) {
        const wasPanel = isPanel(l);
        l.title = call.args.p_title.trim();
        l.description = call.args.p_description.trim();
        l.lesson_role = call.args.p_role.trim();
        l.format = call.args.p_format.trim();
        l.source_url = call.args.p_source_url.trim() || null;
        if (isPanel(l)) {
          // dm.adopt_panel_speaker: the speaker it had closed stays on the panel
          const had = (l.speaker_name ?? "").trim();
          if (!wasPanel && had && !had.includes("·")) {
            const p = l.people.find((x) => x.name === had);
            if (p) p.status = CLOSED;
            else l.people.push({ id: nextId--, name: had, status: CLOSED, phone: null, room: null, source_url: null });
          }
          refresh(l);
        }
      }
      break;
    }
    case "v2_delete_slot":
      wf.lessons = wf.lessons.filter((l) => l.id !== call.args.p_lesson_id);
      break;
    case "v2_reopen_slot": {
      const l = lesson(call.args.p_lesson_id);
      if (l) l.speaker_name = null;
      break;
    }
    case "v2_add_person": {
      const l = lesson(call.args.p_lesson_id);
      if (!l) return { status: "forbidden" };
      const chavurot = isChavurot(l);
      const p: Person = {
        id: nextId--, name: call.args.p_name.trim(), status: "⬜ לא פנינו",
        phone: chavurot ? null : call.args.p_phone.trim() || null,
        room: chavurot ? call.args.p_room || null : null, source_url: null,
      };
      l.people.push(p);
      if (call.args.p_close && !chavurot) {
        if (isPanel(l)) {
          p.status = CLOSED;
          refresh(l);
          result = { closed: p.name, removed: [], logged: true };
        } else {
          result = close(l, p);
        }
      }
      result.person = p.id;
      break;
    }
    case "v2_edit_person": {
      const at = find(call.args.p_person_id);
      if (!at) return { status: "forbidden" };
      if (call.args.p_phone !== null) at.p.phone = call.args.p_phone.trim() || null;
      if (call.args.p_room !== null) at.p.room = call.args.p_room || null;
      if (call.args.p_source_url !== null) at.p.source_url = call.args.p_source_url.trim() || null;
      break;
    }
    case "v2_set_person_status": {
      const at = find(call.args.p_person_id);
      if (!at) return { status: "forbidden" };
      if (isPanel(at.l)) {
        at.p.status = call.args.p_status;
        refresh(at.l);
        result = { logged: true };
      } else if (call.args.p_status === CLOSED) {
        result = close(at.l, at.p);
      } else {
        at.p.status = call.args.p_status;
        result = { logged: true };
      }
      break;
    }
    case "v2_remove_person": {
      const at = find(call.args.p_person_id);
      if (!at) return { status: "forbidden" };
      at.l.people = at.l.people.filter((x) => x.id !== at.p.id);
      if (isPanel(at.l)) refresh(at.l);
      result = { removed: at.p.name };
      break;
    }
  }
  wf.lessons = recomputeTimes(wf.lessons, wf.mishmar.start_time);
  return { status: "ok", workfile: wf, result: { ...result, sync: ZERO } };
}
