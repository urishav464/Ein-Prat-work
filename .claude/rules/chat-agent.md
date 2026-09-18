---
paths:
  - "chat_agent.py"
---

# The chat agent — scoping and the four cost ceilings

Sonnet 5, streaming, **thirteen tools**. The generator prompt IS the system prompt, loaded from disk; the chat's tools read and write the same rows the UI shows.

**THE SCOPING RULE: every writing tool is bound to the Mishmar in the session context; the model never supplies a `mishmar_id`.** A trainee's chat cannot reach another pair's Mishmar even if the conversation asks — the id is not a parameter the model can reach.

## Why cost stays flat (and how it breaks)

A turn re-sends its whole history on every API call, and a tool-using turn makes several — the two multiply. Four ceilings keep the cost of a turn flat instead of linear in thread length; **removing any one restores the growth**:

1. `MAX_TOOL_ROUNDS = 3`, and the **last round sets `tool_choice: none`** so a trainee always ends with an answer rather than "I ran out of steps".
2. `trim_history()` sends a trailing window, not the thread. **It may only cut on a plain user turn** — a `tool_result` whose `tool_use` was trimmed away is a 400 from the API, not a cheaper request, and that is how this optimisation usually breaks. The window never opens later than the current question, so the turn in flight goes whole, thinking blocks included. The caller keeps everything; only what is *sent* is trimmed.
3. `compact_tool_output()` caps a result at 1500 chars **structurally — fewer rows, shorter strings — never by cutting the JSON text**, which would spend the tokens and lose the answer too (truncated JSON is unparseable).
4. `search_speaker_index` projects columns and caps rows *before* enriching. It used to `select("*")` and enrich every match with two more Supabase round-trips: a one-letter topic — what a model sends when it widens a search — matched 46 rows, cost 92 round-trips, and produced a 20k-char result re-sent on every later round.

## The evening-builder tools (the pair's main work surface)

- `save_lesson` takes `duration_minutes`, never a start time — times are derived (`recompute_lesson_times`) and every save reflows the evening; the tool returns the recomputed schedule so the model reports real times.
- `add_candidate_speaker` / `close_speaker` / `set_source_sheet` / `add_task(slot_order=…)` resolve `slot_order` inside the context's Mishmar only — a task the model ties to a slot gets an explicit `tasks.lesson_id`; the model never sees a lesson id. `close_speaker` is the «סגרתי את X» flow: X becomes the lesson's speaker, the journal logs ✅, the other candidates are removed.
- `close_topic` returns `phase_opened` (the newly-current phase + open tasks) and `index_matches` — **a closed topic is a sentence, so the matcher falls back to its meaningful words** — and builds the default timeline when the evening is empty. An iron rule makes the model unfold all of that in the SAME response.
- **Phones never enter chat context.** `render_context` shows candidates as name+status only; the test suite asserts a phone string does not appear.

## The scout (the speaker-search screen) — map → people → fit, TWO calls per search

The screen used to quote the literal topic into fourteen fixed queries, mine names out of the
snippets with regex and hand the survivors to ONE curation call — which is why a lesson topic
made the search narrower instead of wider, and why a topic phrased as a question found nobody.
Now:

1. **`scout_map(topic, lesson_topic, angle)`** — no tools, `effort: low`, ~1k tokens. Reads the
   topic as FIELDS: per angle a discipline, the kind of person, 2–4 **broad Hebrew terms — never
   the topic phrase**, where such people sit, and one line on why the field speaks to the topic.
   Cached in `session_state["scout_map"]` on `(topic, lesson_topic, angle)`; the trainee edits it
   (terms as a text line, a checkbox per angle) before anything expensive runs.
2. **`scout_speakers(topic, lesson, lesson_topic, progress, scout_map_result)`** — the model
   searches the web itself: `web_search_20260318` (`max_uses = SCOUT_MAX_SEARCHES = 8`,
   `allowed_callers: ["direct"]`, `user_location` IL/Jerusalem) + `web_fetch_20260318`
   (`max_uses = 4`, `max_content_tokens = 8000`, free beyond tokens, can only open URLs its own
   searches returned). Streamed, so every `server_tool_use` becomes a progress line («מחפש: …» /
   «קורא: …»). `pause_turn` is resumed at most `SCOUT_MAX_CONTINUES = 2` times by sending the
   assistant message back unchanged (`model_dump(exclude_none=True)` keeps `encrypted_content`),
   then reported as `truncated`. Usage is summed across the resumptions and carries
   `searches` / `fetches` — shown on screen, so the «about a shekel» claim is checkable.

**Why `allowed_callers: ["direct"]` and not dynamic filtering.** Direct calls return every
`web_search_tool_result` block whole; `_harvest_sources` collects every URL the model actually
retrieved (search results, fetched pages, citations) and **that set is the no-invention rule
now**: `_ground` keeps a candidate only if one of its links is in it, blanks a foreign `link`,
drops the rest into `rejected` as `ungrounded`, strips contact fields, force-flags «⚠️ לאמת»,
and derives confidence from the pages (institutional domain AND a page_age ≥ 2024 → `high`; one →
`medium`). The old rule — a name is kept only if WE sent it — cannot exist when the model does
the searching; the anchor moved from names to URLs. Dynamic filtering is the later cost
optimisation, once we know what the runs really cost.

**Every fallback names its reason** (`no_map` · `no_names` · `model_rejected_all` · `truncated` ·
`empty_reply` · `search_disabled` — the org has web search off in the Claude Console and the API
says so with a 400 · `error`), keeps the map and the queries, and the screen offers one manual
link per term. The index is NOT a source on this screen, but every returned name is checked
against it: **`_index_memory(name)`** is one line of institutional memory — what the person
taught here and when (the seed's «(18.9.25)»-dated notes, this season's `lessons.speaker_name`),
the last outreach with its Mishmar and date, the rating if any — or «אין תיעוד של הזמנה קודמת».
Never «not in the index» read as a review.

**Every run is saved**, the empty ones included: `slim_for_storage` keeps the map, the queries,
the candidates without evidence snippets, the rejections, the outcome and the cost (~2–4 KB);
`dm.mark_search_added` appends the names the pair actually took from it. `speaker_search.py`'s
discovery (`search_candidates`, `extract_names`) is off the primary path; `verify_speaker` (the
«אמת» button) and the CLI agents still use it.

## The prompt

- The ~17.5k-char stable half (role + generator prompt + work-file template) carries the `cache_control` breakpoint; live context sits AFTER it. Don't move the breakpoint or interleave changing text before it.
- **The 44-name roster is stripped from the generator prompt at load** (`_drop_speaker_roster`) — it is a dated snapshot of what `search_speaker_index` reads live; paying ~3.2k chars per request for *staler* data than the tool returns. The file keeps the roster (still pasted whole into external chat windows, which have no tools). The legend, the ה1–ה7 collision flags and the institution list are not duplicated anywhere and must survive the cut.
- The stable prompt is cached in-process keyed on source-file mtimes — editing the generator prompt takes effect on the next message without a restart.
- Assistant turns are echoed back verbatim, thinking blocks included; all tool results return in ONE user message (splitting them teaches the model to stop making parallel calls).
