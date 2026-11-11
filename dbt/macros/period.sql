{#-
  Convert an NHS "Period" value to a real date (the first day of the month).

  NHS files use two styles: ISO (2024-04-01) in older files and day/month/year
  (01/04/2025) in newer ones. Both are handled here, in one place.
-#}
{% macro period_expr(column_name) %}
    case
        when {{ column_name }} like '%/%' then strptime({{ column_name }}, '%d/%m/%Y')::date
        else strptime({{ column_name }}, '%Y-%m-%d')::date
    end
{% endmacro %}
