# Invitation Artist Prompt

The counterpart to `Mishmer-section/generator/mishmar-generator-prompt.md` for the visual side: turns a landscape photo into a themed watercolor invitation background.

## How it works

`base-prompt.md` is the constant part — A4 portrait, watercolor technique, palette, and lighting instructions used for every invitation.

Each Mishmar or event gets a **variant** in `variants/` that extends the base prompt with:
- a set of hidden symbolic elements specific to the topic, woven into the landscape
- a topic-specific color palette and mood
- (sometimes) a compositional narrative, e.g. a journey across the frame

## Variants so far

| File | Topic | Note |
|---|---|---|
| `variants/cinema-mishmar.md` | קולנוע (Cinema) | — |
| `variants/passover-exodus.md` | Passover / Exodus | Source labeled this "Shavuot" — content is Passover. Flagged in the file, not corrected. |

## Writing a new variant

Copy the pattern: take `base-prompt.md`, keep its watercolor-technique instructions, then add topic-specific hidden elements, palette, mood, and (if useful) a compositional narrative — the way `cinema-mishmar.md` and `passover-exodus.md` do.
