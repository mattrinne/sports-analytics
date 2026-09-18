{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='alias',
        merge_update_columns=['stadium_id', 'stadium_code', 'source', 'updated_at'],
        on_schema_change='fail',
        full_refresh=false,
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
        pre_hook="create sequence if not exists {{ this.schema }}.stadium_id_seq",
    )
}}
-- Master data for venues: every nflverse venue code seen in clean.schedules (alias, e.g. JAX00),
-- resolved to an integer stadium_id minted here from a sequence in order of first appearance and
-- never reused. The code is stable through naming-rights changes, so it is its own canonical value
-- (stadium_code) and no mappings apply. Incremental: only new or changed codes are written.
-- full_refresh=false: to renumber deliberately, drop this table and the sequence and build again.
with codes as (
    select distinct stadium_id as alias from {{ ref('schedules') }} where stadium_id is not null
),
existing as (
    {% if is_incremental() %}
    select alias, stadium_id, stadium_code, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as stadium_id, null::text as stadium_code,
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
),
new_ids as (
    select alias, nextval('{{ this.schema }}.stadium_id_seq')::integer as stadium_id
    from (select c.alias from codes c where c.alias not in (select alias from existing) order by 1) x
),
assigned as (
    select c.alias, coalesce(e.stadium_id, n.stadium_id) as stadium_id, c.alias as stadium_code, 'canonical' as source
    from codes c
    left join existing e on e.alias = c.alias
    left join new_ids n on n.alias = c.alias
)
select
    a.alias,
    a.stadium_id,
    a.stadium_code,
    a.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from assigned a
left join existing e on e.alias = a.alias
where e.alias is null
   or (e.stadium_id, e.stadium_code, e.source) is distinct from (a.stadium_id, a.stadium_code, a.source)
