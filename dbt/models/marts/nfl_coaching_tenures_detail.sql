-- Presentation view over nfl.coaching_tenures: the same rows with the coach name, team name and
-- role abbreviation joined in from nfl.coaches, nfl.teams and reference.coach_roles.
{{ config(materialized='view', alias='coaching_tenures_detail') }}

select
    t.coach_id,
    c.coach_name,
    t.team_id,
    tm.team_abbr,
    tm.team_name,
    t.role_id,
    r.role_abbr,
    t.is_interim,
    t.first_season,
    t.last_season,
    t.start_date,
    t.end_date
from {{ ref('nfl_coaching_tenures') }} t
join {{ ref('nfl_coaches') }} c on c.coach_id = t.coach_id
join {{ ref('nfl_teams') }} tm on tm.team_id = t.team_id
join {{ ref('coach_roles') }} r on r.role_id = t.role_id
