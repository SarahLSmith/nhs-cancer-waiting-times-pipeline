{#-
  linked_cwt: clean_cwt with the April 2026 ICB changes applied.

  Commissioner rows that use an ICB code closed on 31 March 2026 are given the
  code of the ICB that replaced it (see reference/icb_mapping_2026.csv).
  Frimley is marked 'excluded': it is kept here so the national totals still
  reconcile, but it is left out of ICB-level reports (see README, limitations).
-#}
with mapped as (
    select
        c.*,
        m.new_org_code,
        m.new_org_name,
        m.treatment as mapping_treatment
    from {{ ref('clean_cwt') }} c
    left join {{ ref('icb_mapping_2026') }} m
        on c.basis = 'COMMISSIONER'
       and c.org_code = m.old_org_code
)

select
    period_start,
    basis,
    org_code,
    org_name,
    parent_org,
    standard,
    cancer_type,
    referral_route,
    treatment_modality,
    total,
    within,
    after,
    performance,
    status,
    source_id,
    load_id,
    pulled_at,
    is_headline,
    -- The ICB this row belongs to after the April 2026 change.
    case when basis = 'COMMISSIONER' then coalesce(new_org_code, org_code) end as icb_code,
    case when basis = 'COMMISSIONER' then upper(coalesce(new_org_name, org_name)) end as icb_name,
    mapping_treatment,
    period_start >= date '2026-04-01' as after_icb_restructure,
    -- What kind of commissioner this row is. Only 'ICB' and 'Unknown' go into ICB reports.
    case
        when basis <> 'COMMISSIONER' then 'Provider'
        when mapping_treatment = 'excluded' then 'Excluded (Frimley)'
        when org_name like '%COMMISSIONING HUB%' then 'Commissioning hub'
        when org_code = 'UNKNOWN' then 'Unknown'
        else 'ICB'
    end as org_group
from mapped
