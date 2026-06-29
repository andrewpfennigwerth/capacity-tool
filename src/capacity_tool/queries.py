"""Small, explicit analytical queries used to validate the warehouse."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

import duckdb

PeriodGranularity = Literal["month", "quarter"]
RouteSort = Literal["oa_change", "carrier_change"]
_CARRIER_CODE = re.compile(r"^[A-Z0-9]{2}$")
_SAME_STORE_ROUTES_SQL = (
    files("capacity_tool.sql")
    .joinpath("same_store_routes.sql")
    .read_text(encoding="utf-8")
    .strip()
    .removesuffix(";")
)


@dataclass(frozen=True)
class RouteCapacity:
    travel_month: str
    carrier_code: str
    origin_code: str
    destination_code: str
    carrier_seats: int
    market_seats: int
    other_airline_seats: int


@dataclass(frozen=True)
class AnalysisPeriod:
    label: str
    comparison_label: str
    granularity: PeriodGranularity
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date


@dataclass(frozen=True)
class SameStoreRouteCapacity:
    origin_code: str
    destination_code: str
    carrier_seats_current: int
    carrier_seats_prior: int
    carrier_seat_change: int
    carrier_seat_change_pct: float | None
    market_seats_current: int
    market_seats_prior: int
    oa_seats_current: int
    oa_seats_prior: int
    oa_seat_change: int
    oa_seat_change_pct: float | None


@dataclass(frozen=True)
class SameStoreSummary:
    carrier_code: str
    period: str
    comparison_period: str
    same_store_route_count: int
    carrier_seats_current: int
    carrier_seats_prior: int
    carrier_seat_change: int
    carrier_seat_change_pct: float | None
    oa_seats_current: int
    oa_seats_prior: int
    oa_seat_change: int
    oa_seat_change_pct: float | None


@dataclass(frozen=True)
class SameStoreRoutePage:
    routes: tuple[SameStoreRouteCapacity, ...]
    total: int
    limit: int
    offset: int


def parse_month(value: str) -> str:
    """Convert CLI input such as 2026-07 to the database's ISO month date."""

    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m-01")
    except ValueError as error:
        raise ValueError(f"Month must use YYYY-MM format; received {value!r}.") from error


def parse_analysis_period(value: str) -> AnalysisPeriod:
    """Parse a YYYY-MM or YYYY-QN label into current and prior-year month bounds."""

    month_match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", value)
    if month_match:
        year, month = (int(part) for part in month_match.groups())
        return AnalysisPeriod(
            label=value,
            comparison_label=f"{year - 1:04d}-{month:02d}",
            granularity="month",
            current_start=date(year, month, 1),
            current_end=date(year, month, 1),
            prior_start=date(year - 1, month, 1),
            prior_end=date(year - 1, month, 1),
        )

    quarter_match = re.fullmatch(r"(\d{4})-Q([1-4])", value.upper())
    if quarter_match:
        year, quarter = (int(part) for part in quarter_match.groups())
        first_month = 3 * (quarter - 1) + 1
        last_month = first_month + 2
        return AnalysisPeriod(
            label=f"{year:04d}-Q{quarter}",
            comparison_label=f"{year - 1:04d}-Q{quarter}",
            granularity="quarter",
            current_start=date(year, first_month, 1),
            current_end=date(year, last_month, 1),
            prior_start=date(year - 1, first_month, 1),
            prior_end=date(year - 1, last_month, 1),
        )

    raise ValueError(
        f"Period must use YYYY-MM or YYYY-QN format; received {value!r}."
    )


def _normalize_carrier_code(value: str) -> str:
    carrier_code = value.strip().upper()
    if not _CARRIER_CODE.fullmatch(carrier_code):
        raise ValueError(f"Invalid carrier code {value!r}.")
    return carrier_code


def _active_batch_subquery() -> str:
    return """
        SELECT source_batch_id
        FROM import_batch
        GROUP BY source_batch_id
        HAVING COUNT(DISTINCT report_type) = 2
        ORDER BY MAX(imported_at) DESC
        LIMIT 1
    """


