{{ config(alias='coach_games') }}
-- One row per team-game with the head coach (from schedules). Unpivots home/away.
select
    g.game_id, g.season, g.game_type, g.week, g.game_date,
    g.home_team               as team,
    g.away_team               as opponent,
    true                      as is_home,
    g.home_coach              as coach,
    g.away_coach              as opponent_coach,
    g.home_score              as points_for,
    g.away_score              as points_against,
    case when g.home_score is null then null
         when g.home_score > g.away_score then 1 when g.home_score < g.away_score then 0 else 0.5 end as win
from {{ ref('nfl_games') }} g
union all
select
    g.game_id, g.season, g.game_type, g.week, g.game_date,
    g.away_team, g.home_team, false, g.away_coach, g.home_coach,
    g.away_score, g.home_score,
    case when g.away_score is null then null
         when g.away_score > g.home_score then 1 when g.away_score < g.home_score then 0 else 0.5 end
from {{ ref('nfl_games') }} g
