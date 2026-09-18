{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='alias',
        merge_update_columns=['game_id', 'game_key', 'source', 'updated_at'],
        on_schema_change='fail',
        full_refresh=false,
        contract={'enforced': true},
        persist_docs={'relation': true, 'columns': true},
        pre_hook="create sequence if not exists {{ this.schema }}.game_id_seq",
    )
}}
-- Master data for games: every id a source uses for a game (alias), resolved to the nflverse
-- game_id string (game_key) and to an integer game_id minted here from a sequence, in order of
-- first appearance, never reused. Aliases: the nflverse game_id itself (source = canonical; used by
-- clean.pbp, participation, player/team stats as game_id / nflverse_game_id) and the GSIS old_game_id
-- (source = old_game_id; used by clean.officials.game_id) when it names exactly one game (unscheduled
-- future games share placeholder old ids until the schedule firms up). Incremental: only new or
-- changed aliases are written. full_refresh=false: to renumber deliberately, drop this table and
-- the sequence and build again.
with games as (
    select game_id as game_key, old_game_id from {{ ref('schedules') }}
),
aliases as (
    select game_key as alias, game_key, 'canonical' as source from games
    union all
    select old_game_id, game_key, 'old_game_id'
    from games
    where old_game_id is not null
      and old_game_id <> game_key
      and old_game_id in (select old_game_id from games group by 1 having count(*) = 1)
),
existing as (
    {% if is_incremental() %}
    select alias, game_id, game_key, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as game_id, null::text as game_key,
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
),
known_ids as (
    select game_key, min(game_id) as game_id from existing group by game_key
),
new_ids as (
    select game_key, nextval('{{ this.schema }}.game_id_seq')::integer as game_id
    from (
        select distinct a.game_key
        from aliases a
        where a.game_key not in (select game_key from known_ids)
        order by 1
    ) x
),
assigned as (
    select a.alias, a.game_key, a.source, coalesce(k.game_id, n.game_id) as game_id
    from aliases a
    left join known_ids k on k.game_key = a.game_key
    left join new_ids n on n.game_key = a.game_key
)
select
    a.alias,
    a.game_id,
    a.game_key,
    a.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from assigned a
left join existing e on e.alias = a.alias
where e.alias is null
   or (e.game_id, e.game_key, e.source) is distinct from (a.game_id, a.game_key, a.source)
