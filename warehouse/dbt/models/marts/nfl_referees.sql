{{
    config(
        alias='referees',
    )
}}
-- Referee dimension, derived from reference.referee_identities: one row per referee_id with the
-- canonical name. Identity (ids, spelling resolution) lives in the identities table; this is the
-- analysis surface. created_at = first time any spelling of the referee was seen.
select
    referee_id,
    referee_name,
    min(created_at)                      as created_at,
    max(updated_at)                      as updated_at
from {{ ref('referee_identities') }}
group by referee_id, referee_name
