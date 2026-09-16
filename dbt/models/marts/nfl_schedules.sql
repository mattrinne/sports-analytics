{{
    config(
        alias='schedules',
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='game_id',
        merge_update_columns=[
            'season', 'game_type', 'week', 'gameday', 'weekday', 'gametime', 'time_of_day',
            'away_team_id', 'home_team_id', 'away_score', 'home_score', 'result', 'total',
            'winning_team_id', 'winning_team_location', 'losing_team_id', 'losing_team_location',
            'overtime', 'gsis_id', 'nfl_detail_id', 'pfr_id', 'pff_id', 'espn_id', 'ftn_id',
            'away_rest', 'home_rest', 'away_moneyline', 'home_moneyline', 'spread_line', 'total_line',
            'temp', 'wind', 'away_coach_id', 'home_coach_id', 'referee_id', 'stadium_id', 'updated_at',
        ],
        on_schema_change='fail',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- Game fact/dimension: one row per game in clean.schedules (1999+, played and scheduled), keyed by
-- the integer game_id from reference.game_identities, with every team, coach, referee and venue
-- resolved to its warehouse key. gametime is kept as the source gives it (US Eastern); time_of_day
-- buckets the kickoff in US Central time: morning before 12:00, noon 12:00-13:59, afternoon
-- 14:00-16:59, night from 17:00. result and total are nflverse's home_score - away_score and
-- home_score + away_score; winning/losing columns are NULL for ties and unplayed games.
-- Incremental: a row is rewritten only when some attribute changed (scores, lines, flexed
-- kickoffs, a resolved coach or referee spelling), so updated_at is meaningful.
with src as (
    select
        gi.game_id,
        s.season,
        s.game_type,
        s.week,
        s.gameday,
        s.weekday,
        s.gametime,
        case
            when s.gametime is null then null
            when ct.kickoff::time < '12:00' then 'morning'
            when ct.kickoff::time < '14:00' then 'noon'
            when ct.kickoff::time < '17:00' then 'afternoon'
            else 'night'
        end                                                     as time_of_day,
        at_.team_id                                             as away_team_id,
        ht.team_id                                              as home_team_id,
        s.away_score,
        s.home_score,
        s.result,
        s.total,
        case when s.result > 0 then ht.team_id when s.result < 0 then at_.team_id end as winning_team_id,
        case when s.result > 0 then 'home' when s.result < 0 then 'away' end           as winning_team_location,
        case when s.result > 0 then at_.team_id when s.result < 0 then ht.team_id end as losing_team_id,
        case when s.result > 0 then 'away' when s.result < 0 then 'home' end           as losing_team_location,
        s.overtime,
        s.gsis                                                  as gsis_id,
        s.nfl_detail_id,
        s.pfr                                                   as pfr_id,
        s.pff                                                   as pff_id,
        s.espn::integer                                         as espn_id,
        s.ftn                                                   as ftn_id,
        s.away_rest,
        s.home_rest,
        s.away_moneyline,
        s.home_moneyline,
        s.spread_line,
        s.total_line,
        s.temp,
        s.wind,
        ac.coach_id                                             as away_coach_id,
        hc.coach_id                                             as home_coach_id,
        r.referee_id,
        st.stadium_id
    from {{ ref('schedules') }} s
    join {{ ref('game_identities') }} gi on gi.alias = s.game_id and gi.source = 'canonical'
    join {{ ref('team_identities') }} at_ on at_.alias = s.away_team
    join {{ ref('team_identities') }} ht on ht.alias = s.home_team
    left join {{ ref('coach_identities') }} ac on ac.alias = s.away_coach
    left join {{ ref('coach_identities') }} hc on hc.alias = s.home_coach
    left join {{ ref('referee_identities') }} r on r.alias = s.referee
    left join {{ ref('stadium_identities') }} st on st.alias = s.stadium_id
    cross join lateral (
        select ((s.gameday + s.gametime) at time zone 'America/New_York') at time zone 'America/Chicago' as kickoff
    ) ct
),
existing as (
    {% if is_incremental() %}
    select * from {{ this }}
    {% else %}
    select null::integer as game_id, null::smallint as season, null::text as game_type, null::smallint as week,
           null::date as gameday, null::text as weekday, null::time as gametime, null::text as time_of_day,
           null::integer as away_team_id, null::integer as home_team_id, null::smallint as away_score,
           null::smallint as home_score, null::smallint as result, null::smallint as total,
           null::integer as winning_team_id, null::text as winning_team_location,
           null::integer as losing_team_id, null::text as losing_team_location, null::boolean as overtime,
           null::integer as gsis_id, null::text as nfl_detail_id, null::text as pfr_id, null::integer as pff_id,
           null::integer as espn_id, null::integer as ftn_id, null::smallint as away_rest, null::smallint as home_rest,
           null::smallint as away_moneyline, null::smallint as home_moneyline, null::double precision as spread_line,
           null::double precision as total_line, null::smallint as temp, null::smallint as wind,
           null::integer as away_coach_id, null::integer as home_coach_id, null::integer as referee_id,
           null::integer as stadium_id, null::timestamptz as created_at, null::timestamptz as updated_at
    where false
    {% endif %}
)
select
    s.*,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from src s
left join existing e on e.game_id = s.game_id
where e.game_id is null
   or row(s.season, s.game_type, s.week, s.gameday, s.weekday, s.gametime, s.time_of_day,
          s.away_team_id, s.home_team_id, s.away_score, s.home_score, s.result, s.total,
          s.winning_team_id, s.winning_team_location, s.losing_team_id, s.losing_team_location,
          s.overtime, s.gsis_id, s.nfl_detail_id, s.pfr_id, s.pff_id, s.espn_id, s.ftn_id,
          s.away_rest, s.home_rest, s.away_moneyline, s.home_moneyline, s.spread_line, s.total_line,
          s.temp, s.wind, s.away_coach_id, s.home_coach_id, s.referee_id, s.stadium_id)
      is distinct from
      row(e.season, e.game_type, e.week, e.gameday, e.weekday, e.gametime, e.time_of_day,
          e.away_team_id, e.home_team_id, e.away_score, e.home_score, e.result, e.total,
          e.winning_team_id, e.winning_team_location, e.losing_team_id, e.losing_team_location,
          e.overtime, e.gsis_id, e.nfl_detail_id, e.pfr_id, e.pff_id, e.espn_id, e.ftn_id,
          e.away_rest, e.home_rest, e.away_moneyline, e.home_moneyline, e.spread_line, e.total_line,
          e.temp, e.wind, e.away_coach_id, e.home_coach_id, e.referee_id, e.stadium_id)
