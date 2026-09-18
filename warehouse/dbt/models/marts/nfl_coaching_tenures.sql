{{
    config(
        alias='coaching_tenures',
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['coach_id', 'team_id', 'role_id', 'first_season', 'is_interim'],
        merge_update_columns=['start_date', 'end_date', 'start_source', 'end_source', 'last_season', 'updated_at'],
        on_schema_change='fail',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- One row per continuous stint of a coach in a role (HC/OC/DC) with a franchise.
--
-- Head coaches come from the nflverse game log (clean.schedules names the head coach of every
-- played game), which is complete even when Wikipedia's end-of-season staff block omits a coach
-- fired mid-year; Wikipedia (clean.coaching_staff) supplies the interim flag and any recorded
-- change dates. Coordinators come from clean.coaching_staff alone.
--
-- start_source / end_source name the clean table the date came from: 'coaching_staff' (a date
-- Wikipedia recorded) or 'schedules' (the game log: first/last game coached around a mid-season
-- head-coach change, or the season calendar proxy for an undated season-long stint: the day after
-- the franchise's previous season ended for a start, the last game of the season for an end).
-- NULL date + NULL source = unknown (an undated interim stint and the predecessor it replaced).
-- end_date is NULL with end_source 'ongoing' while the tenure runs into the latest season. Consecutive seasons in the same role collapse into one
-- tenure; a tenure breaks on a missing season or a mid-season change. Incremental: only new or
-- changed tenures are written; a full refresh is safe (no minted ids).
with roles as (
    select m.source_value as staff_role, r.role_id
    from {{ ref('reference_mappings') }} m
    join {{ ref('coach_roles') }} r on r.role = m.canonical_value
    where m.domain = 'coach_role'
),
games as (
    select g.season, ti.team_id, g.gameday, g.coach, g.played
    from (
        select season, home_team as team, home_coach as coach, gameday, home_score is not null as played
        from {{ ref('schedules') }}
        union all
        select season, away_team, away_coach, gameday, home_score is not null
        from {{ ref('schedules') }}
    ) g
    join {{ ref('team_identities') }} ti on ti.alias = g.team
),
team_seasons as (
    select
        season,
        team_id,
        coalesce(lag(last_game) over (partition by team_id order by season) + 1, first_game) as season_start,
        last_game
    from (
        select season, team_id, min(gameday) as first_game, max(gameday) as last_game
        from games group by season, team_id
    ) x
),
latest_season as (
    select max(season) as season from {{ ref('coaching_staff') }}
),
staff as (
    select
        s.season::integer as season, ti.team_id, ci.coach_id, ro.role_id,
        s.is_interim, s.start_date, s.end_date
    from {{ ref('coaching_staff') }} s
    join {{ ref('coach_identities') }} ci on ci.alias = s.coach
    join {{ ref('team_identities') }} ti on ti.alias = s.team
    join roles ro on ro.staff_role = s.role
),
-- ---------------------------------------------------------------- head coaches: game log
hc_games as (
    select g.season, g.team_id, g.gameday, ci.coach_id
    from games g
    join {{ ref('coach_identities') }} ci on ci.alias = g.coach
    where g.played
),
hc_changes as (
    select *,
        case when lag(coach_id) over (partition by season, team_id order by gameday) is distinct from coach_id
             then 1 else 0 end as changed
    from hc_games
),
hc_runs as (
    select *,
        sum(changed) over (partition by season, team_id order by gameday rows unbounded preceding) - 1 as run_no
    from hc_changes
),
hc_stints as (
    select
        season, team_id, coach_id, run_no,
        min(gameday) as first_game_coached,
        max(gameday) as last_game_coached,
        count(*) over (partition by season, team_id) as stints_in_season
    from hc_runs
    group by season, team_id, coach_id, run_no
),
hc_rows as (
    select
        h.season, h.team_id, h.coach_id, 1::smallint as role_id,
        coalesce(w.is_interim, false)                        as is_interim,
        -- start: first stint of the season starts in the offseason; later stints on their first game
        case when h.run_no > 0 or w.start_date is not null then true else false end as explicit_start,
        case when w.start_date is not null then w.start_date
             when h.run_no > 0 then h.first_game_coached
             else ts.season_start end                        as start_date,
        case when w.start_date is not null then 'coaching_staff'
             else 'schedules' end                            as start_source,
        -- end: a stint followed by another coach in the same season ends on its last game
        case when h.run_no < h.stints_in_season - 1 or w.end_date is not null then true else false end as explicit_end,
        case when w.end_date is not null then w.end_date
             when h.run_no < h.stints_in_season - 1 then h.last_game_coached
             else ts.last_game end                           as end_date,
        case when w.end_date is not null then 'coaching_staff'
             else 'schedules' end                            as end_source
    from hc_stints h
    join team_seasons ts on ts.season = h.season and ts.team_id = h.team_id
    left join staff w on w.season = h.season and w.team_id = h.team_id and w.coach_id = h.coach_id and w.role_id = 1
),
-- ---------------------------------------------------------------- coordinators: Wikipedia rows
coord_season as (
    -- does this team-season-role contain an undated interim change? then the surrounding
    -- boundaries are unknown rather than season-long
    select season, team_id, role_id,
           bool_or(is_interim and start_date is null) as undated_interim_change
    from staff where role_id in (2, 3)
    group by season, team_id, role_id
),
coord_rows as (
    select
        s.season, s.team_id, s.coach_id, s.role_id, s.is_interim,
        (s.start_date is not null or s.is_interim)           as explicit_start,
        case when s.start_date is not null then s.start_date
             when s.is_interim then null
             else ts.season_start end                        as start_date,
        case when s.start_date is not null then 'coaching_staff'
             when s.is_interim then null
             else 'schedules' end                            as start_source,
        (s.end_date is not null or (cs.undated_interim_change and not s.is_interim)) as explicit_end,
        case when s.end_date is not null then s.end_date
             when cs.undated_interim_change and not s.is_interim then null
             else ts.last_game end                           as end_date,
        case when s.end_date is not null then 'coaching_staff'
             when cs.undated_interim_change and not s.is_interim then null
             else 'schedules' end                            as end_source
    from staff s
    join team_seasons ts on ts.season = s.season and ts.team_id = s.team_id
    join coord_season cs on cs.season = s.season and cs.team_id = s.team_id and cs.role_id = s.role_id
    where s.role_id in (2, 3)
),
-- ---------------------------------------------------------------- collapse across seasons
rows_all as (
    select * from hc_rows
    union all
    select * from coord_rows
),
sequenced as (
    select *,
        lag(season) over w       as prev_season,
        lag(explicit_end) over w as prev_explicit_end
    from rows_all
    window w as (partition by coach_id, team_id, role_id, is_interim order by season, start_date nulls first)
),
numbered as (
    select *,
        sum(case when prev_season is null or prev_season <> season - 1 or prev_explicit_end or explicit_start
                 then 1 else 0 end)
            over (partition by coach_id, team_id, role_id, is_interim order by season, start_date nulls first
                  rows unbounded preceding) as tenure_no
    from sequenced
),
bounds as (
    select *,
        min(season) over t as first_season,
        max(season) over t as last_season
    from numbered
    window t as (partition by coach_id, team_id, role_id, is_interim, tenure_no)
),
tenures as (
    select
        coach_id, team_id, role_id, is_interim,
        first_season::smallint as first_season,
        last_season::smallint  as last_season,
        (array_agg(start_date   order by season))[1]         as start_date,
        (array_agg(start_source order by season))[1]         as start_source,
        case when last_season = (select season from latest_season)
              and not bool_or(explicit_end and season = last_season)
             then null
             else (array_agg(end_date order by season desc))[1] end as end_date,
        case when last_season = (select season from latest_season)
              and not bool_or(explicit_end and season = last_season)
             then 'ongoing'
             else (array_agg(end_source order by season desc))[1] end as end_source
    from bounds
    group by coach_id, team_id, role_id, is_interim, tenure_no, first_season, last_season
),
existing as (
    {% if is_incremental() %}
    select * from {{ this }}
    {% else %}
    select null::integer as coach_id, null::integer as team_id, null::smallint as role_id,
           null::boolean as is_interim, null::smallint as first_season, null::smallint as last_season,
           null::date as start_date, null::date as end_date, null::text as start_source, null::text as end_source,
           null::timestamptz as created_at, null::timestamptz as updated_at
    where false
    {% endif %}
)
select
    t.coach_id,
    t.team_id,
    t.role_id,
    t.is_interim,
    t.first_season,
    t.last_season,
    t.start_date,
    t.end_date,
    t.start_source,
    t.end_source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from tenures t
left join existing e
  on e.coach_id = t.coach_id and e.team_id = t.team_id and e.role_id = t.role_id
 and e.first_season = t.first_season and e.is_interim = t.is_interim
where e.coach_id is null
   or (e.start_date, e.start_source, e.end_date, e.end_source, e.last_season)
      is distinct from (t.start_date, t.start_source, t.end_date, t.end_source, t.last_season)
