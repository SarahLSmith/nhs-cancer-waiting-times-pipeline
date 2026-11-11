"""Automated quality checks.

Each check is a small function that takes a DuckDB connection and returns a
:class:`CheckResult` saying whether it passed and why. The run stops if any
check fails, so a bad load never reaches the summary table.

Checks run against the tables built by dbt:

* ``clean_cwt``      - one tidy row per period, organisation and measure
* ``linked_cwt``     - ``clean_cwt`` with the April 2026 ICB mapping applied
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

# The key that must be unique in clean_cwt (one row per period and measure).
KEY_COLUMNS = (
    "period_start",
    "basis",
    "org_code",
    "standard",
    "cancer_type",
    "referral_route",
    "treatment_modality",
)

REQUIRED_CLEAN_COLUMNS = KEY_COLUMNS + (
    "org_name",
    "total",
    "within",
    "after",
    "performance",
    "is_headline",
)

# The measure the reconciliation checks use: the 62-day standard, all cancers.
# (The definition of "headline" lives in dbt/models/clean/clean_cwt.sql.)
HEADLINE_FILTER = "is_headline AND standard = '62D'"

# Tolerance for float sums (dbt casts counts to DOUBLE; NHS counts can be x.5).
TOLERANCE = 0.5


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check, with a plain-English reason."""

    name: str
    passed: bool
    detail: str


def months_between(first: date, last: date) -> list[date]:
    """Return the first day of every month from ``first`` to ``last`` inclusive."""
    months = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(date(year, month, 1))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def check_schema(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """The clean table has every column the reports depend on."""
    present = {r[0] for r in con.execute("DESCRIBE clean_cwt").fetchall()}
    missing = sorted(set(REQUIRED_CLEAN_COLUMNS) - present)
    if missing:
        return CheckResult("schema", False, f"missing columns: {', '.join(missing)}")
    return CheckResult(
        "schema", True, f"all {len(REQUIRED_CLEAN_COLUMNS)} required columns present"
    )


def check_no_duplicate_keys(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """No two rows share the same period, organisation and measure."""
    cols = ", ".join(KEY_COLUMNS)
    dupes = con.execute(
        f"SELECT count(*) FROM (SELECT {cols} FROM clean_cwt GROUP BY {cols} HAVING count(*) > 1)"
    ).fetchone()[0]
    if dupes:
        return CheckResult("no duplicate keys", False, f"{dupes} duplicated keys found")
    return CheckResult(
        "no duplicate keys", True, "every period, organisation and measure appears once"
    )


def check_months_complete(
    con: duckdb.DuckDBPyConnection, expected: list[date]
) -> CheckResult:
    """Every expected month has data for the headline measure."""
    present = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT period_start FROM clean_cwt WHERE {HEADLINE_FILTER}"
        ).fetchall()
    }
    missing = [m for m in expected if m not in present]
    if missing:
        names = ", ".join(m.strftime("%b %Y") for m in missing)
        return CheckResult("all months present", False, f"no data for: {names}")
    return CheckResult(
        "all months present",
        True,
        f"{len(expected)} months from {expected[0]:%b %Y} to {expected[-1]:%b %Y}",
    )


def check_plausible_values(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """Counts are never negative, Within never exceeds Total, performance is 0 to 1."""
    bad = con.execute("""
        SELECT count(*) FROM clean_cwt
        WHERE total < 0
           OR within > total + 0.000001
           OR (performance IS NOT NULL AND (performance < 0 OR performance > 1.000001))
        """).fetchone()[0]
    if bad:
        return CheckResult(
            "plausible values", False, f"{bad} rows have impossible counts or rates"
        )
    return CheckResult(
        "plausible values", True, "no negative counts; rates between 0 and 1"
    )


def check_national_reconciles(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """For each month: the national total equals the sum of all commissioner rows.

    The national total comes from the provider file's ``Total`` row. The
    commissioner rows are the same measure split by commissioner (including the
    commissioning hubs and UNKNOWN), so the two must agree.
    """
    rows = con.execute(f"""
        WITH national AS (
            SELECT period_start, sum(total) AS national_total FROM clean_cwt
            WHERE basis = 'PROVIDER' AND org_code = 'Total' AND {HEADLINE_FILTER}
            GROUP BY period_start
        ),
        commissioners AS (
            SELECT period_start, sum(total) AS commissioner_total FROM clean_cwt
            WHERE basis = 'COMMISSIONER' AND {HEADLINE_FILTER}
            GROUP BY period_start
        )
        SELECT strftime(n.period_start, '%Y-%m') AS month, n.national_total, c.commissioner_total
        FROM national n LEFT JOIN commissioners c USING (period_start)
        WHERE c.commissioner_total IS NULL
           OR abs(n.national_total - c.commissioner_total) > {TOLERANCE}
        ORDER BY month
        """).fetchall()
    if rows:
        return CheckResult(
            "national totals reconcile",
            False,
            "mismatch in: " + ", ".join(r[0] for r in rows),
        )
    return CheckResult(
        "national totals reconcile",
        True,
        "provider total equals sum of commissioners, every month",
    )


def check_icb_reconciles(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """For each month: ICB report rows + hubs + excluded Frimley = commissioner total.

    This proves the April 2026 mapping and the report filters lose no patients:
    every commissioner row is either in the ICB report or in a group we name
    and leave out on purpose (commissioning hubs, excluded Frimley).
    """
    rows = con.execute(f"""
        WITH commissioners AS (
            SELECT period_start, sum(total) AS total FROM linked_cwt
            WHERE basis = 'COMMISSIONER' AND {HEADLINE_FILTER}
            GROUP BY period_start
        ),
        reported AS (
            SELECT period_start, sum(total) AS total FROM reports_icb_monthly
            WHERE standard = '62D'
            GROUP BY period_start
        ),
        left_out AS (
            SELECT period_start, sum(total) AS total FROM linked_cwt
            WHERE basis = 'COMMISSIONER' AND {HEADLINE_FILTER}
              AND org_group IN ('Excluded (Frimley)', 'Commissioning hub')
            GROUP BY period_start
        )
        SELECT strftime(c.period_start, '%Y-%m') AS month
        FROM commissioners c
        LEFT JOIN reported r USING (period_start)
        LEFT JOIN left_out o USING (period_start)
        WHERE abs(c.total - (coalesce(r.total, 0) + coalesce(o.total, 0))) > {TOLERANCE}
        ORDER BY month
        """).fetchall()
    if rows:
        return CheckResult(
            "ICB totals reconcile",
            False,
            "mismatch in: " + ", ".join(r[0] for r in rows),
        )
    return CheckResult(
        "ICB totals reconcile",
        True,
        "ICB report + commissioning hubs + excluded Frimley equal the commissioner total",
    )


def run_all(
    con: duckdb.DuckDBPyConnection, expected_months: list[date]
) -> list[CheckResult]:
    """Run every check and return all results (the caller decides what to do)."""
    return [
        check_schema(con),
        check_no_duplicate_keys(con),
        check_months_complete(con, expected_months),
        check_plausible_values(con),
        check_national_reconciles(con),
        check_icb_reconciles(con),
    ]
