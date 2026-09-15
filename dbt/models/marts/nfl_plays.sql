{{ config(alias='plays') }}
-- Play-by-play joined to NGS participation charting: personnel packages, formation, coverage,
-- pass rushers, players on the field. Participation exists from 2016 and lags a season behind;
-- scheme columns are NULL for plays that were not charted (runs, special teams, some passes).
select
    p.*,
    pa.offense_formation,
    pa.offense_personnel,
    pa.n_offense,
    pa.defense_personnel,
    pa.n_defense,
    pa.defenders_in_box,
    pa.number_of_pass_rushers,
    pa.defense_man_zone_type,
    pa.defense_coverage_type,
    pa.was_pressure,
    pa.time_to_throw,
    pa.ngs_air_yards,
    pa.route,
    pa.offense_players,
    pa.defense_players,
    pa.offense_names,
    pa.defense_names,
    pa.offense_positions,
    pa.defense_positions,
    pa.nflverse_game_id is not null as has_participation
from {{ ref('pbp') }} p
left join {{ ref('participation') }} pa
       on pa.nflverse_game_id = p.game_id
      and pa.play_id = p.play_id
