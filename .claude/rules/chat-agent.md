---
paths:
  - "chat_agent.py"
---

# The chat agent — scoping and the four cost ceilings

Sonnet 5, streaming, ten tools. The generator prompt IS the system prompt, loaded from disk; the chat's tools read and write the same rows the UI shows.

**THE SCOPING RULE: every writing tool is bound to the Mishmar in the session context; the model never supplies a `mishmar_id`.** A trainee's chat cannot reach another pair's Mishmar even if the conversation asks — the id is not a parameter the model can reach.

## Why cost stays flat (and how it breaks)

A turn re-sends its whole history on every API call, and a tool-using turn makes several — the two multiply. Four ceilings keep the cost of a turn flat instead of linear in thread length; **removing any one restores the growth**:

1. `MAX_TOOL_ROUNDS = 3`, and the **last round sets `tool_choice: none`** so a trainee always ends with an answer rather than "I ran out of steps".
2. `trim_history()` sends a trailing window, not the thread. **It may only cut on a plain user turn** — a `tool_result` whose `tool_use` was trimmed away is a 400 from the API, not a cheaper request, and that is how this optimisation usually breaks. The window never opens later than the current question, so the turn in flight goes whole, thinking blocks included. The caller keeps everything; only what is *sent* is trimmed.
3. `compact_tool_output()` caps a result at 1500 chars **structurally — fewer rows, shorter strings — never by cutting the JSON text**, which would spend the tokens and lose the answer too (truncated JSON is unparseable).
4. `search_speaker_index` projects columns and caps rows *before* enriching. It used to `select("*")` and enrich every match with two more Supabase round-trips: a one-letter topic — what a model sends when it widens a search — matched 46 rows, cost 92 round-trips, and produced a 20k-char result re-sent on every later round.

## The prompt

- The ~17.5k-char stable half (role + generator prompt + work-file template) carries the `cache_control` breakpoint; live context sits AFTER it. Don't move the breakpoint or interleave changing text before it.
- **The 44-name roster is stripped from the generator prompt at load** (`_drop_speaker_roster`) — it is a dated snapshot of what `search_speaker_index` reads live; paying ~3.2k chars per request for *staler* data than the tool returns. The file keeps the roster (still pasted whole into external chat windows, which have no tools). The legend, the ה1–ה7 collision flags and the institution list are not duplicated anywhere and must survive the cut.
- The stable prompt is cached in-process keyed on source-file mtimes — editing the generator prompt takes effect on the next message without a restart.
- Assistant turns are echoed back verbatim, thinking blocks included; all tool results return in ONE user message (splitting them teaches the model to stop making parallel calls).
