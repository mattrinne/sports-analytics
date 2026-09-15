{{ config(alias='coach_stints') }}
-- Head-coach tenure per team aggregated from coach_games.
select
    coach,
    team,
    min(season)                                    as first_season,
    max(season)                                    as last_season,
    count(*) filter (where points_for is not null) as games,
    sum(win)::numeric(6,1)                         as wins,
    count(*) filter (where win = 0)                as losses,
    count(*) filter (where win = 0.5)              as ties,
    count(*) filter (where game_type <> 'REG' and points_for is not null) as playoff_games
from {{ ref('nfl_coach_games') }}
where coach is not null
group by coach, team
