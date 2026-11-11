"""Tests for the quality checks.

Each check gets a case that should pass and a case that should fail, using
small tables built in memory. No NHS download is needed to run these tests.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from pipeline import checks

CLEAN_COLUMNS = (
    "period_start, basis, org_code, org_name, parent_org, standard, cancer_type, "
    "referral_route, treatment_modality, total, within, after, performance, is_headline"
)


def clean_row(
    period: date = date(2026, 5, 1),
    basis: str = "COMMISSIONER",
    org_code: str = "QJM",
    standard: str = "62D",
    total: float = 100.0,
    within: float = 70.0,
) -> tuple:
    """One row of clean_cwt, as a tuple in CLEAN_COLUMNS order."""
    performance = within / total if total else None
    return (
        period,
        basis,
        org_code,
        f"ORG {org_code}",
        "ENGLAND",
        standard,
        "ALL CANCERS",
        "ALL ROUTES",
        "ALL MODALITIES",
        total,
        within,
        total - within,
        performance,
        True,
    )


def build(
    con: duckdb.DuckDBPyConnection, rows: list[tuple], reports: list[tuple] = ()
) -> None:
    """Create clean_cwt, linked_cwt and reports_icb_monthly holding the given rows.

    linked_cwt is the same rows with the ICB columns added (every commissioner
    is an ordinary ICB here; the mapping is tested separately with real data).
    """
    con.execute("""
        CREATE TABLE clean_cwt (
            period_start DATE, basis VARCHAR, org_code VARCHAR, org_name VARCHAR,
            parent_org VARCHAR, standard VARCHAR, cancer_type VARCHAR,
            referral_route VARCHAR, treatment_modality VARCHAR, total DOUBLE,
            within DOUBLE, after DOUBLE, performance DOUBLE, is_headline BOOLEAN
        )
        """)
    con.executemany(
        f"INSERT INTO clean_cwt ({CLEAN_COLUMNS}) VALUES ({', '.join(['?'] * 14)})",
        rows,
    )
    con.execute("""
        CREATE TABLE linked_cwt AS
        SELECT *, 'ICB' AS org_group, NULL::VARCHAR AS mapping_treatment FROM clean_cwt
        """)
    con.execute("""
        CREATE TABLE reports_icb_monthly (
            period_start DATE, icb_code VARCHAR, standard VARCHAR,
            total DOUBLE, within_standard DOUBLE
        )
        """)
    if reports:  # executemany needs at least one row
        con.executemany(
            "INSERT INTO reports_icb_monthly VALUES (?, ?, ?, ?, ?)", list(reports)
        )


def test_months_between_is_inclusive_and_crosses_years():
    months = checks.months_between(date(2025, 11, 1), date(2026, 2, 1))
    assert months == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


def test_no_duplicate_keys_passes_then_fails():
    con = duckdb.connect()
    build(con, [clean_row(org_code="QJM"), clean_row(org_code="QJK")])
    assert checks.check_no_duplicate_keys(con).passed

    con = duckdb.connect()
    build(con, [clean_row(org_code="QJM"), clean_row(org_code="QJM")])
    assert not checks.check_no_duplicate_keys(con).passed


def test_plausible_values_catches_within_greater_than_total():
    con = duckdb.connect()
    build(con, [clean_row(total=100, within=70)])
    assert checks.check_plausible_values(con).passed

    con = duckdb.connect()
    build(con, [clean_row(total=100, within=150)])
    assert not checks.check_plausible_values(con).passed


def test_months_complete_names_the_missing_month():
    con = duckdb.connect()
    build(con, [clean_row(period=date(2026, 5, 1)), clean_row(period=date(2026, 6, 1))])
    result = checks.check_months_complete(
        con, [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]
    )
    assert not result.passed
    assert "Jul 2026" in result.detail


def test_national_total_must_equal_sum_of_commissioners():
    national = clean_row(basis="PROVIDER", org_code="Total", total=100, within=70)

    con = duckdb.connect()
    build(con, [national, clean_row(org_code="QJM", total=100, within=70)])
    assert checks.check_national_reconciles(con).passed

    con = duckdb.connect()
    build(con, [national, clean_row(org_code="QJM", total=60, within=30)])
    assert not checks.check_national_reconciles(con).passed


@pytest.mark.parametrize(
    "reported_total, expected_pass", [(100.0, True), (40.0, False)]
)
def test_icb_report_plus_left_out_rows_equal_commissioner_total(
    reported_total, expected_pass
):
    con = duckdb.connect()
    build(
        con,
        [clean_row(org_code="QJM", total=100, within=70)],
        reports=[(date(2026, 5, 1), "QJM", "62D", reported_total, 70.0)],
    )
    assert checks.check_icb_reconciles(con).passed is expected_pass
