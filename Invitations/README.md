# Invitations — Design Library

Reference library for designing invitation posters for Mishmarim and other Ein Prat events. Shared across `Mishmer-section/` and any future generator (lessons, hikes, etc.) that needs an invitation.

## The pattern (from existing examples)

Two invitation flavors show up in past posters:

1. **Thematic Mishmar invitation** — a custom watercolor illustration painted to match the Mishmar's specific subject (e.g. old cinema and film reels for a קולנוע Mishmar, Hasmonean warriors for a חנוכה Mishmar, lanterns and mountains for a פילוסופיית המזרח Mishmar), with a fixed text layout on top:
   - Header: `הנכם מוזמנים למשמר בנושא [נושא]`
   - Date (Hebrew + Gregorian)
   - A timed schedule block (speaker/session name + time), usually in a semi-transparent box over the art
   - Ein Prat logo

2. **General event/study-days poster** — reuses a generic Ein Prat landscape watercolor (hills, the Judean Desert, the campus) rather than a topic-specific painting, for multi-day schedules like study days or holiday programs (Pesach, Chanukah).

The topic-specific artwork is generated from a prompt that turns the Mishmar's subject into a themed watercolor painting — see `prompt/` for the base prompt and its per-topic variants.

## Structure

```
Invitations/
├── README.md
├── prompt/       ← the "invitation artist" prompt that generates the themed watercolor per topic
└── examples/     ← past invitation posters, kept as visual reference for the pattern
```

## Adding examples

Image files can't be attached to this repo through chat — they need to be pushed via git (upload directly on GitHub into `Invitations/examples/`, or `git push` from a local clone). Once pushed, they become part of the design reference here.
