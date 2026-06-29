"""Load schedule-report CSV files into a validated DuckDB analytical model."""

from __future__ import annotations

import csv
import hashlib
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

import duckdb

ReportType = Literal["coverage", "market"]

_CARRIER_HEADER = (
    "Travel Month",
    "Airline Code",
    "Origin Code",
    "Destination Code",
    "Seats",
)
_MARKET_HEADER = (
    "Travel Month",
    "Origin Code",
    "Destination Code",
    "Seats",
)
_CARRIER_CODE = re.compile(r"^[A-Z0-9]{2}$")
_AIRPORT_CODE = re.compile(r"^[A-Z0-9]{3}$")


class ValidationError(ValueError):
    """Raised when a report cannot be safely used in the analytical model."""


@dataclass(frozen=True)
class CarrierCapacityRecord:
    travel_month: date
    carrier_code: str
    origin_code: str
    destination_code: str
    seats: int


@dataclass(frozen=True)
class MarketCapacityRecord:
    travel_month: date
    origin_code: str
    destination_code: str
    seats: int


@dataclass(frozen=True)
class ParsedReport:
    report_type: ReportType
    source_file: Path
    records: tuple[CarrierCapacityRecord | MarketCapacityRecord, ...]
    data_header_line: int
    first_month: date
    last_month: date


@dataclass(frozen=True)
class ImportSummary:
    database_path: Path
    source_batch_id: str
    carrier_record_count: int
    market_record_count: int
    carrier_count: int
    first_month: date
    last_month: date


def _normalized_cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _find_header(reader: Iterable[list[str]], expected: tuple[str, ...]) -> int:
    matches: list[int] = []
    for line_number, row in enumerate(reader, start=1):
        if tuple(row[: len(expected)]) == expected:
            matches.append(line_number)

    if len(matches) != 1:
        raise ValidationError(
            f"Expected exactly one {expected!r} header; found {len(matches)}."
        )
    return matches[0]


def _parse_month(value: str, report_type: ReportType, line_number: int) -> date:
    format_string = "%b-%y" if report_type == "coverage" else "%b %Y"
    try:
        return datetime.strptime(value, format_string).date().replace(day=1)
    except ValueError as error:
        raise ValidationError(
            f"Line {line_number}: invalid travel month {value!r}."
        ) from error


def _parse_code(
    value: str, pattern: re.Pattern[str], label: str, line_number: int
) -> str:
    code = value.upper()
    if not pattern.fullmatch(code):
        raise ValidationError(f"Line {line_number}: invalid {label} {value!r}.")
    return code


def _parse_seats(value: str, line_number: int) -> int:
    normalized = value.replace(",", "")
    try:
        seats = int(normalized)
    except ValueError as error:
        raise ValidationError(f"Line {line_number}: invalid seats {value!r}.") from error
    if seats < 0:
        raise ValidationError(f"Line {line_number}: seats cannot be negative.")
    return seats


