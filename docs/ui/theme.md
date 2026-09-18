# The Hook — UI theme (gold on graphite terminal)

**Product name: The Hook** (the half point on a line; sport-neutral, chosen 2026-09-18 with other
leagues in mind). Mark: `THE/HOOK`, slash in the accent. Theme decided 2026-09-18 after three rounds of visual studies (four theme directions → five trading-desk
variants → five terminal palettes). Tokens live in `tokens.css` next to this file; this page is the
rules that the tokens cannot express.

## Character

A trading-desk terminal: dark, dense, square, all monospace, everything visible at once. Graphite
rather than true black so it holds up over long sessions. One accent (gold) for identity and
navigation state; colour otherwise reserved for betting outcomes.

## Rules

1. **Green / red / gold mean cover / no cover / push, everywhere, and nothing else.** A chart
   series, a status pill or a button may not use them for another meaning.
2. **Team colours are data.** 9px swatch beside the abbreviation, never a fill for a chart series
   and never a page accent. No logos in tables.
3. **One typeface.** JetBrains Mono for labels, body and figures. `font-variant-numeric:
   tabular-nums` on anything numeric. Uppercase with `.08em` tracking for labels, nav and table
   headers; mixed case for row labels only when they are proper names.
4. **Square corners, 1px rules, no shadows.** Depth comes from the three surface tones
   (`--bg`, `--bar`, `--surface`), not from elevation.
5. **Section headings** are 11.5px uppercase mono prefixed with `▸` in the accent.
6. **Density first.** 26px table rows, 12px base type. A "comfortable" toggle may raise
   `--row-h` to 32px and `--size` to 13px; nothing else changes.
7. **Small samples are grey.** Any record with n < 30 renders in `--muted` regardless of hit rate.
   Rows at ≥ 55 % cover with n ≥ 30 get a 3px accent marker on the left.
8. **ROI shown with its assumption.** A tile or cell showing ROI states the odds it assumed
   (recorded odds, or -110 when missing) in its caption.

## Shell

- Top bar (`--bar-h`): brand `THE/HOOK` with the slash in accent, nav (Slate · Explorer · Teams ·
  Coaches · Referees · Stadiums · Models · Data), global filters right-aligned (season range,
  REG / POST), date and week.
- Ticker (`--ticker-h`) under the bar in season: each game as `AWAY @ HOME  FAV -x.x · O/U y · score
  ▲FAV / ▼DOG`.
- Body: panels stacked with `--pad`, each with a section heading row (title left, context label
  right).

## Widgets (as built in the studies)

- **Game card**: two rows (away, home) of swatch · abbreviation · spread and moneyline · score;
  footer with total, referee, cover chip, O/U chip; weather line.
- **Record tile**: uppercase label, mono figure in accent (or semantic colour when the figure is a
  signed margin or ROI), one-line caption.
- **Split table**: Split · n · ATS (W–L–P + %) · O/U · Avg CM · ROI; zebra off; hot-row marker.
- **Cover-margin strip**: one bar per game, ± from a centre rule, coloured by outcome, week labels.

## Reference renderings

Studies were published as private artifacts during the design session; the final chosen panel is
"C · Gold on graphite" on the terminal-palettes page. Re-create from the token file rather than
from screenshots.
