-- Every team code in every clean table must resolve to a franchise through reference.team_identities.
-- A new code (relocation, nflverse rename) shows up here first; fix it with a reference_mappings row.
with codes as (
    select 'schedules' as t, home_team as code from {{ ref('schedules') }}
    union select 'schedules', away_team from {{ ref('schedules') }}
    union select 'pbp', posteam from {{ ref('pbp') }}
    union select 'pbp', defteam from {{ ref('pbp') }}
    union select 'pbp', home_team from {{ ref('pbp') }}
    union select 'pbp', away_team from {{ ref('pbp') }}
    union select 'participation', possession_team from {{ ref('participation') }}
    union select 'player_stats_week', team from {{ ref('player_stats_week') }}
    union select 'player_stats_week', opponent_team from {{ ref('player_stats_week') }}
    union select 'team_stats_week', team from {{ ref('team_stats_week') }}
    union select 'team_stats_week', opponent_team from {{ ref('team_stats_week') }}
    union select 'rosters', team from {{ ref('rosters') }}
    union select 'rosters_weekly', team from {{ ref('rosters_weekly') }}
    union select 'depth_charts', club_code from {{ ref('depth_charts') }}
    union select 'depth_charts', team from {{ ref('depth_charts') }}
    union select 'coaching_staff', team from {{ ref('coaching_staff') }}
    union select 'players', latest_team from {{ ref('players') }}
    union select 'teams', team_abbr from {{ ref('teams') }}
)
select c.t, c.code
from codes c
left join {{ ref('team_identities') }} a on a.alias = c.code
where c.code is not null and c.code <> '' and a.team_id is null
