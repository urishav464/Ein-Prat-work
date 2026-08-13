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

## House style — measured from the source files

Fonts actually used in past posters (read from the embedded fonts in the PDFs in `examples/`):

| Poster | Fonts |
|---|---|
| ערב לימוד | Ambivalenti Compressed (title), BarLev + BarLev Bold, FB Flashback Bold |
| אלול | Aluma MF Medium/Bold, Choco Regular/Bold |
| קולנוע, פילוסופיית המזרח | Ariana Regular |

These are commercial Hebrew faces and aren't available in this repo. The key characteristic to preserve when substituting: **they are narrow/compressed**, which is what lets large text sit on a single line. A free stand-in that behaves the same way is *Noto Sans Hebrew Variable* at `font-stretch: 62.5%`.

Proportions measured from the ערב לימוד PDF (as % of page width, so they scale to any output size):

| Element | Size |
|---|---|
| Title | 21.4cqw |
| "הנכם מוזמנים ל.." | 6.4cqw |
| Schedule lines | 5.2cqw |
| "מחכים לראותכם!" | 5.9cqw |
| Top meta row (בס"ד + date) | 4.2cqw |
| Schedule line spacing | 1.38 × font size |
| Schedule block | 31%–75% of page height |
| Closing line | 82% of page height |

The schedule sits close to the closing line, and each item is one single line: `זמן - שם, נושא`.

## The translucent panel

A device used on several posters: a **rounded-corner box, very high transparency, light pastel tone drawn from the image behind it**, placed under the text so details read clearly instead of blending into the artwork. Used on the busier illustrated backgrounds (חנוכה, קולנוע). Not needed when the background is calm enough behind the text, or when a full-page wash already lifts it.

## Structure

```
Invitations/
├── README.md
├── prompt/       ← the "invitation artist" prompt that generates the themed watercolor per topic
└── examples/     ← past invitation posters, kept as visual reference for the pattern
```

## Adding examples

Image files can't be attached to this repo through chat — they need to be pushed via git (upload directly on GitHub into `Invitations/examples/`, or `git push` from a local clone). Once pushed, they become part of the design reference here.
