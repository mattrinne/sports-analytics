"""Registry of nflverse datasets to mirror. Adding a dataset is one entry here; `refresh`,
`backfill` and `list` pick it up automatically.

Loaders are named by string so importing this module does not import nflreadpy/polars, which keeps
CLI start-up fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dataset:
    name: str
    table: str
    loader: str  # nflreadpy function name
    description: str
    partitioned: bool = (
        True  # True: one file per season, replaced by `season`. False: full replace.
    )
    min_season: int | None = 1999
    loader_kwargs: dict = field(default_factory=dict)
    indexes: tuple[tuple[str, ...], ...] = ()
    unique: tuple[str, ...] | None = None


REGISTRY: dict[str, Dataset] = {
    d.name: d
    for d in [
        Dataset(
            name="schedules",
            table="schedules",
            loader="load_schedules",
            description="Game schedules, results, head coaches, closing betting lines (all seasons in one file).",
            partitioned=False,
            min_season=None,
            loader_kwargs={"seasons": True},
            indexes=(("season", "week"), ("home_team",), ("away_team",)),
            unique=("game_id",),
        ),
        Dataset(
            name="teams",
            table="teams",
            loader="load_teams",
            description="Team names, abbreviations, colors, logos.",
            partitioned=False,
            min_season=None,
            unique=("team_abbr",),
        ),
        Dataset(
            name="players",
            table="players",
            loader="load_players",
            description="Player master with cross-source ids.",
            partitioned=False,
            min_season=None,
            indexes=(("display_name",),),
            unique=("gsis_id",),
        ),
        Dataset(
            name="rosters",
            table="rosters",
            loader="load_rosters",
            description="Season-level rosters.",
            indexes=(("season", "team"), ("gsis_id",)),
        ),
        Dataset(
            name="rosters_weekly",
            table="rosters_weekly",
            loader="load_rosters_weekly",
            description="Week-level rosters (who was on the roster for each game week).",
            min_season=2002,
            indexes=(("season", "week", "team"), ("gsis_id",)),
        ),
        Dataset(
            name="depth_charts",
            table="depth_charts",
            loader="load_depth_charts",
            description="Weekly depth charts.",
            min_season=2001,
            indexes=(("season", "week"), ("gsis_id",)),
        ),
        Dataset(
            name="team_stats_week",
            table="team_stats_week",
            loader="load_team_stats",
            description="Post-game team box-score stats, one row per team-game.",
            loader_kwargs={"summary_level": "week"},
            indexes=(("season", "week"), ("game_id",), ("team",)),
        ),
        Dataset(
            name="player_stats_week",
            table="player_stats_week",
            loader="load_player_stats",
            description="Post-game player box-score stats, one row per player-game.",
            loader_kwargs={"summary_level": "week"},
            indexes=(("season", "week"), ("player_id", "season"), ("team",)),
        ),
        Dataset(
            name="pbp",
            table="pbp",
            loader="load_pbp",
            description="nflfastR play-by-play with EPA/WP model outputs (~370 columns).",
            indexes=(("game_id",), ("season", "week"), ("posteam", "season")),
        ),
        Dataset(
            name="participation",
            table="participation",
            loader="load_participation",
            description="Per-play personnel, formation, coverage type, pass rushers, players on field (2016+).",
            min_season=2016,
            indexes=(("nflverse_game_id", "play_id"), ("season",)),
        ),
        Dataset(
            name="coaching_staff",
            table="coaching_staff",
            loader="nfl_pipeline.sources.wikipedia_staff.load_coaching_staff",
            description="Head coach, offensive and defensive coordinators per team-season with mid-season change dates, parsed from Wikipedia season articles.",
            min_season=2010,
            indexes=(("season", "team"), ("coach",)),
        ),
        Dataset(
            name="officials",
            table="officials",
            loader="load_officials",
            description="Officiating crews per game.",
            min_season=2015,
            indexes=(("game_id",),),
        ),
    ]
}


def seasons_for(dataset: Dataset, start: int, end: int) -> list[int]:
    """Seasons in [start, end] that this dataset can have, clipped to its min_season."""
    lo = max(start, dataset.min_season or start)
    return list(range(lo, end + 1))
