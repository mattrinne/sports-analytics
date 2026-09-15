{{ config(alias='games') }}
-- One row per game from clean.schedules with analysis-friendly names, the winner, and the
-- closing-line outcomes. spread_line convention (nflverse): positive = home team favored.
select
    s.game_id,
    s.season,
    s.game_type,
    s.week,
    s.gameday                                         as game_date,
    s.weekday,
    s.gametime                                        as kickoff,
    s.home_team,
    s.away_team,
    s.home_score,
    s.away_score,
    s.result                                          as home_margin,
    s.total                                           as total_points,
    s.overtime,
    s.div_game                                        as divisional,
    s.location,
    case
        when s.home_score is null then null
        when s.home_score > s.away_score then s.home_team
        when s.away_score > s.home_score then s.away_team
        else 'TIE'
    end                                               as winner,
    s.home_coach,
    s.away_coach,
    s.home_qb_id,
    s.home_qb_name,
    s.away_qb_id,
    s.away_qb_name,
    s.home_rest,
    s.away_rest,
    s.referee,
    s.stadium_id,
    s.stadium,
    s.roof,
    s.surface,
    s.temp,
    s.wind,
    s.spread_line,
    s.home_spread_odds,
    s.away_spread_odds,
    s.total_line,
    s.over_odds,
    s.under_odds,
    s.home_moneyline,
    s.away_moneyline,
    case
        when s.result is null or s.spread_line is null then null
        when s.result > s.spread_line then 'home'
        when s.result < s.spread_line then 'away'
        else 'push'
    end                                               as spread_cover,
    case
        when s.total is null or s.total_line is null then null
        when s.total > s.total_line then 'over'
        when s.total < s.total_line then 'under'
        else 'push'
    end                                               as total_result,
    s.old_game_id,
    s.gsis,
    s.pfr,
    s.espn
from {{ ref('schedules') }} s
