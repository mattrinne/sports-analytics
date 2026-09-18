{{ config(severity='warn') }}
-- A stadium name should belong to one venue code. Warns on upstream mis-tags (e.g. a London game
-- carrying the home team's code); nfl.stadiums already picks the majority name per venue.
select stadium, string_agg(distinct stadium_id, ', ') as stadium_ids
from {{ ref('schedules') }}
where stadium is not null and stadium_id is not null
group by stadium
having count(distinct stadium_id) > 1