def parse_report(path: Path, report_type: ReportType) -> ParsedReport:
    """Parse only the tabular section of a Dynamic Table report."""

    expected_header = _CARRIER_HEADER if report_type == "coverage" else _MARKET_HEADER
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.reader(source))

    header_line = _find_header(iter(rows), expected_header)
    records: list[CarrierCapacityRecord | MarketCapacityRecord] = []
    seen_keys: set[tuple[object, ...]] = set()
    data_started = False

    for line_number, row in enumerate(rows[header_line:], start=header_line + 1):
        values = tuple(_normalized_cell(row, index) for index in range(len(expected_header)))

        if not any(values):
            if data_started:
                break
            continue

        data_started = True
        if report_type == "coverage":
            month, carrier, origin, destination, seat_value = values
            record = CarrierCapacityRecord(
                travel_month=_parse_month(month, report_type, line_number),
                carrier_code=_parse_code(
                    carrier, _CARRIER_CODE, "carrier code", line_number
                ),
                origin_code=_parse_code(
                    origin, _AIRPORT_CODE, "origin code", line_number
                ),
                destination_code=_parse_code(
                    destination, _AIRPORT_CODE, "destination code", line_number
                ),
                seats=_parse_seats(seat_value, line_number),
            )
            key = (
                record.travel_month,
                record.carrier_code,
                record.origin_code,
                record.destination_code,
            )
        else:
            month, origin, destination, seat_value = values
            record = MarketCapacityRecord(
                travel_month=_parse_month(month, report_type, line_number),
                origin_code=_parse_code(
                    origin, _AIRPORT_CODE, "origin code", line_number
                ),
                destination_code=_parse_code(
                    destination, _AIRPORT_CODE, "destination code", line_number
                ),
                seats=_parse_seats(seat_value, line_number),
            )
            key = (record.travel_month, record.origin_code, record.destination_code)

        if key in seen_keys:
            raise ValidationError(f"Line {line_number}: duplicate natural key {key}.")
        seen_keys.add(key)
        records.append(record)

    if not records:
        raise ValidationError(f"No records found after the header in {path}.")

    months = [record.travel_month for record in records]
    return ParsedReport(
        report_type=report_type,
        source_file=path,
        records=tuple(records),
        data_header_line=header_line,
        first_month=min(months),
        last_month=max(months),
    )


def _validate_cross_report(
    coverage: ParsedReport, market: ParsedReport
) -> None:
    if coverage.first_month != market.first_month or coverage.last_month != market.last_month:
        raise ValidationError(
            "Coverage and market reports do not have the same travel-month range."
        )

    market_records = market.records
    coverage_records = coverage.records
    market_by_key = {
        (record.travel_month, record.origin_code, record.destination_code): record.seats
        for record in market_records
        if isinstance(record, MarketCapacityRecord)
    }
    coverage_by_market_key: defaultdict[tuple[date, str, str], int] = defaultdict(int)

    for record in coverage_records:
        if not isinstance(record, CarrierCapacityRecord):
            continue
        market_key = (
            record.travel_month,
            record.origin_code,
            record.destination_code,
        )
        if market_key not in market_by_key:
            raise ValidationError(
                "Coverage record has no market match: "
                f"{record.travel_month} {record.origin_code}->{record.destination_code}."
            )
        coverage_by_market_key[market_key] += record.seats

    exceeding_keys = [
        (key, carrier_seats, market_by_key[key])
        for key, carrier_seats in coverage_by_market_key.items()
        if carrier_seats > market_by_key[key]
    ]
    if exceeding_keys:
        key, carrier_seats, market_seats = exceeding_keys[0]
        raise ValidationError(
            "Combined carrier seats exceed market seats for "
            f"{key[0]} {key[1]}->{key[2]}: {carrier_seats} > {market_seats}."
        )


def _source_batch_id(coverage_path: Path, market_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (coverage_path, market_path):
        digest.update(path.name.encode())
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1_048_576), b""):
                digest.update(chunk)
    return f"batch_{digest.hexdigest()[:16]}"


