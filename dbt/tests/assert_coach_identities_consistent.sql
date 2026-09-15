-- One coach_id per canonical name and one canonical name per coach_id.
select 'name with several ids' as problem, coach_name as value
from {{ ref('coach_identities') }} group by coach_name having count(distinct coach_id) > 1
union all
select 'id with several names', coach_id::text
from {{ ref('coach_identities') }} group by coach_id having count(distinct coach_name) > 1
