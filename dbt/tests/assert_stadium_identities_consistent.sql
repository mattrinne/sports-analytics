-- One stadium_id per venue code and one venue code per stadium_id.
select 'key with several ids' as problem, stadium_code as value
from {{ ref('stadium_identities') }} group by stadium_code having count(distinct stadium_id) > 1
union all
select 'id with several keys', stadium_id::text
from {{ ref('stadium_identities') }} group by stadium_id having count(distinct stadium_code) > 1
