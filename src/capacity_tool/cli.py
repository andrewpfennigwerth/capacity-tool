"""Command-line entry points for the Milestone 1 warehouse."""

from __future__ import annotations

import argparse
from pathlib import Path

from capacity_tool.ingestion import ValidationError, build_warehouse
from capacity_tool.queries import (
    get_route_capacity,
    get_same_store_route_page,
    get_same_store_summary,
)


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

    summary = commands.add_parser(
        "same-store-summary",
        help="Calculate aggregate same-store carrier and OA capacity.",
    )
    summary.add_argument("--carrier", required=True, help="Marketing carrier code.")
    summary.add_argument(
        "--period", required=True, help="Current period in YYYY-MM or YYYY-QN format."
    )
    summary.add_argument(
        "--database",
        type=Path,
        default=Path("warehouse/capacity.duckdb"),
        help="Path to an existing DuckDB warehouse.",
    )

    routes = commands.add_parser(
        "same-store-routes",
        help="Show route-level same-store carrier and OA capacity.",
    )
    routes.add_argument("--carrier", required=True, help="Marketing carrier code.")
    routes.add_argument(
        "--period", required=True, help="Current period in YYYY-MM or YYYY-QN format."
    )
    routes.add_argument(
        "--limit", type=int, default=20, help="Maximum routes to display."
    )
    routes.add_argument(
        "--sort",
        choices=("oa-change", "carrier-change"),
        default="oa-change",
        help="Absolute-change metric used to rank displayed routes.",
    )
    routes.add_argument(
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


def _format_percent(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1%}"


def _run_same_store_summary(args: argparse.Namespace) -> int:
    summary = get_same_store_summary(args.database, args.carrier, args.period)
    print(
        f"{summary.carrier_code} same-store: "
        f"{summary.period} vs {summary.comparison_period}"
    )
    print(f"Directional routes: {summary.same_store_route_count:,}")
    print(
        "Carrier seats: "
        f"{summary.carrier_seats_current:,} vs {summary.carrier_seats_prior:,}; "
        f"{summary.carrier_seat_change:+,} "
        f"({_format_percent(summary.carrier_seat_change_pct)})"
    )
    print(
        "OA seats:      "
        f"{summary.oa_seats_current:,} vs {summary.oa_seats_prior:,}; "
        f"{summary.oa_seat_change:+,} "
        f"({_format_percent(summary.oa_seat_change_pct)})"
    )
    return 0


def _run_same_store_routes(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise ValueError("--limit must be greater than zero.")

    page = get_same_store_route_page(
        args.database,
        args.carrier,
        args.period,
        args.sort.replace("-", "_"),
        args.limit,
        0,
    )

    print(
        f"{args.carrier.upper()} same-store route drivers for {args.period} "
        f"(top {len(page.routes)} of {page.total})"
    )
    print(
        "O&D       Carrier current/prior   Change       OA current/prior        Change"
    )
    for route in page.routes:
        print(
            f"{route.origin_code}→{route.destination_code:<3}  "
            f"{route.carrier_seats_current:>10,}/{route.carrier_seats_prior:<10,} "
            f"{route.carrier_seat_change:>+10,}  "
            f"{route.oa_seats_current:>10,}/{route.oa_seats_prior:<10,} "
            f"{route.oa_seat_change:>+10,}"
        )
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            return _run_ingest(args)
        if args.command == "route":
            return _run_route(args)
        if args.command == "same-store-summary":
            return _run_same_store_summary(args)
        return _run_same_store_routes(args)
    except (OSError, ValidationError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
