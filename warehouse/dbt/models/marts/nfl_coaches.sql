{{
    config(
        alias='coaches',
        materialized='table',
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
    )
}}
-- Coach dimension, derived from reference.coach_identities: one row per coach_id with the
-- canonical name. Identity (ids, spelling resolution) lives in the identities table; this is the
-- analysis surface. created_at = first time any spelling of the coach was seen.
select
    coach_id,
    coach_name,
    min(created_at)                      as created_at,
    max(updated_at)                      as updated_at
from {{ ref('coach_identities') }}
group by coach_id, coach_name
