{{ config(alias='player_game_stats') }}
-- Player box-score rows with game context (date, home/away, result).
select
    p.*,
    g.game_date,
    g.game_type,
    p.team = g.home_team                            as is_home,
    case when p.team = g.home_team then g.home_score else g.away_score end as team_score,
    case when p.team = g.home_team then g.away_score else g.home_score end as opponent_score,
    g.winner = p.team                               as won
from {{ ref('player_stats_week') }} p
left join {{ ref('nfl_games') }} g on g.game_id = p.game_id
