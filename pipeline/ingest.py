"""Download NHS files, archive them, and load them into the landing table.

What this module guarantees on every run:

* **No duplicates from re-runs.** Each file is fingerprinted with SHA-256. A file
  whose fingerprint is already in ``load_log`` is skipped.
* **Every download is archived** in ``landing/<pull date>/`` with a manifest, so
  any pull can be reproduced later.
* **Restatements stop the run.** If a file with the *same status* (for example
  two Final files) gives different totals for a month that is already loaded,
  we raise :class:`RestatementError` instead of silently overwriting data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import requests

from pipeline.config import Settings, Source
from pipeline.storage import LocalStorage, Storage, sha256_of

USER_AGENT = "Mozilla/5.0 (compatible; nhs-cwt-pipeline learning project)"

# NHS files use two date styles for the Period column:
#   2022-23 to 2024-25 files:  2022-04-01        (ISO)
#   2025-26 and later files:   01/04/2025        (day/month/year)
# Every value is the first of the month, so we only need to get the order right.
PERIOD_SQL = (
    "CASE WHEN Period LIKE '%/%' "
    "THEN strptime(Period, '%d/%m/%Y')::DATE "
    "ELSE strptime(Period, '%Y-%m-%d')::DATE END"
)

LOAD_LOG_DDL = """
CREATE TABLE IF NOT EXISTS load_log (
    load_id      BIGINT PRIMARY KEY,
    source_id    VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,
    sha256       VARCHAR NOT NULL UNIQUE,
    pulled_at    TIMESTAMP NOT NULL,
    source_url   VARCHAR NOT NULL,
    rows_loaded  BIGINT NOT NULL
)
"""


class RestatementError(RuntimeError):
    """Raised when an already-loaded month has changed without a status change."""


@dataclass(frozen=True)
class LoadResult:
    """What happened to one source during an ingest run."""

    source_id: str
    action: str  # "loaded" or "skipped"
    load_id: int | None
    rows: int


def download(url: str, timeout_seconds: int = 300) -> bytes:
    """Fetch a file over HTTPS and return its bytes. Raises on HTTP errors."""
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=timeout_seconds
    )
    response.raise_for_status()
    return response.content


def _duckdb_path(path: Path) -> str:
    """DuckDB accepts forward slashes on Windows; backslashes can be misread."""
    return str(path).replace("\\", "/")


def ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create the load log table if it does not exist yet."""
    con.execute(LOAD_LOG_DDL)


def _next_load_id(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT coalesce(max(load_id), 0) + 1 FROM load_log").fetchone()[
        0
    ]


def _check_for_restatement(
    con: duckdb.DuckDBPyConnection, status: str, new_sha: str
) -> None:
    """Stop if the new file changes a month already loaded with the same status.

    We compare a simple fingerprint per month (row count and sum of ``Total``).
    Identical months are fine (a cumulative file repeats old months unchanged).
    A different fingerprint for a month already loaded with the same status is
    a restatement, and needs a person to look at it before we continue.
    """
    rows = con.execute(
        f"""
        WITH incoming AS (
            SELECT {PERIOD_SQL} AS period, try_cast(Total AS DOUBLE) AS total
            FROM incoming_file
        ),
        new_fp AS (
            SELECT period, count(*) AS n, sum(total) AS s FROM incoming GROUP BY period
        ),
        old AS (
            SELECT {PERIOD_SQL} AS period, try_cast(Total AS DOUBLE) AS total, source_sha256
            FROM landing_cwt
            WHERE status = ? AND source_sha256 <> ?
        ),
        old_fp AS (
            SELECT period, source_sha256, count(*) AS n, sum(total) AS s
            FROM old GROUP BY period, source_sha256
        )
        SELECT strftime(new_fp.period, '%Y-%m') AS month
        FROM new_fp JOIN old_fp USING (period)
        WHERE new_fp.n <> old_fp.n OR new_fp.s <> old_fp.s
        GROUP BY month
        ORDER BY month
        """,
        [status, new_sha],
    ).fetchall()
    if rows:
        months = ", ".join(r[0] for r in rows)
        raise RestatementError(
            f"Months already loaded as '{status}' have changed: {months}. "
            "Check the NHS restatement notice before loading."
        )


def ingest_source(
    con: duckdb.DuckDBPyConnection,
    source: Source,
    storage: Storage,
    pulled_at: datetime,
    manifest: list[dict[str, object]],
) -> LoadResult:
    """Download one source, archive it, and load it unless already loaded."""
    data = download(source.url)
    sha = sha256_of(data)

    already = con.execute(
        "SELECT load_id FROM load_log WHERE sha256 = ?", [sha]
    ).fetchone()
    if already:
        return LoadResult(source.id, "skipped", None, 0)

    key = f"{pulled_at:%Y-%m-%d}/{source.id}.csv"
    stored_path = Path(storage.write_bytes(key, data))
    load_id = _next_load_id(con)

    ensure_landing_table(con, stored_path)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE incoming_file AS "
        "SELECT * FROM read_csv(?, all_varchar=true, header=true)",
        [_duckdb_path(stored_path)],
    )
    _check_for_restatement(con, source.status, sha)

    con.execute(
        """
        INSERT INTO landing_cwt BY NAME
        SELECT *, ? AS source_id, ? AS status, ? AS source_sha256,
               ? AS load_id, ? AS pulled_at
        FROM incoming_file
        """,
        [source.id, source.status, sha, load_id, pulled_at],
    )
    rows = con.execute("SELECT count(*) FROM incoming_file").fetchone()[0]
    con.execute(
        "INSERT INTO load_log VALUES (?, ?, ?, ?, ?, ?, ?)",
        [load_id, source.id, source.status, sha, pulled_at, source.url, rows],
    )
    manifest.append(
        {
            "source_id": source.id,
            "url": source.url,
            "status": source.status,
            "sha256": sha,
            "bytes": len(data),
            "rows": rows,
            "stored_at": str(stored_path),
        }
    )
    return LoadResult(source.id, "loaded", load_id, rows)


def ensure_landing_table(con: duckdb.DuckDBPyConnection, sample_csv: Path) -> None:
    """Create ``landing_cwt`` with the NHS columns (all text) plus our metadata.

    Text is kept on purpose: the clean layer (dbt) does all type conversion, so
    bad values are visible there rather than failing the load.
    """
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS landing_cwt AS
        SELECT *, NULL::VARCHAR AS source_id, NULL::VARCHAR AS status,
               NULL::VARCHAR AS source_sha256, NULL::BIGINT AS load_id,
               NULL::TIMESTAMP AS pulled_at
        FROM read_csv('{_duckdb_path(sample_csv)}', all_varchar=true, header=true)
        LIMIT 0
        """)


def ingest_all(settings: Settings, con: duckdb.DuckDBPyConnection) -> list[LoadResult]:
    """Ingest every source in ``sources.yml``. Returns one result per source."""
    pulled_at = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    storage = LocalStorage(settings.landing_dir)
    ensure_tables(con)

    results: list[LoadResult] = []
    manifest: list[dict[str, object]] = []
    for source in settings.sources:
        results.append(ingest_source(con, source, storage, pulled_at, manifest))

    if manifest:
        # The manifest records exactly what was downloaded in this pull.
        manifest_key = f"{pulled_at:%Y-%m-%d}/manifest.json"
        storage.write_bytes(
            manifest_key,
            json.dumps(
                {"pulled_at": str(pulled_at), "files": manifest}, indent=2
            ).encode(),
        )
    return results
