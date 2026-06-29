"""Command-line entry points for the Milestone 1 warehouse."""

from __future__ import annotations

import argparse
from pathlib import Path

from capacity_tool.ingestion import ValidationError, build_warehouse
from capacity_tool.queries import get_route_capacity


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capacity-ingest",
        description="Build and inspect the airline-capacity analytical warehouse.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Validate source reports and build DuckDB.")
    ingest.add_argument(
        "--coverage",
        type=Path,
        default=Path("data/CC Coverage 06-09-26.csv"),
        help="Path to the carrier-level Capacity Coverage report.",
    )
    ingest.add_argument(
        "--market",
        type=Path,
        default=Path("data/CC OA 06-09-26.csv"),
        help="Path to the market-level OA report.",
    )
    ingest.add_argument(
        "--database",
        type=Path,
        default=Path("warehouse/capacity.duckdb"),
        help="Destination DuckDB file. It is rebuilt on each successful import.",
    )

    route = commands.add_parser(
        "route", help="Inspect carrier, market, and OA seats for one directional route."
    )
    route.add_argument("--carrier", required=True, help="Marketing carrier code, e.g. DL.")
    route.add_argument("--origin", required=True, help="Origin airport code, e.g. LGA.")
    route.add_argument(
        "--destination", required=True, help="Destination airport code, e.g. RSW."
    )
    route.add_argument("--month", required=True, help="Travel month in YYYY-MM format.")
    route.add_argument(
        "--database",
        type=Path,
        default=Path("warehouse/capacity.duckdb"),
        help="Path to an existing DuckDB warehouse.",
    )
    return parser


def _run_ingest(args: argparse.Namespace) -> int:
    summary = build_warehouse(args.coverage, args.market, args.database)
    print(f"Built {summary.database_path}")
    print(f"Batch: {summary.source_batch_id}")
    print(
        "Coverage: "
        f"{summary.carrier_record_count:,} records across {summary.carrier_count} carriers"
    )
    print(f"Market: {summary.market_record_count:,} records")
    print(f"Travel months: {summary.first_month:%b %Y} to {summary.last_month:%b %Y}")
    return 0


def _run_route(args: argparse.Namespace) -> int:
    result = get_route_capacity(
        args.database,
        args.carrier,
        args.origin,
        args.destination,
        args.month,
    )
    if result is None:
        print("No carrier-capacity record matches that directional O&D-month.")
        return 1
    print(
        f"{result.carrier_code} {result.origin_code}→{result.destination_code} "
        f"({result.travel_month})"
    )
    print(f"Carrier seats:       {result.carrier_seats:,}")
    print(f"Market seats:        {result.market_seats:,}")
    print(f"Other-airline seats: {result.other_airline_seats:,}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            return _run_ingest(args)
        return _run_route(args)
    except (OSError, ValidationError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
