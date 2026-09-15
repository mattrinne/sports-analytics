{{ config(alias='game_coordinators') }}
-- One row per team-game with the head coach, offensive coordinator and defensive coordinator in
-- charge on game day. Staff rows come from clean.coaching_staff (Wikipedia season articles); a
-- person covers a game when start_date <= game_date < end_date (NULL = season boundary).
-- head_coach comes from nflverse schedules; head_coach_wiki is the parsed value for validation.
with team_games as (
    select g.game_id, g.season, g.week, g.game_type, g.game_date, g.home_team as team, g.away_team as opponent,
           true as is_home, g.home_coach as head_coach
    from {{ ref('nfl_games') }} g
    union all
    select g.game_id, g.season, g.week, g.game_type, g.game_date, g.away_team, g.home_team,
           false, g.away_coach
    from {{ ref('nfl_games') }} g
),
pick as (
    select tg.game_id, tg.team, s.role, s.coach, s.is_interim,
           row_number() over (
               partition by tg.game_id, tg.team, s.role
               -- prefer the most specific window: interim with a start date first,
               -- then anyone with an explicit start date, then the season-long holder
               order by s.start_date desc nulls last, s.is_interim desc
           ) as rn
    from team_games tg
    join {{ ref('coaching_staff') }} s
      on s.season = tg.season and s.team = tg.team
     and (s.start_date is null or s.start_date <= tg.game_date)
     and (s.end_date   is null or s.end_date   >  tg.game_date)
)
select
    tg.game_id, tg.season, tg.week, tg.game_type, tg.game_date, tg.team, tg.opponent, tg.is_home,
    tg.head_coach,
    hc.coach      as head_coach_wiki,
    hc.is_interim as head_coach_interim,
    oc.coach      as offensive_coordinator,
    oc.is_interim as offensive_coordinator_interim,
    dc.coach      as defensive_coordinator,
    dc.is_interim as defensive_coordinator_interim,
    st.coach      as special_teams_coordinator
from team_games tg
left join pick hc on hc.game_id = tg.game_id and hc.team = tg.team and hc.role = 'head_coach' and hc.rn = 1
left join pick oc on oc.game_id = tg.game_id and oc.team = tg.team and oc.role = 'offensive_coordinator' and oc.rn = 1
left join pick dc on dc.game_id = tg.game_id and dc.team = tg.team and dc.role = 'defensive_coordinator' and dc.rn = 1
left join pick st on st.game_id = tg.game_id and st.team = tg.team and st.role = 'special_teams_coordinator' and st.rn = 1