def _create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE import_batch (
          source_batch_id VARCHAR NOT NULL,
          source_file VARCHAR NOT NULL,
          report_type VARCHAR NOT NULL,
          imported_at TIMESTAMP NOT NULL,
          row_count BIGINT NOT NULL,
          travel_month_start DATE NOT NULL,
          travel_month_end DATE NOT NULL,
          validation_status VARCHAR NOT NULL,
          PRIMARY KEY (source_batch_id, report_type)
        );

        CREATE TABLE carrier_capacity (
          travel_month DATE NOT NULL,
          carrier_code VARCHAR NOT NULL,
          origin_code VARCHAR NOT NULL,
          destination_code VARCHAR NOT NULL,
          seats BIGINT NOT NULL CHECK (seats >= 0),
          source_batch_id VARCHAR NOT NULL,
          UNIQUE (travel_month, carrier_code, origin_code, destination_code, source_batch_id)
        );

        CREATE TABLE market_capacity (
          travel_month DATE NOT NULL,
          origin_code VARCHAR NOT NULL,
          destination_code VARCHAR NOT NULL,
          seats BIGINT NOT NULL CHECK (seats >= 0),
          source_batch_id VARCHAR NOT NULL,
          UNIQUE (travel_month, origin_code, destination_code, source_batch_id)
        );
        """
    )


def _write_normalized_csv(
    path: Path,
    records: Iterable[CarrierCapacityRecord | MarketCapacityRecord],
    report_type: ReportType,
    source_batch_id: str,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        if report_type == "coverage":
            writer.writerow(
                [
                    "travel_month",
                    "carrier_code",
                    "origin_code",
                    "destination_code",
                    "seats",
                    "source_batch_id",
                ]
            )
            for record in records:
                if isinstance(record, CarrierCapacityRecord):
                    writer.writerow(
                        [
                            record.travel_month.isoformat(),
                            record.carrier_code,
                            record.origin_code,
                            record.destination_code,
                            record.seats,
                            source_batch_id,
                        ]
                    )
        else:
            writer.writerow(
                [
                    "travel_month",
                    "origin_code",
                    "destination_code",
                    "seats",
                    "source_batch_id",
                ]
            )
            for record in records:
                if isinstance(record, MarketCapacityRecord):
                    writer.writerow(
                        [
                            record.travel_month.isoformat(),
                            record.origin_code,
                            record.destination_code,
                            record.seats,
                            source_batch_id,
                        ]
                    )


def _copy_csv(
    connection: duckdb.DuckDBPyConnection, table_name: str, source_path: Path
) -> None:
    escaped_path = str(source_path).replace("'", "''")
    connection.execute(f"COPY {table_name} FROM '{escaped_path}' (HEADER TRUE)")


def build_warehouse(
    coverage_path: Path, market_path: Path, database_path: Path
) -> ImportSummary:
    """Validate both reports, then atomically replace the DuckDB warehouse."""

    coverage = parse_report(coverage_path, "coverage")
    market = parse_report(market_path, "market")
    _validate_cross_report(coverage, market)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = database_path.with_name(f".{database_path.name}.tmp")
    temporary_wal_path = Path(f"{temporary_path}.wal")
    for artifact_path in (temporary_path, temporary_wal_path):
        if artifact_path.exists():
            artifact_path.unlink()

    source_batch_id = _source_batch_id(coverage_path, market_path)
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)

    with tempfile.TemporaryDirectory(
        dir=database_path.parent, prefix=".capacity-import-"
    ) as import_directory:
        normalized_coverage = Path(import_directory) / "coverage.csv"
        normalized_market = Path(import_directory) / "market.csv"
        _write_normalized_csv(
            normalized_coverage, coverage.records, "coverage", source_batch_id
        )
        _write_normalized_csv(
            normalized_market, market.records, "market", source_batch_id
        )

        connection = duckdb.connect(str(temporary_path))
        try:
            _create_schema(connection)
            _copy_csv(connection, "carrier_capacity", normalized_coverage)
            _copy_csv(connection, "market_capacity", normalized_market)
            connection.executemany(
                """
                INSERT INTO import_batch VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source_batch_id,
                        str(report.source_file),
                        report.report_type,
                        imported_at,
                        len(report.records),
                        report.first_month,
                        report.last_month,
                        "passed",
                    )
                    for report in (coverage, market)
                ],
            )
        finally:
            connection.close()

    target_wal_path = Path(f"{database_path}.wal")
    if target_wal_path.exists():
        target_wal_path.unlink()
    temporary_path.replace(database_path)

    carrier_count = len(
        {
            record.carrier_code
            for record in coverage.records
            if isinstance(record, CarrierCapacityRecord)
        }
    )
    return ImportSummary(
        database_path=database_path,
        source_batch_id=source_batch_id,
        carrier_record_count=len(coverage.records),
        market_record_count=len(market.records),
        carrier_count=carrier_count,
        first_month=coverage.first_month,
        last_month=coverage.last_month,
    )
