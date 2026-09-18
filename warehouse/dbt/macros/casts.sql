{# Small cast helpers that keep the wide clean models readable. #}

{# nflverse 0/1 double flag -> boolean (NULL stays NULL). #}
{% macro flag(col, alias=none) -%}
    ({{ col }} = 1) as {{ alias or col }}
{%- endmacro %}

{% macro as_smallint(col, alias=none) -%}
    {{ col }}::smallint as {{ alias or col }}
{%- endmacro %}

{% macro as_integer(col, alias=none) -%}
    {{ col }}::integer as {{ alias or col }}
{%- endmacro %}

{% macro as_date(col, alias=none) -%}
    {{ col }}::date as {{ alias or col }}
{%- endmacro %}