def _validate_analysis_request(
    connection: duckdb.DuckDBPyConnection,
    carrier_code: str,
    period: AnalysisPeriod,
) -> None:
    first_month, last_month, carrier_records = connection.execute(
        f"""
        SELECT
          MIN(travel_month),
          MAX(travel_month),
          COUNT(*) FILTER (WHERE carrier_code = ?)
        FROM carrier_capacity
        WHERE source_batch_id = ({_active_batch_subquery()})
        """,
        [carrier_code],
    ).fetchone()

    if first_month is None or last_month is None:
        raise ValueError("The warehouse does not contain an active imported batch.")
    if carrier_records == 0:
        raise ValueError(f"Carrier {carrier_code!r} does not exist in the warehouse.")
    if period.prior_start < first_month or period.current_end > last_month:
        raise ValueError(
            f"Period {period.label} requires data from "
            f"{period.prior_start:%Y-%m} through {period.current_end:%Y-%m}; "
            f"the warehouse covers {first_month:%Y-%m} through {last_month:%Y-%m}."
        )


def _same_store_parameters(
    carrier_code: str, period: AnalysisPeriod
) -> list[str | date]:
    return [
        carrier_code,
        period.current_start,
        period.current_end,
        period.prior_start,
        period.prior_end,
    ]


def _route_from_row(row: tuple[object, ...]) -> SameStoreRouteCapacity:
    return SameStoreRouteCapacity(
        origin_code=row[0],
        destination_code=row[1],
        carrier_seats_current=row[2],
        carrier_seats_prior=row[3],
        carrier_seat_change=row[4],
        carrier_seat_change_pct=row[5],
        market_seats_current=row[6],
        market_seats_prior=row[7],
        oa_seats_current=row[8],
        oa_seats_prior=row[9],
        oa_seat_change=row[10],
        oa_seat_change_pct=row[11],
    )


def get_carriers(database_path: Path) -> tuple[str, ...]:
    """Return carriers in the active warehouse batch."""

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            f"""
            SELECT DISTINCT carrier_code
            FROM carrier_capacity
            WHERE source_batch_id = ({_active_batch_subquery()})
            ORDER BY carrier_code
            """
        ).fetchall()
    finally:
        connection.close()
    return tuple(row[0] for row in rows)


def get_available_periods(
    database_path: Path, granularity: PeriodGranularity
) -> tuple[str, ...]:
    """Return periods with complete matching prior-year months."""

    if granularity not in ("month", "quarter"):
        raise ValueError(f"Unsupported period granularity {granularity!r}.")

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        month_rows = connection.execute(
            f"""
            SELECT DISTINCT travel_month
            FROM market_capacity
            WHERE source_batch_id = ({_active_batch_subquery()})
            ORDER BY travel_month
            """
        ).fetchall()
    finally:
        connection.close()

    months = {row[0] for row in month_rows}
    if granularity == "month":
        return tuple(
            month.strftime("%Y-%m")
            for month in sorted(months)
            if month.replace(year=month.year - 1) in months
        )

    quarter_labels: list[str] = []
    years = sorted({month.year for month in months})
    for year in years:
        for quarter in range(1, 5):
            first_month = 3 * (quarter - 1) + 1
            current = {
                date(year, first_month + offset, 1) for offset in range(3)
            }
            prior = {
                date(year - 1, first_month + offset, 1) for offset in range(3)
            }
            if current <= months and prior <= months:
                quarter_labels.append(f"{year:04d}-Q{quarter}")
    return tuple(quarter_labels)


