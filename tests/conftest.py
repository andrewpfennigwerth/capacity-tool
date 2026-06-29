from __future__ import annotations

from pathlib import Path

import pytest

from capacity_tool.ingestion import build_warehouse


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def same_store_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "capacity.duckdb"
    build_warehouse(
        FIXTURES / "same_store_coverage.csv",
        FIXTURES / "same_store_market.csv",
        database_path,
    )
    return database_path
