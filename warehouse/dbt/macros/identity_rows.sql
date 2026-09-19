{#
  Body shared by the name-keyed identity models (coach_identities, referee_identities).
  entity   'coach' -> columns coach_id / coach_name, sequence <schema>.coach_id_seq, mapping domain
           passed as `domain` (e.g. 'coach_name').
  sources  list of (relation, column, extra_where_or_none): every distinct non-null value of each is a
           spelling. The reference_mappings source values for the domain are always added.
  Rules: spellings -> canonical via reference_mappings; ids come from the sequence, one per canonical
  name, never reused; an existing id is kept (known_ids), a new canonical inherits the id of a
  spelling that now resolves to it if nobody else holds that id (inherited_ids), otherwise nextval.
  Emits only new rows or rows whose (id, name, source) changed, so updated_at is meaningful.
  The calling model keeps its own config() (unique_key alias, merge, full_refresh=false, pre_hook
  creating the sequence) and its header comment.
#}
{% macro identity_rows(entity, domain, sources) -%}
{%- set id_col = entity ~ '_id' -%}
{%- set name_col = entity ~ '_name' -%}
with mappings as (
    select source_value, canonical_value
    from {{ ref('reference_mappings') }}
    where domain = '{{ domain }}'
),
spellings as (
    {% for rel, col, extra in sources -%}
    select distinct {{ col }} as alias from {{ rel }}
    where {{ col }} is not null{% if extra %} and {{ extra }}{% endif %}
    union
    {% endfor -%}
    select source_value from mappings
),
resolved as (
    select
        s.alias,
        coalesce(m.canonical_value, s.alias)                             as {{ name_col }},
        case when m.source_value is null then 'canonical' else 'reference_mappings' end as source
    from spellings s
    left join mappings m on m.source_value = s.alias
),
existing as (
    {% if is_incremental() %}
    select alias, {{ id_col }}, {{ name_col }}, source, created_at from {{ this }}
    {% else %}
    select null::text as alias, null::integer as {{ id_col }}, null::text as {{ name_col }},
           null::text as source, null::timestamptz as created_at
    where false
    {% endif %}
),
known_ids as (
    -- id already held by rows that resolve to this canonical name today
    select e.{{ name_col }}, min(e.{{ id_col }}) as {{ id_col }}
    from existing e
    where e.{{ name_col }} in (select {{ name_col }} from resolved)
    group by e.{{ name_col }}
),
inherited_ids as (
    -- a canonical name with no id yet takes the id of a spelling that now resolves to it, but
    -- only if every row holding that id resolves to it (the id would otherwise be retired)
    select r.{{ name_col }}, min(e.{{ id_col }}) as {{ id_col }}
    from resolved r
    join existing e on e.alias = r.alias
    where r.{{ name_col }} not in (select {{ name_col }} from known_ids)
      and not exists (
          select 1
          from existing e2
          left join resolved r2 on r2.alias = e2.alias
          where e2.{{ id_col }} = e.{{ id_col }}
            and coalesce(r2.{{ name_col }}, '') <> r.{{ name_col }}
      )
    group by r.{{ name_col }}
),
new_canonicals as (
    select {{ name_col }}, nextval('{{ this.schema }}.{{ id_col }}_seq')::integer as {{ id_col }}
    from (
        select distinct r.{{ name_col }}
        from resolved r
        left join known_ids k on k.{{ name_col }} = r.{{ name_col }}
        where k.{{ id_col }} is null
          and r.{{ name_col }} not in (select {{ name_col }} from inherited_ids)
        order by 1
    ) x
),
assigned as (
    select r.alias, r.{{ name_col }}, r.source, coalesce(k.{{ id_col }}, i.{{ id_col }}, n.{{ id_col }}) as {{ id_col }}
    from resolved r
    left join known_ids k on k.{{ name_col }} = r.{{ name_col }}
    left join inherited_ids i on i.{{ name_col }} = r.{{ name_col }}
    left join new_canonicals n on n.{{ name_col }} = r.{{ name_col }}
)
select
    a.alias,
    a.{{ id_col }},
    a.{{ name_col }},
    a.source,
    coalesce(e.created_at, now())        as created_at,
    now()                                as updated_at
from assigned a
left join existing e on e.alias = a.alias
where e.alias is null
   or (e.{{ id_col }}, e.{{ name_col }}, e.source) is distinct from (a.{{ id_col }}, a.{{ name_col }}, a.source)
{%- endmacro %}
