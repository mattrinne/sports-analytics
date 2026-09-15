{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='alias',
        merge_update_columns=['coach_id', 'coach_name', 'source', 'updated_at'],
        on_schema_change='fail',
        full_refresh=false,
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
        pre_hook="create sequence if not exists {{ this.schema }}.coach_id_seq",
    )
}}
-- Master data for coaches: one row per spelling seen anywhere (clean.coaching_staff plus every
-- reference_mappings row for domain coach_name), resolved to a canonical name and a coach_id.
-- Ids are minted here from a sequence, one per canonical name, and never reused. Incremental:
-- only new spellings, or spellings whose canonical/id changed because a mapping was added, are
-- written, so updated_at is meaningful. When a mapping merges two names that both had ids, the
-- canonical name's id survives and the other is retired; a new canonical name inherits the id of
-- a spelling that now resolves to it when no other coach holds that id. full_refresh=false: to renumber
-- deliberately, drop this table and the sequence and build again.
with mappings as (
    select source_value, canonical_value
    from {{ ref('reference_mappings') }}
    where domain = 'coach_name'
),
spellings as (
    select distinct coach as alias from {{ ref('coaching_staff') }} where coach is not null
    union
    select source_value from mappings
),
resolved as (
    select
        s.alias,
        coalesce(m.canonical_value, s.alias)                             as coach_name,
        case when m.source_value is null then 'canonical' else 'reference_mappings' end as source
    from spellings s
    left join mappings m on m.source_value = s.alias
),
existing as (
    {% if is_incremental() %}
    select alias, coach_id, coach_name, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as coach_id, null::text as coach_name,
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
),
known_ids as (
    -- id already held by rows that resolve to this canonical name today
    select e.coach_name, min(e.coach_id) as coach_id
    from existing e
    where e.coach_name in (select coach_name from resolved)
    group by e.coach_name
),
inherited_ids as (
    -- a canonical name with no id yet takes the id of a spelling that now resolves to it, but
    -- only if every row holding that id resolves to it (the id would otherwise be retired)
    select r.coach_name, min(e.coach_id) as coach_id
    from resolved r
    join existing e on e.alias = r.alias
    where r.coach_name not in (select coach_name from known_ids)
      and not exists (
          select 1
          from existing e2
          left join resolved r2 on r2.alias = e2.alias
          where e2.coach_id = e.coach_id
            and coalesce(r2.coach_name, '') <> r.coach_name
      )
    group by r.coach_name
),
new_canonicals as (
    select coach_name, nextval('{{ this.schema }}.coach_id_seq')::integer as coach_id
    from (
        select distinct r.coach_name
        from resolved r
        left join known_ids k on k.coach_name = r.coach_name
        where k.coach_id is null
          and r.coach_name not in (select coach_name from inherited_ids)
        order by 1
    ) x
),
assigned as (
    select r.alias, r.coach_name, r.source, coalesce(k.coach_id, i.coach_id, n.coach_id) as coach_id
    from resolved r
    left join known_ids k on k.coach_name = r.coach_name
    left join inherited_ids i on i.coach_name = r.coach_name
    left join new_canonicals n on n.coach_name = r.coach_name
)
select
    a.alias,
    a.coach_id,
    a.coach_name,
    a.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from assigned a
left join existing e on e.alias = a.alias
where e.alias is null
   or (e.coach_id, e.coach_name, e.source) is distinct from (a.coach_id, a.coach_name, a.source)
