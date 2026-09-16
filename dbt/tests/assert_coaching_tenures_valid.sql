-- Tenures must be well-formed: start <= end when both are known, and a coach cannot hold the
-- same role with the same franchise in two overlapping non-interim tenures.
select 'start after end' as problem, coach_id, team_id, role_id, first_season
from {{ ref('nfl_coaching_tenures') }}
where end_date < start_date
union all
select 'overlap', a.coach_id, a.team_id, a.role_id, a.first_season
from {{ ref('nfl_coaching_tenures') }} a
join {{ ref('nfl_coaching_tenures') }} b
  on b.coach_id = a.coach_id and b.team_id = a.team_id and b.role_id = a.role_id
 and b.is_interim = a.is_interim and b.first_season > a.first_season
 and b.start_date is not null and a.end_date is not null and b.start_date <= a.end_date
where not a.is_interim
