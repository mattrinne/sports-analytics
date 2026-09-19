{{
    config(
        merge_update_columns=['referee_id', 'referee_name', 'source', 'updated_at'],
        full_refresh=false,
        pre_hook="create sequence if not exists {{ this.schema }}.referee_id_seq",
    )
}}
-- Master data for referees (crew chiefs): one row per spelling seen anywhere (clean.schedules.referee
-- 1999+, the Referee position in clean.officials 2015+, and every reference_mappings row for domain
-- referee_name), resolved to a canonical name and a referee_id. nflverse's officials.official_id is not
-- usable as the key: it was renumbered in 2023 and does not exist before 2015, so ids are minted here
-- from a sequence, one per canonical name, and never reused. Same incremental and id-inheritance rules
-- as coach_identities. full_refresh=false: to renumber deliberately, drop this table and the sequence
-- and build again.
{{ identity_rows('referee', 'referee_name', [
    (ref('schedules'), 'referee', none),
    (ref('officials'), 'official_name', "position = 'Referee'"),
]) }}
