{#-
  reports_icb_monthly: one row per month, ICB and standard, for the headline
  measures (all cancers, all routes, all treatments).

  Performance is recalculated from the counts (within / total). It is never
  averaged across ICBs or months, because that would give the wrong answer.
  Frimley is excluded (see linked_cwt and the README limitations).
-#}
select
    period_start,
    icb_code,
    any_value(icb_name)                       as icb_name,
    standard,
    sum(total)                                as total,
    sum(within)                               as within_standard,
    sum(within) / nullif(sum(total), 0)       as performance,
    bool_or(status = 'provisional')           as includes_provisional,
    bool_or(after_icb_restructure)            as after_icb_restructure
from {{ ref('linked_cwt') }}
where org_group in ('ICB', 'Unknown')   -- not commissioning hubs, not excluded Frimley
  and is_headline                        -- the headline rows defined in clean_cwt
group by period_start, icb_code, standard
