# Decisions log

Each decision records what was chosen, why, and the evidence behind it. Newest decisions are at the bottom.

## D1. Use the cumulative combined CSVs, not the monthly files
- **Chosen:** one file per financial year (2022-23 to 2025-26, all Final) plus one file for Apr to Aug 2026 (Provisional).
- **Why:** the NHS CWT page lists these cumulative files directly. They cover the full window in five downloads. The April 2026 file in this set is identical, row for row, to the separate monthly April 2026 file (checked: 25,965 of 25,965 rows match on every measure).
- **Source:** the "Monthly Combined CSV" section of https://www.england.nhs.uk/statistics/statistical-work-areas/cancer-waiting-times/
- **Change from the plan:** the plan named monthly files. Monthly files still work, and the ingest step accepts any file added to `config/sources.yml`.

## D2. Final beats Provisional
- **Chosen:** when the same row appears in more than one file, the Final version is kept. Between two versions of the same status, the newer load wins.
- **Why:** Final figures are NHS England's revised and checked figures. Provisional figures can still change.

## D3. Re-runs rebuild only what changed
- **Chosen:** downloads are skipped when their SHA-256 fingerprint is already in `load_log`. The dbt `clean` model rebuilds only months that arrived in a newer load, replacing whole months.
- **Why:** re-running costs little, and a month that moves from provisional to final is replaced as a unit, so organisations that disappeared between versions do not linger.

## D4. Stop on a restatement
- **Chosen:** if a file with the same status changes the totals of a month already loaded, the run stops with a message naming the month.
- **Why:** a silent overwrite would hide a change the NHS has published. A person should check the restatement notice first.

## D5. ICB mapping comes from the ODS change summary
- **Chosen:** `reference/icb_mapping_2026.csv` is built from the "Summary" tab of the ODS workbook "ODS Change Summary – ICB Mergers April 2026", rows 56 to 71 (linked from https://digital.nhs.uk/services/organisation-data-service/upcoming-code-changes/icb-mergers-2026-change-summary).
- **Mapping:** 12 retired ICB codes map to 6 new ICBs. Hampshire and Isle of Wight (QRL) keeps its code and is flagged as a boundary change.
- **Check:** the new codes in the April 2026 file match the target codes in the ODS summary (D7T5G, S1Y5D, T6Y0W, Z9B2Z, S0E4D, S9B9J, QRL).

## D6. Frimley is excluded from ICB tables, but kept in national totals
- **Chosen:** Frimley (QNQ) rows are marked `excluded`. They are left out of ICB tables and charts, and kept in the national reconciliation.
- **Why:** the ODS summary says Frimley was split three ways, and it does not give a rule for dividing its history between the receiving ICBs. Splitting it ourselves would invent numbers.
- **Panel note:** this is a stated limitation of the project.

## D7. Commissioning hubs are not ICBs
- **Chosen:** the eight commissioning hubs (for example "LONDON - H&J COMMISSIONING HUB") are kept in the data but left out of ICB tables.
- **Why:** they are not geographic ICBs. Including them would compare them with places they do not cover.

## D8. Headline measures are defined once
- **Chosen:** `is_headline` is set in `clean_cwt`. It means: all cancers, and the "all" row for each standard. For 62-day this is "all routes, all treatments". For 31-day this is "all stages, all treatments". For Faster Diagnosis it is "all routes, no treatment".
- **Why:** each standard uses a different label for its "all" row in the NHS file. Checking this in one place stops each report from guessing.

## D9. Performance is recalculated, never averaged
- **Chosen:** ICB performance = sum of "within" counts divided by sum of totals.
- **Why:** averaging percentages across ICBs or months gives the wrong answer when ICBs differ in size.

## D10. Keep the NHS text values; convert in the clean layer
- **Chosen:** the landing table stores every value as text. Conversion to numbers and dates happens in dbt, with `try_cast`.
- **Why:** a bad value shows up in the clean layer, where it can be inspected, instead of stopping the load.

## D11. Two date styles, one conversion
- **Chosen:** the Period column is ISO (`2024-04-01`) in the 2022-23 to 2024-25 files and day/month/year (`01/04/2025`) in later files. Both are converted in the `period_expr` macro.
- **Why:** reading `01/02/2026` with the wrong order would give January instead of February.

## D12. Limitations accepted for this project
- The 2021-22 data is not included. It has no combined CSV in the same format.
- Pre-April 2026 ICB history is shown under the new ICB names. The Hampshire and Isle of Wight boundary change means its earlier history covers a smaller area. Trends across April 2026 for that ICB are not like-for-like.
- The most recent months are provisional and may be revised.
- 62-day, 31-day and Faster Diagnosis performance are reported as the NHS defines them. Standard thresholds should be checked against NHS England's current release before the panel presentation.
