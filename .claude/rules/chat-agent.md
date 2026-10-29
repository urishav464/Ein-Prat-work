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
- `close_topic` returns `phase_opened` (the newly-current phase + open tasks) and `index_matches` — **a closed topic is a sentence, so the matcher falls back to its meaningful words** — and builds the default timeline when the evening is empty. The `close_topic` tool description tells the model to unfold all of that in the SAME response.
- **Phones never enter chat context.** `render_context` shows candidates as name+status only — nothing checks this automatically, so a change to `render_context` is checked by reading it.

## The scout (the speaker-search screen) — map → people → fit, TWO calls per search

The screen used to quote the literal topic into fourteen fixed queries, mine names out of the
snippets with regex and hand the survivors to ONE curation call — which is why a lesson topic
made the search narrower instead of wider, and why a topic phrased as a question found nobody.
Now:

1. **`scout_map(topic, lesson_topic, angle)`** — no tools, `effort: low`, structured output
   (`MAP_SCHEMA`; the scan cannot use one — web search returns citations), `max_tokens` 4000. Reads the
   topic as FIELDS: per angle a discipline, the kind of person, 2–4 **broad Hebrew terms — never
   the topic phrase**, where such people sit, and one line on why the field speaks to the topic.
   Cached in `session_state["scout_map"]` on `(topic, lesson_topic, angle)`; the trainee edits it
   (terms as a text line, a checkbox per angle) before anything expensive runs.
2. **`scout_speakers(topic, lesson, lesson_topic, progress, scout_map_result)`** — the model
   searches the web itself (`max_tokens` 16000, streamed — thinking counts toward it, and one real
   scan used 5.3k output): `web_search_20260318` (`max_uses` = 3 per angle + 1 per example,
   ceiling `SCOUT_MAX_SEARCHES = 12` — it was 2 per angle + 1, ceiling 8, until round 3 below;
   a single-angle scan used to be allowed the whole ceiling,
   `allowed_callers: ["direct"]`, no `user_location` — the API rejects `country: "IL"` with a 400 «Country code IL is not supported», which failed every scan until the «פרטים טכניים» text named it) + `web_fetch_20260318`
   (`max_uses` = angles + 1, +1 with examples, ceiling 5; `max_content_tokens = 5000` — an average page is ~2.5k;
   free beyond tokens, can only open URLs its own
   searches returned). Streamed, so every `server_tool_use` becomes a progress line («מחפש: …» /
   «קורא: …»). `pause_turn` is resumed at most `SCOUT_MAX_CONTINUES = 2` times by sending the
   assistant message back unchanged (`model_dump(exclude_none=True)` keeps `encrypted_content`),
   then reported as `truncated`. Usage is summed across the resumptions and carries
   `searches` / `fetches` and **`cost_usd`** — the scan plus the map, priced by `_cost` from
   `PRICES` (Sonnet 5: $2 in · $10 out · $0.20 cache read · $2.50 5-minute cache write) and
   `SEARCH_USD`, cache writes included. The screen and the dashboard show ≈₪ (`ILS_PER_USD`, a
   label, not a quote). Measured on the first real scan (#04, three angles): 7 searches, 35.7k
   input, 130k cache reads, 5.3k output → **$0.22 ≈ ₪0.8**; searches and input ~⅓ each, output
   ~¼. The system prompt caches for 5 minutes, not 1h: scans are minutes to hours apart, so the
   2× write rarely paid back, and the reads inside one scan's server-side loop hit either TTL.

**Round 2 of the method (after the first real results — four professors, all relevant).** The
map's angles are PURPOSES, not professions (יסודות = what one must know; ערעור = who turns the
question over; מפתיעה = a neighbouring field), and **`who` is chosen by the topic**: a researcher,
or an educator, rabbi, writer, artist, practitioner, journalist — whoever actually speaks about it
in Israel, preferring people who teach a broad young audience; `where` may be Hartman, Beit Avi
Chai, Alma, Kolot… not only departments. The scout treats the map's kind of person as binding,
breaks ties toward evidence of public teaching (and says so in `fit`), searches in Hebrew (English
only to reach an institutional page), writes no text between searches, and caps `rejected` at 4.
`_ground` adds **`inst_link`** — the first grounded URL on an institutional domain — which the
card opens as «🏛️ עמוד המוסד» (the old «אמת» re-ran a 5-second DuckDuckGo check of what the
model had just read). Nothing here could be tested against the API from the sandbox; the
comparison is the instructor's re-run of the same topic against the $0.22 baseline.

