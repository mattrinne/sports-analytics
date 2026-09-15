{{ config(alias='team_game_stats') }}
-- Team box-score rows with game context, result, and the closing line from the team's side.
select
    t.*,
    g.game_date,
    g.game_type,
    t.team = g.home_team                            as is_home,
    case when t.team = g.home_team then g.home_score else g.away_score end as points_for,
    case when t.team = g.home_team then g.away_score else g.home_score end as points_against,
    g.winner = t.team                               as won,
    g.spread_line * case when t.team = g.home_team then 1 else -1 end as spread_for_team,
    g.total_line
from {{ ref('team_stats_week') }} t
left join {{ ref('nfl_games') }} g on g.game_id = t.game_id
