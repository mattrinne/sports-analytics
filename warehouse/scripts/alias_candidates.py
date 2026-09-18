"""Report names in a dimension that look like the same person, for human review.

Nothing here changes data. Review the pairs and add the real aliases to
data/seeds/reference_mappings.csv in the entity's domain. Relatives score high and must NOT be
merged: coaching families (Harbaugh, Shanahan, Gruden, Ryan, Kubiak...), the Hochulis, the Careys
and the Steratores among referees.

    uv run python scripts/alias_candidates.py coach [--min-ratio 0.8]
    uv run python scripts/alias_candidates.py referee
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import re

import psycopg

from nfl_pipeline.config import settings

# entity -> (dimension table, name column, reference_mappings domain)
ENTITIES = {
    "coach": ("nfl.coaches", "coach_name", "coach_name"),
    "referee": ("nfl.referees", "referee_name", "referee_name"),
}

SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv)\.?$", re.IGNORECASE)


def norm(name: str) -> str:
    return re.sub(r"[^a-z ]", "", SUFFIX.sub("", name.lower().strip()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("entity", choices=sorted(ENTITIES), nargs="?", default="coach")
    ap.add_argument("--min-ratio", type=float, default=0.8)
    args = ap.parse_args()
    table, column, domain = ENTITIES[args.entity]
    with psycopg.connect(settings().database_url) as conn:
        names = [r[0] for r in conn.execute(f"select {column} from {table} order by 1")]
        mapped = {
            r[0]
            for r in conn.execute(
                "select source_value from reference.reference_mappings where domain = %s", (domain,)
            )
        }
    rows = []
    for a, b in itertools.combinations(names, 2):
        if a in mapped or b in mapped:
            continue
        ratio = difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()
        same_last = a.split()[-1].lower() == b.split()[-1].lower()
        same_initial = a[0].lower() == b[0].lower()
        if (
            norm(a) == norm(b)
            or ratio >= args.min_ratio
            or (same_last and same_initial and ratio >= 0.6)
        ):
            rows.append((ratio, a, b))
    for ratio, a, b in sorted(rows, reverse=True):
        print(f"{ratio:.2f}  {a!r:32s} {b!r}")
    print(f"{len(rows)} candidate pairs among {len(names)} {args.entity}s (already-mapped names excluded)")


if __name__ == "__main__":
    main()
