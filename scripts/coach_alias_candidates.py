"""Report coach names in nfl.coaches that look like the same person, for human review.

Nothing here changes data. Review the pairs and add the real aliases to
data/seeds/reference_mappings.csv (domain coach_name); coaching families (Harbaugh, Shanahan,
Gruden, Ryan, Kubiak...) score high and must NOT be merged.

    uv run python scripts/coach_alias_candidates.py [--min-ratio 0.8]
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import re

import psycopg

from nfl_pipeline.config import settings

SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv)\.?$", re.IGNORECASE)


def norm(name: str) -> str:
    return re.sub(r"[^a-z ]", "", SUFFIX.sub("", name.lower().strip()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ratio", type=float, default=0.8)
    args = ap.parse_args()
    with psycopg.connect(settings().database_url) as conn:
        names = [r[0] for r in conn.execute("select coach_name from nfl.coaches order by 1")]
        mapped = {
            r[0]
            for r in conn.execute(
                "select source_value from nfl.reference_mappings where domain = 'coach_name'"
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
    print(f"{len(rows)} candidate pairs among {len(names)} coaches (already-mapped names excluded)")


if __name__ == "__main__":
    main()
