{{
    config(
        alias='stadiums',
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='stadium_id',
        merge_update_columns=['stadium_code', 'stadium_name', 'roof', 'surface', 'first_season', 'last_season', 'updated_at'],
        on_schema_change='fail',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- Venue dimension: one row per venue, keyed by the integer stadium_id minted in
-- reference.stadium_identities from nflverse's venue code (stadium_code, e.g. JAX00 or LON02; the
-- same building keeps its code through naming-rights changes).
-- stadium_name is the name used in the venue's latest season after season-bounded corrections
-- from reference_mappings (domain stadium); when a season carries two names for one code (a
-- mis-tagged game) the more frequent one wins. roof is dome / outdoors / retractable (a venue
-- recorded both open and closed), surface the latest season's value. Incremental so that
-- updated_at moves only when an attribute actually changes.
with mappings as (
    select source_value, canonical_value, coalesce(valid_from, 0) as valid_from, coalesce(valid_to, 9999) as valid_to
    from {{ ref('reference_mappings') }}
    where domain = 'stadium'
),
games as (
    select
        i.stadium_id,
        g.stadium_id                             as stadium_code,
        coalesce(m.canonical_value, g.stadium)   as stadium,
        g.season,
        nullif(g.roof, '')                       as roof,
        nullif(btrim(g.surface), '')             as surface
    from {{ ref('schedules') }} g
    join {{ ref('stadium_identities') }} i on i.alias = g.stadium_id
    left join mappings m on m.source_value = g.stadium and g.season between m.valid_from and m.valid_to
    where g.stadium_id is not null
),
seasons as (
    select stadium_id, min(stadium_code) as stadium_code, min(season) as first_season, max(season) as last_season
    from games
    group by stadium_id
),
latest_name as (
    select distinct on (stadium_id) stadium_id, stadium as stadium_name
    from (select stadium_id, season, stadium, count(*) as n from games where stadium is not null group by 1, 2, 3) x
    order by stadium_id, season desc, n desc, stadium
),
latest_surface as (
    select distinct on (stadium_id) stadium_id, surface
    from (select stadium_id, season, surface, count(*) as n from games where surface is not null group by 1, 2, 3) x
    order by stadium_id, season desc, n desc, surface
),
roofs as (
    select
        stadium_id,
        case when bool_or(roof in ('open', 'closed')) then 'retractable'
             else mode() within group (order by roof) end as roof
    from games
    where roof is not null
    group by stadium_id
),
src as (
    select s.stadium_id, s.stadium_code, n.stadium_name, r.roof, f.surface, s.first_season, s.last_season
    from seasons s
    join latest_name n using (stadium_id)
    left join roofs r using (stadium_id)
    left join latest_surface f using (stadium_id)
),
existing as (
    {% if is_incremental() %}
    select * from {{ this }}
    {% else %}
    select null::integer as stadium_id, null::text as stadium_code, null::text as stadium_name, null::text as roof, null::text as surface,
           null::smallint as first_season, null::smallint as last_season,
           null::timestamptz as created_at, null::timestamptz as updated_at
    where false
    {% endif %}
)
select
    s.stadium_id,
    s.stadium_code,
    s.stadium_name,
    s.roof,
    s.surface,
    s.first_season,
    s.last_season,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from src s
left join existing e on e.stadium_id = s.stadium_id
where e.stadium_id is null
   or (e.stadium_code, e.stadium_name, e.roof, e.surface, e.first_season, e.last_season)
      is distinct from (s.stadium_code, s.stadium_name, s.roof, s.surface, s.first_season, s.last_season)
