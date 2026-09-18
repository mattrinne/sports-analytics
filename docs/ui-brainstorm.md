# The Hook — web UI brainstorm (sports-betting analysis on the warehouse)

Status: written 2026-09-18. **Theme decided the same day: "Gold on graphite" terminal** — see
`docs/ui/theme.md` and `docs/ui/tokens.css`. Stack and content priorities are still open; the
rest of this file is the brainstorm they will be chosen from.

## What the UI is for

One user, one laptop, historical data only (closing lines, no line movement, no live odds). The
UI answers "how has X performed against the line, under which conditions, and how much should I
trust that" — and later "what does my model say and how has it done". It is an analyst's desk,
not a sportsbook.

## Style / theme directions

| direction | feel | palette | type | fits when | risk |
|---|---|---|---|---|---|
| **Trading desk** | Bloomberg / trading terminal: dark, dense, everything visible at once | near-black `#0d1117`-ish surfaces, one cool accent (steel blue), semantic green/red reserved for cover / no-cover, amber for push | monospace tabular numerals for figures (JetBrains Mono, IBM Plex Mono), compact sans for labels | you want to scan 16 games and 40 numbers per screen | reads as a cliché if the accent goes neon; hard to read for long narrative |
| **Broadsheet / almanac** | Pro Football Reference meets the FiveThirtyEight era: light, editorial, generous tables | warm off-white, ink black, one saturated accent, muted team colours only inside charts | serif display (Tiempos / Source Serif), sans body, tabular lining figures | reading trends, writing up findings, comparing seasons | less at-a-glance density; team colours clash on a light ground |
| **Film room / chalkboard** | coach's slate: dark grey-green, chalk-white lines, hand-drawn route-like chart marks | slate `#1f2a2a`, chalk `#e8e6dc`, one field-green accent | condensed sans headings (Barlow Condensed), mono numbers | coach- and situation-centric content, playbook metaphors | novelty wears off; chalk texture fights data legibility |
| **Neutral analytics** | Linear / Vercel dashboard: quiet, grey scale, one accent, colour is data | zinc greys, a single accent (indigo or teal), semantic colours only | Inter / Geist, tabular numerals | everything; safe default that ages well | can look like every SaaS dashboard |

**Decision (2026-09-18):** Trading desk, in the "gold on graphite" palette — graphite ground,
gold accent, all JetBrains Mono, square corners, ticker strip. The user rejected the warm-black
amber version for its brown cast. Tokens and rules are in `docs/ui/`. Earlier recommendation was
Neutral analytics as the base system with Trading desk density; superseded. Two rules that
matter more than the theme: (1) team colours are *data*, shown only as small swatches / logos
and never as the palette for a 32-series chart; (2) green/red/amber mean cover / loss / push
everywhere and nothing else. Ship light and dark from the start via tokens; dark is the
working mode, light for reading and screenshots.

## Content — organised by the question a bettor asks

### Entity pages (one per `nfl.*` dimension)

- **Team** — ATS and O/U records with splits: home/away, favourite/underdog, spread buckets
  (0–3, 3.5–6.5, 7+), after bye, after loss, short rest, divisional, primetime, roof/surface,
  month. Points scored/allowed vs `total_line`. Season-by-season sparkline of cover margin.
  Current HC / coordinators from `coaching_tenures`.
- **Coach** — HC record ATS across every tenure (`coaching_tenures` gives the stints), as
  favourite vs underdog, off a loss, vs specific opponents/coaches, interim stints flagged.
  Timeline of tenures with team logos.
- **Referee** — penalties and penalty yards per game, average `total` vs `total_line` (over
  rate), home cover rate, games worked per season, crew via `officials`. Caveat panel: the
  ~30 games where `schedules.referee` disagrees with `officials`.
- **Stadium** — over rate, home cover rate, scoring by roof/surface/temp/wind bands (all in
  `schedules`), neutral-site flag.
- **Game** — closing line and result, cover margin, both teams' relevant trend tiles, the
  ref, the stadium/weather, both HCs, rest days, box score from `team_stats_week`, drive /
  EPA summary from `pbp` when loaded.

### Cross-cutting

- **Weekly slate** (home page in season) — every game of the selected week with closing
  line, total, and 2–3 trend tiles per side ("DAL 9-3 ATS as road dog since 2022"). Out of
  season the home page becomes a season review.
