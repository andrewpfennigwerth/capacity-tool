from __future__ import annotations

from pathlib import Path

import pytest

from capacity_tool.queries import (
    get_same_store_routes,
    get_same_store_summary,
    parse_analysis_period,
)


def test_parse_analysis_period_supports_months_and_quarters() -> None:
    month = parse_analysis_period("2026-07")
    assert month.comparison_label == "2025-07"
    assert month.current_start == month.current_end

    quarter = parse_analysis_period("2026-Q2")
    assert quarter.comparison_label == "2025-Q2"
    assert quarter.current_start.isoformat() == "2026-04-01"
    assert quarter.current_end.isoformat() == "2026-06-01"
    assert quarter.prior_start.isoformat() == "2025-04-01"
    assert quarter.prior_end.isoformat() == "2025-06-01"


def test_same_store_routes_intersect_current_and_prior_periods(
    same_store_database: Path,
) -> None:
    routes = get_same_store_routes(same_store_database, "dl", "2026-Q2")
    route_by_od = {
        (route.origin_code, route.destination_code): route for route in routes
    }

    assert set(route_by_od) == {
        ("AAA", "BBB"),
        ("BBB", "AAA"),
        ("EEE", "FFF"),
    }
    assert ("AAA", "CCC") not in route_by_od  # new route
    assert ("AAA", "DDD") not in route_by_od  # dropped route
    assert ("GGG", "HHH") not in route_by_od  # zero-capacity route

    outbound = route_by_od[("AAA", "BBB")]
    assert outbound.carrier_seats_current == 240
    assert outbound.carrier_seats_prior == 200
    assert outbound.carrier_seat_change == 40
    assert outbound.carrier_seat_change_pct == pytest.approx(0.20)
    assert outbound.oa_seats_current == 560
    assert outbound.oa_seats_prior == 400
    assert outbound.oa_seat_change_pct == pytest.approx(0.40)

    reverse = route_by_od[("BBB", "AAA")]
    assert reverse.oa_seats_prior == 0
    assert reverse.oa_seat_change_pct is None

    seasonal = route_by_od[("EEE", "FFF")]
    assert seasonal.carrier_seats_current == 100
    assert seasonal.carrier_seats_prior == 80
    assert seasonal.market_seats_current == 210
    assert seasonal.market_seats_prior == 140
    assert seasonal.oa_seats_current == 110
    assert seasonal.oa_seats_prior == 60


def test_same_store_summary_uses_aggregate_totals(
    same_store_database: Path,
) -> None:
    summary = get_same_store_summary(same_store_database, "DL", "2026-Q2")

    assert summary.period == "2026-Q2"
    assert summary.comparison_period == "2025-Q2"
    assert summary.same_store_route_count == 3
    assert summary.carrier_seats_current == 400
    assert summary.carrier_seats_prior == 330
    assert summary.carrier_seat_change == 70
    assert summary.carrier_seat_change_pct == pytest.approx(70 / 330)
    assert summary.oa_seats_current == 730
    assert summary.oa_seats_prior == 460
    assert summary.oa_seat_change == 270
    assert summary.oa_seat_change_pct == pytest.approx(270 / 460)


def test_same_store_rejects_period_without_prior_year_data(
    same_store_database: Path,
) -> None:
    with pytest.raises(ValueError, match="requires data"):
        get_same_store_summary(same_store_database, "DL", "2025-Q2")
