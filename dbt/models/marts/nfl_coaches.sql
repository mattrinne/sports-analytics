{{
    config(
        alias='coaches',
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='coach_name',
        merge_update_columns=['updated_at'],
        on_schema_change='fail',
        full_refresh=false,
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
        pre_hook="create sequence if not exists {{ this.schema }}.coach_id_seq",
        post_hook="delete from {{ this }} where coach_name in (select source_value from {{ ref('reference_mappings') }} where domain = 'coach_name')",
    )
}}
-- Persisted dimension: one row per distinct coach in clean.coaching_staff after resolving
-- spellings through nfl.reference_mappings (domain coach_name). coach_id comes from a sequence,
-- so ids are never reused; existing rows keep coach_id/created_at and only updated_at moves when
-- a coaching_staff partition mentioning them is reloaded. Adding a mapping later removes the
-- alias row (post_hook) and, if the canonical name is new, gives it the next id.
-- full_refresh=false: dbt skips this model under --full-refresh. To renumber deliberately, drop
-- nfl.coaches and nfl.coach_id_seq and build again.
with mappings as (
    select source_value, canonical_value
    from {{ ref('reference_mappings') }}
    where domain = 'coach_name' and (source_system is null or source_system = 'wikipedia')
),
existing as (
    {% if is_incremental() %}
    select coach_id, coach_name, created_at from {{ this }}
    {% else %}
    select null::integer as coach_id, null::text as coach_name, null::timestamptz as created_at
    where false
    {% endif %}
),
source_coaches as (
    select coalesce(m.canonical_value, s.coach) as coach_name
    from {{ ref('coaching_staff') }} s
    left join mappings m on m.source_value = s.coach
    where s.coach is not null
    {% if is_incremental() %}
      and (
          s._loaded_at > (select coalesce(max(updated_at), '-infinity'::timestamptz) from {{ this }})
          or coalesce(m.canonical_value, s.coach) not in (select coach_name from existing)
      )
    {% endif %}
    group by 1
),
ordered as (
    select s.coach_name, e.coach_id, e.created_at
    from source_coaches s
    left join existing e on e.coach_name = s.coach_name
    order by s.coach_name
)
select
    coalesce(coach_id, nextval('{{ this.schema }}.coach_id_seq'))::integer as coach_id,
    coach_name,
    coalesce(created_at, now())          as created_at,
    now()                                as updated_at
from ordered
