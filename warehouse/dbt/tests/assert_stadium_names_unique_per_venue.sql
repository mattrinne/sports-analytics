{{ config(severity='warn') }}
-- A stadium name should belong to one venue code. Warns on new upstream mis-tags; nfl.stadiums
-- already picks the majority name per venue. Known and accepted: the 2026 Jaguars London game
-- tagged with the Jaguars' own code JAX00 instead of LON02.
select stadium, string_agg(distinct stadium_id, ', ') as stadium_ids
from {{ ref('schedules') }}
where stadium is not null and stadium_id is not null
  and not (stadium_id = 'JAX00' and stadium ilike '%tottenham%')
group by stadium
having count(distinct stadium_id) > 1
