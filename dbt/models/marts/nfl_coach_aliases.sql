{{ config(alias='coach_aliases') }}
-- Every known spelling of a coach -> coach_id: the canonical name itself plus each
-- reference_mappings row for the coach_name domain. Join names from any source through this.
select c.coach_id, c.coach_name, c.coach_name as alias, null::text as source_system
from {{ ref('nfl_coaches') }} c
union all
select c.coach_id, c.coach_name, m.source_value, m.source_system
from {{ ref('reference_mappings') }} m
join {{ ref('nfl_coaches') }} c on c.coach_name = m.canonical_value
where m.domain = 'coach_name'
