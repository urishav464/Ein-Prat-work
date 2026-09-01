---
name: content-gap
description: Check a proposed Mishmar topic against the previous year's archive and this season's other topics — was something similar already done, and what worked then. Use before a pair closes a topic.
argument-hint: "[topic]"
allowed-tools: Bash, Read, Grep, Agent
---

# Content gap

Two questions. Delegate the first; answer the second yourself.

1. **Was there a similar evening last year?** → run the `archive-diver` agent with
   `question: <topic>`, `kind: topic`. It returns one JSON object (`answer` / `found` / `reception` /
   `caveat`) and already handles the two traps (this season's folders are templates; the
   `ממתין לתשובה` boilerplate). Relay its `answer` and `caveat` verbatim — the caveat that a
   five-file archive proves nothing by absence is the point.
2. **Is it colliding with this season?** → `dm.find_mishmarim_by_topic(topic)`, read-only.

Overlap is material, never a veto: say what was done, how this differs, and let the pair decide.
Never invent a past evening.
