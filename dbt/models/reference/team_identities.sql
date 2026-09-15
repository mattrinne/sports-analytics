{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='alias',
        merge_update_columns=['team_id', 'team_abbr', 'source', 'updated_at'],
        on_schema_change='fail',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- Master data for teams: every team code used anywhere -> franchise team_id. The canonical set
-- is data-driven (home teams of the latest season in clean.schedules, resolved through
-- reference_mappings domain team_abbr, e.g. LA -> LAR); team_id is nflverse's numeric franchise
-- id from clean.teams, which a franchise keeps through relocations. nfl.teams is derived from
-- this table. A code that appears in the data without a row here fails
-- tests/assert_all_team_codes_resolve.
with mappings as (
    select source_value, canonical_value
    from {{ ref('reference_mappings') }}
    where domain = 'team_abbr'
),
current_codes as (
    select distinct coalesce(m.canonical_value, s.home_team) as team_abbr
    from {{ ref('schedules') }} s
    left join mappings m on m.source_value = s.home_team
    where s.season = (select max(season) from {{ ref('schedules') }})
),
spellings as (
    select team_abbr as alias, team_abbr, 'canonical' as source from current_codes
    union all
    select m.source_value, m.canonical_value, 'reference_mappings'
    from mappings m
    join current_codes c on c.team_abbr = m.canonical_value
),
resolved as (
    select s.alias, t.team_id::integer as team_id, s.team_abbr, s.source
    from spellings s
    join {{ ref('teams') }} t on t.team_abbr = s.team_abbr
),
existing as (
    {% if is_incremental() %}
    select alias, team_id, team_abbr, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as team_id, null::text as team_abbr,
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
)
select
    r.alias,
    r.team_id,
    r.team_abbr,
    r.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from resolved r
left join existing e on e.alias = r.alias
where e.alias is null
   or (e.team_id, e.team_abbr, e.source) is distinct from (r.team_id, r.team_abbr, r.source)
