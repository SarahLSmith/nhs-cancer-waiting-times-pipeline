{#-
  reports_icb_summary: the table for the panel. The six most recent months of
  reports_icb_monthly. "Most recent" is taken from the data, not from today's
  date, so the table is correct for whatever data was last loaded.
-#}
select *
from {{ ref('reports_icb_monthly') }}
where period_start > (select max(period_start) from {{ ref('reports_icb_monthly') }}) - interval 6 months
