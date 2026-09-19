-- The betting labels every analysis keys on: for played games, result and total are the score
-- difference/sum and the closing spread and total exist (true for every played game since 1999).
select game_id, 'result <> home_score - away_score' as problem
from {{ ref('nfl_schedules') }}
where home_score is not null and result is distinct from home_score - away_score
union all
select game_id, 'total <> home_score + away_score'
from {{ ref('nfl_schedules') }}
where home_score is not null and total is distinct from home_score + away_score
union all
select game_id, 'played game without closing line'
from {{ ref('nfl_schedules') }}
where home_score is not null and (spread_line is null or total_line is null)
