"""Read the pipeline settings from ``config/sources.yml``.

Nothing about file locations or source links is hard-coded elsewhere in the
package: change the YAML file, not the code, when NHS publishes a new file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

# The project root is the folder that contains ``pipeline/``, ``config/`` and ``dbt/``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources.yml"

VALID_STATUSES = ("final", "provisional")


@dataclass(frozen=True)
class Source:
    """One NHS England file we are allowed to load."""

    id: str
    label: str
    url: str
    status: str  # "final" or "provisional"
    first_period: date
    last_period: date


@dataclass(frozen=True)
class Settings:
    """All settings the pipeline needs, with paths resolved to absolute locations."""

    sources: tuple[Source, ...]
    icb_mapping_path: Path
    landing_dir: Path
    warehouse_path: Path
    outputs_dir: Path
    dbt_project_dir: Path


def load_settings(config_path: Path = DEFAULT_CONFIG) -> Settings:
    """Parse ``sources.yml`` into a :class:`Settings` object.

    Raises ``ValueError`` if a source has an unknown status, so a typo in the
    YAML fails loudly instead of being loaded as the wrong kind of data.
    """
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    sources = []
    for entry in raw["sources"]:
        if entry["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Source {entry['id']!r} has status {entry['status']!r}; "
                f"expected one of {VALID_STATUSES}"
            )
        sources.append(
            Source(
                id=entry["id"],
                label=entry["label"],
                url=entry["url"],
                status=entry["status"],
                first_period=date.fromisoformat(str(entry["first_period"])),
                last_period=date.fromisoformat(str(entry["last_period"])),
            )
        )

    storage = raw["storage"]
    return Settings(
        sources=tuple(sources),
        icb_mapping_path=PROJECT_ROOT / raw["reference"]["icb_mapping"],
        landing_dir=PROJECT_ROOT / storage["landing_dir"],
        warehouse_path=PROJECT_ROOT / storage["warehouse"],
        outputs_dir=PROJECT_ROOT / storage["outputs_dir"],
        dbt_project_dir=PROJECT_ROOT / storage["dbt_project_dir"],
    )
