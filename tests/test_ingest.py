"""Tests for the ingest step: date parsing, fingerprints and the restatement guard."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from pipeline.ingest import PERIOD_SQL, RestatementError, _check_for_restatement
from pipeline.storage import sha256_of


def _tables(con: duckdb.DuckDBPyConnection, old_rows: list[tuple]) -> None:
    """landing_cwt holds previously loaded rows: (Period, Total, status, source_sha256)."""
    con.execute(
        'CREATE TABLE landing_cwt ("Period" VARCHAR, "Total" VARCHAR, '
        "status VARCHAR, source_sha256 VARCHAR)"
    )
    con.executemany("INSERT INTO landing_cwt VALUES (?, ?, ?, ?)", old_rows)


def _incoming(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """incoming_file is the file being loaded now: (Period, Total)."""
    con.execute('CREATE TEMP TABLE incoming_file ("Period" VARCHAR, "Total" VARCHAR)')
    con.executemany("INSERT INTO incoming_file VALUES (?, ?)", rows)


@pytest.mark.parametrize("text", ["2024-04-01", "01/04/2024"])
def test_both_nhs_period_styles_give_the_same_month(text):
    literal = f"'{text}'"
    expression = PERIOD_SQL.replace("Period", literal)
    value = duckdb.connect().execute(f"SELECT {expression}").fetchone()[0]
    assert value == date(2024, 4, 1)


def test_identical_months_from_a_later_file_are_allowed():
    con = duckdb.connect()
    _tables(con, [("2026-04-01", "100", "provisional", "old-sha")])
    _incoming(con, [("2026-04-01", "100")])
    _check_for_restatement(con, "provisional", "new-sha")  # no exception


def test_changed_month_with_same_status_stops_the_run():
    con = duckdb.connect()
    _tables(con, [("2026-04-01", "100", "provisional", "old-sha")])
    _incoming(con, [("2026-04-01", "105")])
    with pytest.raises(RestatementError, match="2026-04"):
        _check_for_restatement(con, "provisional", "new-sha")


def test_provisional_becoming_final_is_not_a_restatement():
    con = duckdb.connect()
    _tables(con, [("2026-04-01", "100", "provisional", "old-sha")])
    _incoming(con, [("2026-04-01", "103")])
    _check_for_restatement(con, "final", "new-sha")  # different status: expected change


def test_fingerprint_changes_when_a_byte_changes():
    assert sha256_of(b"abc") != sha256_of(b"abd")
    assert sha256_of(b"abc") == sha256_of(b"abc")
