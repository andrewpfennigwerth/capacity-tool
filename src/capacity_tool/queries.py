"""Small, explicit analytical queries used to validate the warehouse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class RouteCapacity:
    travel_month: str
    carrier_code: str
    origin_code: str
    destination_code: str
    carrier_seats: int
    market_seats: int
    other_airline_seats: int


def parse_month(value: str) -> str:
    """Convert CLI input such as 2026-07 to the database's ISO month date."""

    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m-01")
    except ValueError as error:
        raise ValueError(f"Month must use YYYY-MM format; received {value!r}.") from error


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
