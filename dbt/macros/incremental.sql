{# Incremental filter for clean models: on an incremental run only take source rows whose raw
   load timestamp is newer than anything already in the target. raw.* is reloaded one whole
   season at a time with a fresh _loaded_at, so a reloaded season comes through in full and is
   upserted by primary key. Emits "and <cond>" so it can follow any existing where clause. #}
{% macro only_new(loaded_at_expr) -%}
    {%- if is_incremental() %}
    and {{ loaded_at_expr }} > (select coalesce(max(_loaded_at), '-infinity'::timestamptz) from {{ this }})
    {%- endif %}
{%- endmacro %}
