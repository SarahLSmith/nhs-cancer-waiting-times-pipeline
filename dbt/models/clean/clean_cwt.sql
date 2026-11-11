{#-
  clean_cwt: the one current, tidy row per month, organisation and measure.

  What this model does:
    1. Converts NHS text values to proper dates and numbers.
    2. Tidies labels (spaces, capital letters, footnote markers such as "(a)")
       so that the same thing always has the same name.
    3. If the same row appears in more than one file, keeps the Final version
       in preference to Provisional, and then the most recent load.

  Incremental behaviour:
    Only the months that arrived in a newer load are rebuilt. The whole month is
    replaced (delete + insert on period_start), so an organisation that dropped
    out between provisional and final versions does not linger.
    On a full rebuild (--full-refresh) everything is rebuilt.
-#}
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='period_start'
) }}

with landing as (
    select
        {{ period_expr('"Period"') }} as period_start,
        *
    from {{ source('landing', 'landing_cwt') }}
),

{% if is_incremental() %}
-- Months that arrived in a load newer than the last one we processed.
touched as (
    select distinct period_start
    from landing
    where load_id > {{ var('since_load_id', 0) }}
),
{% else %}
-- First build (or full refresh): every month.
touched as (
    select distinct period_start from landing
),
{% endif %}

candidates as (
    select l.*
    from landing l
    inner join touched t using (period_start)
),

tidied as (
    select
        period_start,
        upper(trim("Basis"))                                                  as basis,
        trim("Org_Code")                                                      as org_code,
        trim("Org_Name")                                                      as org_name,
        upper(trim("Parent_Org"))                                             as parent_org,
        trim("Standard_or_Item")                                              as standard,
        -- Remove footnote markers such as " (a)" from the end of cancer types.
        trim(regexp_replace("Cancer_Type", '\s*\(a\)\s*$', ''))               as cancer_type,
        -- Blank route or modality means "not applicable" (for example FDS has no treatment).
        coalesce(nullif(upper(trim("Referral_Route_or_Stage")), ''), 'NOT APPLICABLE')  as referral_route,
        coalesce(nullif(upper(trim("Treatment_Modality")), ''), 'NOT APPLICABLE')       as treatment_modality,
        try_cast("Total" as double)                                           as total,
        try_cast("Within" as double)                                          as within,
        try_cast("After" as double)                                           as after,
        try_cast("Performance" as double)                                     as performance,
        status,
        load_id,
        pulled_at,
        source_id
    from candidates
),

ranked as (
    select
        *,
        row_number() over (
            partition by period_start, basis, org_code, standard,
                         cancer_type, referral_route, treatment_modality
            order by
                case when status = 'final' then 1 else 2 end,  -- Final beats Provisional
                load_id desc                                   -- then the newest load
        ) as version_rank
    from tidied
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
    -- The headline rows the panel sees. Each standard has its own "all" row in NHS
    -- files, so this is defined once here and used everywhere else.
    cancer_type = 'ALL CANCERS' and (
           (standard = '62D' and referral_route = 'ALL ROUTES' and treatment_modality = 'ALL MODALITIES')
        or (standard = '31D' and referral_route = 'ALL STAGES' and treatment_modality = 'ALL MODALITIES')
        or (standard = 'FDS' and referral_route = 'ALL ROUTES' and treatment_modality = 'NOT APPLICABLE')
    ) as is_headline
from ranked
where version_rank = 1
