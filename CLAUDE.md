# sports-analytics — working notes for Claude

What the system is and where each component lives: `README.md` (it indexes every folder and its
docs). This file holds only what is not there: constraints from the user, the rules that span
components, and pointers to the component instruction files. Constraints: one user, who pays for
any infrastructure, so anything hosted must stay as cheap as possible; data is pulled once and
analyzed forever, there is no live data; everything runs in docker compose on a laptop.

## Component instructions — read before working in a folder

| folder | rules |
|---|---|
| `warehouse/` | `warehouse/CLAUDE.md` — a task → doc table over `warehouse/docs/` (layers, identity, loading, commands) |
| `api/` | `api/CLAUDE.md` — module map, SQL and contract rules, one-checkout-per-request, tests |
| `docs/ui/` | `theme.md` (styling rules) and `tokens.css` (the only place a colour, type or density value is defined); `docs/ui-brainstorm.md` has the directions the theme was chosen from |

Each component is its own uv project (`cd <folder>` for `uv run ...`); compose runs from the root.

## Rules that span components

- **Docs rule from the user:** a fact lives in exactly one document and everywhere else points to
  it (a link or "see `path`, section"). Detail belongs to the component that owns it
  (`warehouse/docs/` for schemas, identity and loading, `api/README.md` for routes and
  variables, `.env.example` for variables, a `docs/commands.md` per component for commands); the
  root `README.md` only orients and indexes. A `README.md` and the `CLAUDE.md` beside it never
  share a fact: anything both need goes in a topic file under that folder's `docs/` and both point
  to it. Before adding a paragraph, check whether it already exists and link to it instead.
- **Future plans from the user:** a `CLAUDE.md` never contains plans, roadmap items or
  forward-looking statements; it is operating instructions only. Plans are documented under
  `docs/` (for example `docs/cloud-deployment.md`), and only as the outcome of a planning session
  the user starts for that topic. Never add "later", "deferred" or "next" notes to a doc on your
  own initiative, and never let an existing plan doc steer work the user has not asked for.
- **Hard rule from the user:** nothing downloaded at runtime is written to disk (no vendored
  dictionaries, no wikitext cache, dbt writes `target/`/logs to `/tmp` in containers, nflreadpy's
  cache is off in the image and on a named volume locally). Curated, human-owned inputs live under
  `warehouse/data/` (`seeds/*.csv`, `coaching_staff_overrides.csv`) and are copied into the image,
  as is `warehouse/dbt/`: rebuild the image after changing either.
- **Anything holding data in `nfl` is a persisted mart** built like the dimensions: contract,
  integer PK, `created_at`/`updated_at`, incremental merge. Views only re-present marts. Grain and
  keys are consumer-friendly: integer keys, one row per (game), (game, team) etc., joinable to
  `nfl.teams`/`coaches`/`referees`/`stadiums` without going through `reference.*_identities`.
- **Consumers read `nfl.*` and `ops.*` only.** The api connects as the read-only role
  `nfl_reader` (`docker/postgres/init/02-reader-role.sh`) and never touches `staging`, `clean` or
  `reference`.
- **UI styling** comes from `docs/ui/tokens.css` and the rules in `docs/ui/theme.md`. Green, red
  and gold mean cover, loss and push and nothing else; team colours are data (swatches only).

## Commands

Repo root: `docs/commands.md`. Components: `warehouse/docs/commands.md`, `api/docs/commands.md`
(each ends with how to verify a change). Commit only when asked.

## How the user likes to work

Short what/why/cost before an infrastructure or design choice, then a clear recommendation; they
decide quickly and sometimes reverse earlier designs (aggressive pruning → faithful copy; views →
persisted marts). When asked for an opinion, give an honest one and stop; when told to build,
build the whole thing, verify it, and report plainly including what was changed from the literal
spec and why.
