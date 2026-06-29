from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from capacity_tool.ingestion import ValidationError, build_warehouse, parse_report
from capacity_tool.queries import get_route_capacity


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_report_reads_only_tabular_section() -> None:
    report = parse_report(FIXTURES / "coverage.csv", "coverage")

    assert report.data_header_line == 6
    assert len(report.records) == 2
    assert report.first_month.isoformat() == "2026-07-01"
    assert report.records[0].carrier_code == "DL"
    assert report.records[0].seats == 8080


def test_build_warehouse_and_query_route(tmp_path: Path) -> None:
    database_path = tmp_path / "capacity.duckdb"

    summary = build_warehouse(
        FIXTURES / "coverage.csv",
        FIXTURES / "market.csv",
        database_path,
    )

    assert summary.carrier_record_count == 2
    assert summary.market_record_count == 2
    assert summary.carrier_count == 2
    assert build_warehouse(
        FIXTURES / "coverage.csv",
        FIXTURES / "market.csv",
        database_path,
    ).source_batch_id == summary.source_batch_id

    with duckdb.connect(str(database_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM import_batch").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM carrier_capacity").fetchone() == (2,)

    route = get_route_capacity(database_path, "DL", "LGA", "RSW", "2026-07")
    assert route is not None
    assert route.carrier_seats == 8080
    assert route.market_seats == 10000
    assert route.other_airline_seats == 1920


def test_build_warehouse_rejects_missing_market_route(tmp_path: Path) -> None:
    market_path = tmp_path / "market.csv"
    market_path.write_text(
        "\n".join(
            line
            for line in (FIXTURES / "market.csv").read_text().splitlines()
            if "JFK,MIA" not in line
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="has no market match"):
        build_warehouse(FIXTURES / "coverage.csv", market_path, tmp_path / "out.duckdb")


def test_parse_report_rejects_duplicate_natural_key(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.csv"
    coverage_path.write_text(
        (FIXTURES / "coverage.csv")
        .read_text()
        .replace(
            'Jul-26,DL,LGA,RSW,"8,080",,',
            'Jul-26,DL,LGA,RSW,"8,080",,\nJul-26,DL,LGA,RSW,"8,080",,',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate natural key"):
        parse_report(coverage_path, "coverage")
