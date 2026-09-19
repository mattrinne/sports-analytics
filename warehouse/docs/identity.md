# Identity: the `reference` layer

Every name and code from every source resolves to one integer key here, and the `nfl.*` dimensions
are derived from the result. Paths are relative to `warehouse/`.

## Pattern — follow it for every new entity

1. Spellings/codes for the entity are collected from every source that mentions it (plus every
   `reference_mappings` row for its domain). Today's aliases: Wikipedia staff names, nflverse
   per-game head-coach and referee names, officials crew names, team codes, nflverse venue codes,
   nflverse and GSIS game ids.
2. Each resolves to a canonical value through `reference.reference_mappings`
   (`coalesce(canonical, alias)`). The seed `data/seeds/reference_mappings.csv` (`domain`,
   `source_system`, `source_value`, `canonical_value`, optional season range, note) lists only
   exceptions; anything without a row passes through unchanged.
3. `reference.<entity>_identities` (incremental merge on `alias`): `alias`, key, canonical value,
   `source` ∈ {canonical, reference_mappings} (games: {canonical, old_game_id}), timestamps. Keys:
   `coach_id`/`referee_id`/`stadium_id`/`game_id` from sequence `reference.<entity>_id_seq` in
   order of first appearance, never reused (`full_refresh=false`; a merged name keeps the
   canonical's id, a new canonical inherits an alias's id only if nobody else holds it);
   `team_id` = nflverse franchise id (`clean.teams.team_id::int`, which a franchise keeps through
   relocations: OAK and LV are one team). Every warehouse key is an integer (user preference),
   even when the source has a stable code: `stadium_identities` maps nflverse venue codes
   (`JAX00`, kept as `nfl.stadiums.stadium_code`) to a minted id. nflverse `official_id` is not
   usable as a key: renumbered in 2023, absent before 2015.
4. `nfl.<entity>` dimension is *derived* from the identities table. To key any table on a coach,
   referee or team, join its name/code column to `alias`.
5. Mappings are curated by hand — **never auto-merge** (see below).

## Maintaining the mappings

Spelling variants (`Billy Davis` / `Bill Davis`, nflverse's `Klint Kubliak`; referee typos such as
`Bill Carolo`, `Adrian Hall`, `John Perry`) and code variants are fixed by adding a CSV row, never
automatically. `uv run python scripts/alias_candidates.py coach|referee` prints look-alike pairs
not yet mapped and a person decides: relatives (Harbaugh, Shanahan, Gruden, Ryan, Kubiak,
Phillips…; Hochuli, Carey, Steratore) score high and must stay separate. Verify a suspected referee
typo against the crew in `clean.officials` (join `officials.game_id = schedules.old_game_id`;
jersey numbers are stable per official). Canonical spelling = the most frequent form in the source.
On the next build the alias row takes the canonical's id and the retired id disappears from the
dimension. Parser artifacts (footnote daggers, `, Jr.` punctuation) are fixed in the Wikipedia
parser (`normalize_name()` in `src/nfl_pipeline/sources/wikipedia_staff.py`), never with a mapping
row.

## Facts

- **Team codes**: 41 codes for 32 franchises across three systems (current nflverse, era codes
  `STL/SD/OAK`, nflverse's `LA`, GSIS `ARZ/BLT/CLV/HST/SL` in 2010–2015 rosters). Rams canonical
  code is `LAR` (user decision; nflverse uses `LA`). `tests/assert_all_team_codes_resolve` fails
  the build on an unmapped code.
- **Game ids**: nflverse `game_id` (`2024_06_JAX_CHI`) on schedules/pbp/stats/participation; GSIS
  `old_game_id` (`2024101300`) on officials. `reference.game_identities` carries both as aliases of
  one integer `game_id`, except unscheduled future games whose placeholder old ids collide (2026
  weeks 16–17) and a handful of officials rows whose old id matches no schedule row.
- **Referees**: `schedules.referee` and the Referee row in `officials` disagree for ~30 games
  2016–2025 (reassigned crews; 2022 week 1 is shifted by one game). Both names are real referees,
  so the dimension is unaffected; for a game-level referee prefer `officials` where it exists.
- **Stadiums**: `schedules.stadium_id` is trustworthy, `stadium` names change with sponsors,
  `pbp.stadium` is polluted (a venue's current name or an unrelated one) — use
  `pbp.game_stadium`/`schedules`. `assert_stadium_names_unique_per_venue` warns (not fails) on new
  upstream mis-tags; the known one (2026 Jaguars London game carrying `JAX00`) is excluded in the
  test.
