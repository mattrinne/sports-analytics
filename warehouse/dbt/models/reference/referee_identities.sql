{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='alias',
        merge_update_columns=['referee_id', 'referee_name', 'source', 'updated_at'],
        on_schema_change='fail',
        full_refresh=false,
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
        pre_hook="create sequence if not exists {{ this.schema }}.referee_id_seq",
    )
}}
-- Master data for referees (crew chiefs): one row per spelling seen anywhere (clean.schedules.referee
-- 1999+, the Referee position in clean.officials 2015+, and every reference_mappings row for domain
-- referee_name), resolved to a canonical name and a referee_id. nflverse's officials.official_id is not
-- usable as the key: it was renumbered in 2023 and does not exist before 2015, so ids are minted here
-- from a sequence, one per canonical name, and never reused. Same incremental and id-inheritance rules
-- as coach_identities. full_refresh=false: to renumber deliberately, drop this table and the sequence
-- and build again.
with mappings as (
    select source_value, canonical_value
    from {{ ref('reference_mappings') }}
    where domain = 'referee_name'
),
spellings as (
    select distinct referee as alias from {{ ref('schedules') }} where referee is not null
    union
    select official_name from {{ ref('officials') }} where position = 'Referee' and official_name is not null
    union
    select source_value from mappings
),
resolved as (
    select
        s.alias,
        coalesce(m.canonical_value, s.alias)                             as referee_name,
        case when m.source_value is null then 'canonical' else 'reference_mappings' end as source
    from spellings s
    left join mappings m on m.source_value = s.alias
),
existing as (
    {% if is_incremental() %}
    select alias, referee_id, referee_name, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as referee_id, null::text as referee_name,
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
),
known_ids as (
    -- id already held by rows that resolve to this canonical name today
    select e.referee_name, min(e.referee_id) as referee_id
    from existing e
    where e.referee_name in (select referee_name from resolved)
    group by e.referee_name
),
inherited_ids as (
    -- a canonical name with no id yet takes the id of a spelling that now resolves to it, but
    -- only if every row holding that id resolves to it (the id would otherwise be retired)
    select r.referee_name, min(e.referee_id) as referee_id
    from resolved r
    join existing e on e.alias = r.alias
    where r.referee_name not in (select referee_name from known_ids)
      and not exists (
          select 1
          from existing e2
          left join resolved r2 on r2.alias = e2.alias
          where e2.referee_id = e.referee_id
            and coalesce(r2.referee_name, '') <> r.referee_name
      )
    group by r.referee_name
),
new_canonicals as (
    select referee_name, nextval('{{ this.schema }}.referee_id_seq')::integer as referee_id
    from (
        select distinct r.referee_name
        from resolved r
        left join known_ids k on k.referee_name = r.referee_name
        where k.referee_id is null
          and r.referee_name not in (select referee_name from inherited_ids)
        order by 1
    ) x
),
assigned as (
    select r.alias, r.referee_name, r.source, coalesce(k.referee_id, i.referee_id, n.referee_id) as referee_id
    from resolved r
    left join known_ids k on k.referee_name = r.referee_name
    left join inherited_ids i on i.referee_name = r.referee_name
    left join new_canonicals n on n.referee_name = r.referee_name
)
select
    a.alias,
    a.referee_id,
    a.referee_name,
    a.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from assigned a
left join existing e on e.alias = a.alias
where e.alias is null
   or (e.referee_id, e.referee_name, e.source) is distinct from (a.referee_id, a.referee_name, a.source)