def get_route_capacity(
    database_path: Path,
    carrier_code: str,
    origin_code: str,
    destination_code: str,
    month: str,
) -> RouteCapacity | None:
    """Return carrier, market, and implied OA seats for one directional O&D-month."""

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        row = connection.execute(
            """
            SELECT
              c.travel_month,
              c.carrier_code,
              c.origin_code,
              c.destination_code,
              c.seats AS carrier_seats,
              m.seats AS market_seats,
              m.seats - c.seats AS other_airline_seats
            FROM carrier_capacity AS c
            INNER JOIN market_capacity AS m
              ON c.travel_month = m.travel_month
             AND c.origin_code = m.origin_code
             AND c.destination_code = m.destination_code
             AND c.source_batch_id = m.source_batch_id
            WHERE c.travel_month = ?
              AND c.carrier_code = ?
              AND c.origin_code = ?
              AND c.destination_code = ?
            """,
            [
                parse_month(month),
                carrier_code.upper(),
                origin_code.upper(),
                destination_code.upper(),
            ],
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return RouteCapacity(
        travel_month=row[0].isoformat(),
        carrier_code=row[1],
        origin_code=row[2],
        destination_code=row[3],
        carrier_seats=row[4],
        market_seats=row[5],
        other_airline_seats=row[6],
    )


def get_same_store_routes(
    database_path: Path, carrier_code: str, period_value: str
) -> tuple[SameStoreRouteCapacity, ...]:
    """Return route-level same-store carrier and OA metrics."""

    normalized_carrier = _normalize_carrier_code(carrier_code)
    period = parse_analysis_period(period_value)
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        _validate_analysis_request(connection, normalized_carrier, period)
        rows = connection.execute(
            f"""
            SELECT *
            FROM ({_SAME_STORE_ROUTES_SQL}) AS same_store_routes
            ORDER BY origin_code, destination_code
            """,
            _same_store_parameters(normalized_carrier, period),
        ).fetchall()
    finally:
        connection.close()

    return tuple(_route_from_row(row) for row in rows)


def get_same_store_route_page(
    database_path: Path,
    carrier_code: str,
    period_value: str,
    sort: RouteSort,
    limit: int,
    offset: int,
) -> SameStoreRoutePage:
    """Return a ranked and paginated page from the canonical route query."""

    sort_columns = {
        "oa_change": "oa_seat_change",
        "carrier_change": "carrier_seat_change",
    }
    if sort not in sort_columns:
        raise ValueError(f"Unsupported route sort {sort!r}.")
    if limit < 1 or limit > 500:
        raise ValueError("Route page limit must be between 1 and 500.")
    if offset < 0:
        raise ValueError("Route page offset cannot be negative.")

    normalized_carrier = _normalize_carrier_code(carrier_code)
    period = parse_analysis_period(period_value)
    parameters = _same_store_parameters(normalized_carrier, period)
    canonical_query = f"({_SAME_STORE_ROUTES_SQL}) AS same_store_routes"
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        _validate_analysis_request(connection, normalized_carrier, period)
        total = connection.execute(
            f"SELECT COUNT(*) FROM {canonical_query}",
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT *
            FROM {canonical_query}
            ORDER BY ABS({sort_columns[sort]}) DESC, origin_code, destination_code
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
    finally:
        connection.close()

    return SameStoreRoutePage(
        routes=tuple(_route_from_row(row) for row in rows),
        total=total,
        limit=limit,
        offset=offset,
    )


def get_same_store_summary(
    database_path: Path, carrier_code: str, period_value: str
) -> SameStoreSummary:
    """Aggregate the canonical same-store route query into dashboard metrics."""

    normalized_carrier = _normalize_carrier_code(carrier_code)
    period = parse_analysis_period(period_value)
    summary_sql = f"""
        SELECT
          COUNT(*) AS same_store_route_count,
          COALESCE(SUM(carrier_seats_current), 0) AS carrier_seats_current,
          COALESCE(SUM(carrier_seats_prior), 0) AS carrier_seats_prior,
          COALESCE(SUM(carrier_seats_current), 0)
            - COALESCE(SUM(carrier_seats_prior), 0) AS carrier_seat_change,
          CAST(
            COALESCE(SUM(carrier_seats_current), 0)
              - COALESCE(SUM(carrier_seats_prior), 0)
            AS DOUBLE
          ) / NULLIF(SUM(carrier_seats_prior), 0) AS carrier_seat_change_pct,
          COALESCE(SUM(oa_seats_current), 0) AS oa_seats_current,
          COALESCE(SUM(oa_seats_prior), 0) AS oa_seats_prior,
          COALESCE(SUM(oa_seats_current), 0)
            - COALESCE(SUM(oa_seats_prior), 0) AS oa_seat_change,
          CAST(
            COALESCE(SUM(oa_seats_current), 0)
              - COALESCE(SUM(oa_seats_prior), 0)
            AS DOUBLE
          ) / NULLIF(SUM(oa_seats_prior), 0) AS oa_seat_change_pct
        FROM ({_SAME_STORE_ROUTES_SQL}) AS same_store_routes
    """

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        _validate_analysis_request(connection, normalized_carrier, period)
        row = connection.execute(
            summary_sql,
            _same_store_parameters(normalized_carrier, period),
        ).fetchone()
    finally:
        connection.close()

    return SameStoreSummary(
        carrier_code=normalized_carrier,
        period=period.label,
        comparison_period=period.comparison_label,
        same_store_route_count=row[0],
        carrier_seats_current=row[1],
        carrier_seats_prior=row[2],
        carrier_seat_change=row[3],
        carrier_seat_change_pct=row[4],
        oa_seats_current=row[5],
        oa_seats_prior=row[6],
        oa_seat_change=row[7],
        oa_seat_change_pct=row[8],
    )
