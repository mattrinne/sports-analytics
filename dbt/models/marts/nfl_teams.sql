{{
    config(
        alias='teams',
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='team_id',
        merge_update_columns=['team_abbr', 'team_name', 'team_nick', 'team_conf', 'team_division', 'updated_at'],
        on_schema_change='fail',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- Franchise dimension: the 32 current teams, one per canonical code in reference.team_identities,
-- with attributes from clean.teams. team_id is nflverse's numeric franchise id. Incremental so that
-- updated_at moves only when an attribute actually changes.
with src as (
    select
        i.team_id,
        i.team_abbr,
        t.team_name,
        t.team_nick,
        t.team_conf,
        t.team_division
    from {{ ref('team_identities') }} i
    join {{ ref('teams') }} t on t.team_abbr = i.team_abbr
    where i.source = 'canonical'
),
existing as (
    {% if is_incremental() %}
    select * from {{ this }}
    {% else %}
    select null::integer as team_id, null::text as team_abbr, null::text as team_name,
           null::text as team_nick, null::text as team_conf, null::text as team_division,
           null::timestamptz as created_at, null::timestamptz as updated_at
    where false
    {% endif %}
)
select
    s.team_id,
    s.team_abbr,
    s.team_name,
    s.team_nick,
    s.team_conf,
    s.team_division,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from src s
left join existing e on e.team_id = s.team_id
where e.team_id is null
   or (e.team_abbr, e.team_name, e.team_nick, e.team_conf, e.team_division)
      is distinct from (s.team_abbr, s.team_name, s.team_nick, s.team_conf, s.team_division)
