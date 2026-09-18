-- One referee_id per canonical name and one canonical name per referee_id.
select 'name with several ids' as problem, referee_name as value
from {{ ref('referee_identities') }} group by referee_name having count(distinct referee_id) > 1
union all
select 'id with several names', referee_id::text
from {{ ref('referee_identities') }} group by referee_id having count(distinct referee_name) > 1