**Round 3 of the method (the trainees' verdict, 2026-10: «mostly old academics, not really
lecturers», on a Marxism evening — the staff had suggested educators instead).** The cause was
in the method, not the model: the map read the topic as RESEARCH FIELDS («as researchers name
it», `where` = departments), the scan looked on faculty pages first, and «high confidence» was
an institutional page + a recent one — so the most established professor won every topic, and
«teaches a broad audience» was only a tie-breaker. Now: (1) **the target is someone who teaches
18–25s or a broad audience TODAY** — mechina / midrasha / beit-midrash teachers, open lecture
series, podcasts, video, rabbis, writers, artists; an academic only with public teaching; the
map's `terms` are subjects a lecture would be titled by, `where` the places that teach young
people, and «חוקר/ת» alone is not a kind of person for a Mishmar. (2) The scan searches for
LECTURES, opens a lecture page when it can, and returns `teaching` (one sentence) and
`teaching_link` (a lecture / class / podcast / video URL from its own results — `_ground`
blanks one it never retrieved). (3) **`_confidence` ranks the teaching evidence**: `high` =
a grounded `teaching_link` AND a page from 2024+; `medium` = the teaching link alone, or a
recent institutional page; `low` = neither; `_ground` sorts by it BEFORE the cap. Age is never
guessed (rule 3). (4) **«מרצים בסגנון של…»** (`examples`, ≤ 3, typed by the pair — by the
instructor's decision ONLY typed names; the speaker index is never sent to the model): one
search each to learn what the person does, then people like them; an example never comes
back. (5) **«👎 לא מתאים?»** on a card (`DISMISS_REASONS`) writes `{name, why}` to the saved
search (`dm.mark_search_dismissed`); the next scan of that evening sends them as `avoid`
(`dm.search_avoid`, newest reason per person) and the evening's own people as `on_evening`
(`dm.evening_people`). The prompt says not to return them and to read a reason as a
correction («אקדמי מדי» → further from academia); `_ground` enforces it by `_name_key` (no
title, no gershayim) and files each in `rejected` with the reason. The saved search keeps
`examples`, `avoid`, `dismissed` and the teaching fields. `scripts/harness/test_scout.py`
proves all of it on recorded messages (a stand-in client — payload, budgets, grounding,
steering, ranking, pause_turn, the marks on the fixture); six planted bugs, each caught.
What the model makes of the prompts is the pair's re-run of the same topic, against the
round-2 cost of ≈₪0.8 (round 3's extra searches: ≈₪1–1.3, estimated, not yet measured).

**Why `allowed_callers: ["direct"]` and not dynamic filtering.** Direct calls return every
`web_search_tool_result` block whole; `_harvest_sources` collects every URL the model actually
retrieved (search results, fetched pages, citations) and **that set is the no-invention rule
now**: `_ground` keeps a candidate only if one of its links is in it, blanks a foreign `link`,
drops the rest into `rejected` as `ungrounded`, strips contact fields, force-flags «⚠️ לאמת»,
and derives confidence from the pages — since round 3, from the TEACHING evidence (above). The old rule — a name is kept only if WE sent it — cannot exist when the model does
the searching; the anchor moved from names to URLs. Dynamic filtering is the later cost
optimisation, once we know what the runs really cost.

**Every fallback names its reason** (`no_map` · `no_names` · `model_rejected_all` · `truncated` ·
`empty_reply` · `search_disabled` · `error`), keeps the map and the queries, and the screen offers
one manual link per term — and **always the API's own error text** under «פרטים טכניים» (also on
the dashboard's searches table). `search_disabled` is decided by `_off_for_org`: the error names
web search **and** says «not enabled»/«disabled» — the first version matched on the tool's name
alone, so any 400 about a tool parameter was shown as «search is switched off» and the real cause
was hidden. Web search is ON by default (platform.claude.com/settings/privacy); only the admin line
under the warning names that link. **Web fetch off on its own** (`_fetch_disabled`) is not a
failure: the request is retried once without the `web_fetch` tool, names are grounded on search
result URLs alone, and `usage["fetch_disabled"]` puts a note in the cost caption. The index is NOT a source on this screen, but every returned name is checked
against it: **`_index_memory(name)`** is one line of institutional memory — what the person
taught here and when (the seed's «(18.9.25)»-dated notes, this season's `lessons.speaker_name`),
the last outreach with its Mishmar and date, the rating if any — or «אין תיעוד של הזמנה קודמת».
Never «not in the index» read as a review.

**Every run is saved**, the empty ones included: `slim_for_storage` keeps the map, the queries,
the candidates without evidence snippets, the rejections, the outcome and the cost (~2–4 KB);
`dm.mark_search_added` appends the names the pair actually took from it. `speaker_search.py`'s
discovery (`search_candidates`, `extract_names`) is off the primary path; `verify_speaker` is
used only by the CLI agents now — the search screen's «אמת» became «🏛️ עמוד המוסד».

## The prompt

- The ~17.5k-char stable half (role + generator prompt + work-file template) carries the `cache_control` breakpoint; live context sits AFTER it. Don't move the breakpoint or interleave changing text before it.
- **The 44-name roster is stripped from the generator prompt at load** (`_drop_speaker_roster`) — it is a dated snapshot of what `search_speaker_index` reads live; paying ~3.2k chars per request for *staler* data than the tool returns. The file keeps the roster (still pasted whole into external chat windows, which have no tools). The legend, the ה1–ה7 collision flags and the institution list are not duplicated anywhere and must survive the cut.
- The stable prompt is cached in-process keyed on source-file mtimes — editing the generator prompt takes effect on the next message without a restart.
- Assistant turns are echoed back verbatim, thinking blocks included; all tool results return in ONE user message (splitting them teaches the model to stop making parallel calls).
