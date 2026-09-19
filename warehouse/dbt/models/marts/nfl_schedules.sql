{#- Every mutable column with its Postgres type, in output order. Rendered into merge_update_columns,
    the empty `existing` stub and the change-detection row() comparison so a column is added once. -#}
{% set cols = [
    ('season', 'smallint'), ('game_type', 'text'), ('week', 'smallint'), ('gameday', 'date'),
    ('weekday', 'text'), ('gametime', 'time'), ('time_of_day', 'text'),
    ('away_team_id', 'integer'), ('home_team_id', 'integer'),
    ('away_score', 'smallint'), ('home_score', 'smallint'), ('result', 'smallint'), ('total', 'smallint'),
    ('winning_team_id', 'integer'), ('winning_team_location', 'text'),
    ('losing_team_id', 'integer'), ('losing_team_location', 'text'),
    ('overtime', 'boolean'), ('location', 'text'), ('div_game', 'boolean'),
    ('gsis_id', 'integer'), ('nfl_detail_id', 'text'), ('pfr_id', 'text'), ('pff_id', 'integer'),
    ('espn_id', 'integer'), ('ftn_id', 'integer'),
    ('away_rest', 'smallint'), ('home_rest', 'smallint'),
    ('away_moneyline', 'smallint'), ('home_moneyline', 'smallint'),
    ('spread_line', 'double precision'), ('away_spread_odds', 'smallint'), ('home_spread_odds', 'smallint'),
    ('total_line', 'double precision'), ('over_odds', 'smallint'), ('under_odds', 'smallint'),
    ('roof', 'text'), ('surface', 'text'), ('temp', 'smallint'), ('wind', 'smallint'),
    ('away_coach_id', 'integer'), ('home_coach_id', 'integer'), ('referee_id', 'integer'), ('stadium_id', 'integer'),
] %}
{% set names = cols | map(attribute=0) | list %}
{{
    config(
        alias='schedules',
        materialized='incremental',
        unique_key='game_id',
        merge_update_columns=names + ['updated_at'],
    )
}}
-- Game fact/dimension: one row per game in clean.schedules (1999+, played and scheduled), keyed by
-- the integer game_id from reference.game_identities, with every team, coach, referee and venue
-- resolved to its warehouse key. Closing lines and odds, the divisional/neutral-site flags and
-- roof/surface are carried through untouched (surface is trimmed: nflverse has 'grass ' with a
-- trailing space). gametime is kept as the source gives it (US Eastern); time_of_day
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
        s.location,
        s.div_game,
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
        s.away_spread_odds,
        s.home_spread_odds,
        s.total_line,
        s.over_odds,
        s.under_odds,
        s.roof,
        nullif(trim(s.surface), '')                             as surface,
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
    select null::integer as game_id,
           {% for name, type in cols %}null::{{ type }} as {{ name }},
           {% endfor %}null::timestamptz as created_at, null::timestamptz as updated_at
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
   or row({% for n in names %}s.{{ n }}{{ ', ' if not loop.last }}{% endfor %})
      is distinct from
      row({% for n in names %}e.{{ n }}{{ ', ' if not loop.last }}{% endfor %})
