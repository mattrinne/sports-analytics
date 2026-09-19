# The Hook — UI style brainstorm

Status: written 2026-09-18. **Theme decided the same day: "Gold on graphite" terminal** — the
decision, its rules and the tokens are in `docs/ui/theme.md` and `docs/ui/tokens.css`. This file
keeps the directions the theme was chosen from and the layout principles that came with it. It
says nothing about what the UI shows; only how it looks.

## Design brief

One user, one laptop, long sessions, dense numeric data. The UI is an analyst's desk, not a
sportsbook: it must let the eye scan many figures at once and trust colour to mean one thing.

## Style / theme directions

| direction | feel | palette | type | fits when | risk |
|---|---|---|---|---|---|
| **Trading desk** | Bloomberg / trading terminal: dark, dense, everything visible at once | near-black `#0d1117`-ish surfaces, one cool accent (steel blue), semantic green/red reserved for cover / no-cover, amber for push | monospace tabular numerals for figures (JetBrains Mono, IBM Plex Mono), compact sans for labels | you want to scan many rows and dozens of numbers per screen | reads as a cliché if the accent goes neon; hard to read for long narrative |
| **Broadsheet / almanac** | Pro Football Reference meets the FiveThirtyEight era: light, editorial, generous tables | warm off-white, ink black, one saturated accent, muted team colours only inside charts | serif display (Tiempos / Source Serif), sans body, tabular lining figures | reading, writing up findings, comparing at leisure | less at-a-glance density; team colours clash on a light ground |
| **Film room / chalkboard** | coach's slate: dark grey-green, chalk-white lines, hand-drawn route-like chart marks | slate `#1f2a2a`, chalk `#e8e6dc`, one field-green accent | condensed sans headings (Barlow Condensed), mono numbers | playbook metaphors | novelty wears off; chalk texture fights data legibility |
| **Neutral analytics** | Linear / Vercel dashboard: quiet, grey scale, one accent, colour is data | zinc greys, a single accent (indigo or teal), semantic colours only | Inter / Geist, tabular numerals | everything; safe default that ages well | can look like every SaaS dashboard |

**Decision (2026-09-18):** Trading desk, in the "gold on graphite" palette — graphite ground,
gold accent, all JetBrains Mono, square corners, ticker strip. The warm-black amber variant was
rejected for its brown cast. An earlier recommendation (Neutral analytics as the base system
with Trading desk density) was superseded. Two rules that matter more than the theme:
(1) team colours are *data*, shown only as small swatches and never as the palette for a
32-series chart; (2) green/red/gold mean cover / loss / push everywhere and nothing else.
Single dark theme, no light mode.

## Layout principles

- **Shell**: a fixed top bar carrying brand, navigation and the global filters every page
  honours; an optional ticker strip beneath it; body panels stacked with a constant gap, each
  under a section heading row (title left, context label right).
- **One page pattern per entity type**: a header (identity, swatch, a row of tiles) above a tab
  strip; the same skeleton for every dimension so the code is shared.
- **Two-pane tool pages**: controls in a left panel (chips, grouped), results on the right
  stacked tiles → chart → table. Page state is encoded in the URL so any view is shareable.
- **Density first**: dense tables by default with a "comfortable" toggle that only changes
  row height and base size. Widths are designed for a laptop screen; phone is read-only and
  secondary.
