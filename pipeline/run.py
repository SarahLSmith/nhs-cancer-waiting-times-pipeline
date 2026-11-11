"""Run the whole pipeline: ingest, transform, check, publish the summary.

Order of steps (the run stops at the first failure):

1. Ingest  - download new files, archive them, load them (pipeline/ingest.py)
2. Build   - dbt builds the tidy, linked and report tables (dbt/)
3. Check   - automated quality checks (pipeline/checks.py)
4. Publish - write the summary table and a "data status" file to outputs/

Re-running with no new files changes nothing: unchanged files are skipped and
the incremental dbt build only rebuilds months that arrived in a newer load.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pipeline import checks
from pipeline.config import Settings, load_settings
from pipeline.ingest import RestatementError, ensure_tables, ingest_all

STATE_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_state (
    key   VARCHAR PRIMARY KEY,
    value BIGINT NOT NULL
)
"""

SUMMARY_COLUMNS = (
    "icb_code",
    "icb_name",
    "period_start",
    "standard",
    "total",
    "within_standard",
    "performance",
    "includes_provisional",
)


class PipelineError(RuntimeError):
    """Raised when a step fails and the run must stop."""


def _last_processed_load(con: duckdb.DuckDBPyConnection) -> int:
    """The newest load id that a successful run has already built into dbt."""
    con.execute(STATE_DDL)
    row = con.execute(
        "SELECT value FROM pipeline_state WHERE key = 'last_built_load'"
    ).fetchone()
    return row[0] if row else 0


def _save_last_processed_load(con: duckdb.DuckDBPyConnection, load_id: int) -> None:
    con.execute(STATE_DDL)
    con.execute(
        """
        INSERT INTO pipeline_state VALUES ('last_built_load', ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        [load_id],
    )


def run_dbt(settings: Settings, since_load_id: int, full_refresh: bool = False) -> None:
    """Run ``dbt build`` (seeds, models and dbt tests) against the warehouse.

    The database is closed before this runs, because DuckDB allows one writer
    at a time and dbt needs to write. ``full_refresh`` rebuilds every model from
    scratch; use it after a change to a table's columns.
    """
    env = dict(os.environ, CWT_WAREHOUSE=str(settings.warehouse_path))
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "build",
        "--project-dir",
        str(settings.dbt_project_dir),
        "--profiles-dir",
        str(settings.dbt_project_dir),
        "--vars",
        json.dumps({"since_load_id": since_load_id}),
    ]
    if full_refresh:
        command.append("--full-refresh")
    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        raise PipelineError("dbt build failed (see the messages above)")


def expected_months(settings: Settings) -> list:
    """Every month that the configured sources should cover."""
    first = min(s.first_period for s in settings.sources)
    last = max(s.last_period for s in settings.sources)
    return checks.months_between(first, last)


def publish(settings: Settings, con: duckdb.DuckDBPyConnection) -> Path:
    """Write the summary table and a status file that says how current the data is."""
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)

    rows = con.execute(
        f"SELECT {', '.join(SUMMARY_COLUMNS)} FROM reports_icb_summary "
        "ORDER BY period_start, icb_code, standard"
    ).fetchall()
    summary_path = settings.outputs_dir / "summary_icb_last_6_months.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_COLUMNS)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])

    last_pulled, newest_period, provisional_months = con.execute("""
        SELECT
            (SELECT max(pulled_at) FROM load_log),
            (SELECT max(period_start) FROM reports_icb_monthly),
            (SELECT count(DISTINCT period_start) FROM reports_icb_monthly
             WHERE includes_provisional)
        """).fetchone()
    status = {
        "last_pulled_utc": str(last_pulled),
        "newest_month": str(newest_period),
        "provisional_months": provisional_months,
        "generated_at_utc": datetime.now(UTC)
        .replace(tzinfo=None, microsecond=0)
        .isoformat(),
        "note": "Provisional months can still be revised by NHS England; re-run the pipeline to pick up finals.",
    }
    (settings.outputs_dir / "data_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )
    return summary_path


def main(argv: list[str] | None = None) -> int:
    """Run every step. Returns 0 on success, or a non-zero code that says where it stopped.

    Pass ``--full-refresh`` to rebuild every table from all the loaded files
    (needed after a change to the table definitions).
    """
    args = sys.argv[1:] if argv is None else argv
    full_refresh = "--full-refresh" in args

    settings = load_settings()
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(settings.warehouse_path))
    try:
        ensure_tables(con)
        print("== 1. Ingest")
        results = ingest_all(settings, con)
        for r in results:
            print(
                f"   {r.source_id}: {r.action}"
                + (f" ({r.rows:,} rows)" if r.action == "loaded" else "")
            )

        since = 0 if full_refresh else _last_processed_load(con)
        newest_load = con.execute(
            "SELECT coalesce(max(load_id), 0) FROM load_log"
        ).fetchone()[0]
    except RestatementError as error:
        print(f"STOPPED: {error}")
        return 2
    finally:
        con.close()

    print("== 2. Build (dbt)")
    try:
        run_dbt(settings, since, full_refresh)
    except PipelineError as error:
        print(f"STOPPED: {error}")
        return 3

    print("== 3. Check")
    con = duckdb.connect(str(settings.warehouse_path))
    try:
        results_checks = checks.run_all(con, expected_months(settings))
        failed = [c for c in results_checks if not c.passed]
        for c in results_checks:
            mark = "PASS" if c.passed else "FAIL"
            print(f"   [{mark}] {c.name}: {c.detail}")
        if failed:
            print("STOPPED: quality checks failed; summary not published.")
            return 4

        print("== 4. Publish")
        summary = publish(settings, con)
        _save_last_processed_load(con, newest_load)
        print(f"   summary: {summary}")
        return 0
    finally:
        con.close()
