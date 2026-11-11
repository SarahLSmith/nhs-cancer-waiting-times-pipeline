# Data dictionary

Column meanings for every table the pipeline builds. Source columns come from the NHS England "Monthly Combined CSV" files, which are read exactly as published.

## Source file columns (`landing_cwt`)

| Column | Meaning |
|---|---|
| `Period` | The month, as published. ISO style (`2024-04-01`) in 2022-23 to 2024-25 files; day/month/year (`01/04/2025`) in later files. |
| `Basis` | `Provider` (a hospital trust or provider) or `Commissioner` (an ICB, sub-ICB, commissioning hub or UNKNOWN). |
| `Org_Code` | NHS organisation code. `Total` marks the national total row in provider rows. |
| `Parent_Org` | NHS England region. Capitalisation varies between files. |
| `Org_Name` | Name of the organisation as published. |
| `Standard_or_Item` | The measure: `62D` (62-day), `31D` (31-day), `FDS` (Faster Diagnosis Standard), or referral counts (`Urgent Suspected Cancer referral`, `Urgent Breast Symptomatic referral`). |
| `Cancer_Type` | Cancer group, for example `ALL CANCERS` or `Breast`. Some names carry a footnote such as `(a)`. |
| `Referral_Route_or_Stage` | How the patient was referred (for example `URGENT SUSPECTED CANCER`), or the stage for 31-day (`ALL STAGES`). Capitalisation varies. |
| `Treatment_Modality` | Type of treatment (for example `SURGERY`). Blank for measures that do not split by treatment. |
| `Total` | Number of patients in the measure. Can be a fraction (x.5) for 62-day, as the NHS apportions some patients. |
| `Within` | Number of patients treated within the standard's time limit. |
| `After` | Number of patients treated after the time limit. |
| `Performance` | `Within` divided by `Total`, as published (a proportion from 0 to 1). |
| `Within_14_days` ... `After_28_days` | Detailed time bands. Not used by the headline reports. |

## Pipeline metadata (added to every landing row)

| Column | Meaning |
|---|---|
| `source_id` | Which entry in `config/sources.yml` the row came from. |
| `status` | `final` or `provisional`, as declared in `config/sources.yml`. |
| `source_sha256` | Fingerprint of the file the row came from. |
| `load_id` | Number of the load that added the row. Higher is newer. |
| `pulled_at` | When the file was downloaded (UTC). |

## `clean_cwt` (one current row per month, organisation and measure)

| Column | Meaning |
|---|---|
| `period_start` | First day of the month. |
| `basis` | `PROVIDER` or `COMMISSIONER`, upper case. |
| `org_code`, `org_name` | Organisation code and name, trimmed. |
| `standard` | `62D`, `31D`, `FDS`, or a referral count. |
| `cancer_type` | Cancer group, with footnote markers removed. |
| `referral_route` | Referral route or stage, upper case. Blank becomes `NOT APPLICABLE`. |
| `treatment_modality` | Treatment type, upper case. Blank becomes `NOT APPLICABLE`. |
| `total`, `within`, `after`, `performance` | Numbers converted from text. Anything that cannot be read becomes null. |
| `is_headline` | True for the headline rows the reports use (see D8 in `docs/decisions.md`). |
| `status`, `source_id`, `load_id`, `pulled_at` | Where the chosen version of this row came from. |

**Key (must be unique):** `period_start`, `basis`, `org_code`, `standard`, `cancer_type`, `referral_route`, `treatment_modality`.

## `icb_mapping_2026` (reference, from `reference/icb_mapping_2026.csv`)

| Column | Meaning |
|---|---|
| `old_org_code`, `old_org_name` | ICB code that was closed or changed on 1 April 2026. |
| `new_org_code`, `new_org_name` | ICB that replaced it. Blank for Frimley. |
| `treatment` | `merged` (moved into a new ICB), `boundary_change` (kept its code, changed area), or `excluded` (left out). |
| `source_reference` | Where in the ODS summary the row came from. |

## `linked_cwt` (`clean_cwt` plus ICB mapping)

Adds:

| Column | Meaning |
|---|---|
| `icb_code`, `icb_name` | The ICB after the April 2026 change. Names are upper case. |
| `mapping_treatment` | Copied from the mapping: `merged`, `boundary_change`, `excluded`, or null. |
| `after_icb_restructure` | True for months from April 2026 onwards. |
| `org_group` | `ICB`, `Unknown`, `Commissioning hub`, `Excluded (Frimley)`, or `Provider`. Decides which report a row appears in. |

## `reports_icb_monthly` and `reports_icb_summary`

| Column | Meaning |
|---|---|
| `period_start` | Month. |
| `icb_code`, `icb_name` | The ICB. |
| `standard` | `62D`, `31D` or `FDS`. |
| `total` | Patients in the measure for this ICB and month. |
| `within_standard` | Patients treated within the standard's time limit. |
| `performance` | `within_standard / total`, recalculated here. |
| `includes_provisional` | True if the month is provisional (NHS may still revise it). |
| `after_icb_restructure` | True from April 2026. |

`reports_icb_summary` holds the four most recent months of `reports_icb_monthly`.

## `load_log`

One row per file loaded: `load_id`, `source_id`, `status`, `sha256`, `pulled_at`, `source_url`, `rows_loaded`.

## `outputs/data_status.json`

| Field | Meaning |
|---|---|
| `last_pulled_utc` | When the newest file was downloaded. |
| `newest_month` | The latest month in the data. |
| `provisional_months` | How many months are still provisional. |
| `generated_at_utc` | When this status file was written. |