- **Situational explorer** — the core tool. Filter builder over games (any column of
  `nfl.schedules` plus team/coach/ref/stadium attributes) → ATS record, O/U record, ROI at the
  recorded odds, cover-margin distribution, sample size and a confidence indicator (Wilson
  interval or a simple z-score vs 52.4% break-even). Results table of the underlying games.
  Save/name queries.
- **Compare** — two teams / coaches / referees side by side on the same split table.
- **Trends feed** — auto-generated "streaks" (n ≥ 8, hit rate ≥ 70%) for the coming week,
  ranked by sample size, with a prominent multiple-comparisons warning.
- **Model workspace** (phase 2) — predictions vs closing line per game, edge distribution,
  calibration plot, backtest ROI by season / by edge bucket, feature importance, model
  version history from the `models` schema. Bankroll simulation (flat / Kelly) over a
  backtest.
- **Data health** — seasons loaded, last refresh, dbt test summary, known gaps (participation
  lag, missing lines). Small, one screen.

### Reusable widgets

- **Record tile**: `W-L-P ATS · cover % · n · ROI @ recorded odds`, colour by cover %,
  greyed when n is small.
- **Split table**: rows = conditions, columns = ATS, O/U, n, ROI; sortable; click a row to
  push that condition into the explorer.
- **Cover-margin strip**: one thin bar per game, green/red by cover, length = margin;
  compact way to show a season.
- **Line vs result scatter**: x = spread, y = margin, diagonal = push line; hexbin at scale.

## Layout

- **Shell**: left nav (Slate, Explorer, Teams, Coaches, Referees, Stadiums, Models, Data),
  top bar with the two global filters (season range, season type REG/POST) that every page
  honours, and a command palette (`⌘K`) for jumping to any entity.
- **Entity page pattern**: header (identity, logo/swatch, 4 record tiles) → tabs: Splits ·
  Games · Trends · Compare. Same pattern for every dimension so the code is shared.
- **Explorer**: filter panel on the left (chips, grouped by team / game / line / venue /
  officials), results on the right stacked: record tiles → chart → game table. Shareable URL
  encodes the filters.
- **Density**: dense tables by default (32px rows), a "comfortable" toggle. Widths designed
  for a laptop screen first; phone is read-only and secondary.

## Stack options (what / why / cost)

| option | what | good | bad | cost to first useful screen |
|---|---|---|---|---|
| **Streamlit** | Python pages querying Postgres | fastest; you already live in Python | theming is weak, every interaction reruns the page, will not look like any of the directions above | an evening |
| **Evidence.dev** | SQL + markdown pages, built-in charts and inputs, Node app in compose | polished BI look with almost no frontend code; SQL-first matches "UI reads `nfl.*` only" | extracts sources to parquet on disk (bumps the no-persisted-downloads preference, though it is *our* data); theming is a token file, not free-form; complex filter builder is awkward | a weekend |
| **Custom: FastAPI read-only API + SvelteKit or Next, Observable Plot / ECharts for charts** | full control, design tokens, URL-encoded explorer state | most code; needs a component library discipline | 2–4 weekends for shell + team page + explorer |
| **Hybrid**: Evidence now, custom later | validate which content you actually use before building it | two codebases over time | weekend + later |

**Recommendation:** Hybrid. The content list above is a guess until you have used it; Evidence
gets the slate, team/coach/referee pages and a basic explorer in front of you in a weekend and
tells you which splits you actually look at. Build the custom app when the explorer or the
model workspace outgrows it, carrying the design tokens and the SQL over. If you already know
you want the trading-desk look and full explorer on day one, skip straight to custom.

## Data work the UI will pull forward (marts to build regardless of stack)

1. `nfl.game_team_lines` — one row per (game, team): team, opponent, home flag, closing spread
   from that team's perspective, total, moneyline, result, cover margin, ATS/O/U outcome,
   rest days, divisional flag, HC key, referee key, stadium key. Every split above is a
   `group by` on this table.
2. `nfl.team_game_stats` — `team_stats_week` keyed to `game_id`/`team_id`.
3. `nfl.referee_games` — per (game, referee) with penalty counts derived from `pbp`.
4. Later: `models.predictions`, `models.backtests`, `models.versions`.

## Open questions for the user

- Is the situational explorer the centrepiece, or are curated entity pages enough at first?
- ROI convention: assume -110 when spread odds are missing, or drop those games?
- Season range default: 2010+ (all loaded) or a rolling 3 seasons?
- Which model comes first: spread margin regression, or win probability → moneyline edge?
