-- One game_id per nflverse game and one nflverse game per game_id.
select 'key with several ids' as problem, game_key as value
from {{ ref('game_identities') }} group by game_key having count(distinct game_id) > 1
union all
select 'id with several keys', game_id::text
from {{ ref('game_identities') }} group by game_id having count(distinct game_key) > 1
