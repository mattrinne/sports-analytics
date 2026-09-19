{{
    config(
        merge_update_columns=['coach_id', 'coach_name', 'source', 'updated_at'],
        full_refresh=false,
        pre_hook="create sequence if not exists {{ this.schema }}.coach_id_seq",
    )
}}
-- Master data for coaches: one row per spelling seen anywhere (clean.coaching_staff, the head
-- coaches named per game in clean.schedules, and every reference_mappings row for domain
-- coach_name), resolved to a canonical name and a coach_id.
-- Ids are minted here from a sequence, one per canonical name, and never reused. Incremental:
-- only new spellings, or spellings whose canonical/id changed because a mapping was added, are
-- written, so updated_at is meaningful. When a mapping merges two names that both had ids, the
-- canonical name's id survives and the other is retired; a new canonical name inherits the id of
-- a spelling that now resolves to it when no other coach holds that id. full_refresh=false: to renumber
-- deliberately, drop this table and the sequence and build again.
{{ identity_rows('coach', 'coach_name', [
    (ref('coaching_staff'), 'coach', none),
    (ref('schedules'), 'home_coach', none),
    (ref('schedules'), 'away_coach', none),
]) }}
