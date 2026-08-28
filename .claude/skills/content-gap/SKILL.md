---
name: content-gap
description: Check a proposed Mishmar topic against the previous year's archive and this season's other topics — was something similar already done, and what worked then. Use before a pair closes a topic.
argument-hint: "[topic]"
allowed-tools: Bash, Read, Grep
---

# Content gap analysis

Two questions, answered from real data:

1. **Was there a similar Mishmar before?** `archive.summarise_for_topic(topic)` over the 2025-26 work-files and feedback. Two traps the module already handles — do not bypass it with raw grep:
   - This season's (2026-27) folders are **unfilled templates** and must not be searched as history.
   - Every work-file inherits a status legend containing `ממתין לתשובה`, so an unfiltered search for a תשובה topic matches all 21 templates. Boilerplate must be stripped before matching.
2. **Is it colliding with this season?** `dm.find_mishmarim_by_topic(topic)` across the 21 current Mishmarim.

## Reading the results

- The archive is small (5 real work-files) — **absence of a match is not proof it wasn't done**; say so explicitly.
- A past similar evening is not a veto — it is material: what structure was used, which speakers came (`archive.speaker_history`), what the feedback said. Repetition with a new angle is legitimate pedagogy; flag the overlap and let the pair decide.
- Diversity view, if asked: list this season's closed topics and note clusters (e.g. three philosophy evenings in a row) neutrally.
- Never invent past events; quote only what the files actually contain.
