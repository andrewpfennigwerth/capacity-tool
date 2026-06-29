from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capacity_tool.api.app import create_app


@pytest.fixture
def client(same_store_database: Path) -> TestClient:
    with TestClient(create_app(same_store_database)) as test_client:
        yield test_client


def test_openapi_documents_all_mvp_endpoints(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Capacity Tool API"
    assert {
        "/health",
        "/api/carriers",
        "/api/periods",
        "/api/capacity/summary",
        "/api/capacity/routes",
    } <= set(schema["paths"])


def test_metadata_endpoints_return_valid_analysis_options(
    client: TestClient,
) -> None:
    assert client.get("/api/carriers").json() == {"carriers": ["DL"]}
    assert client.get(
        "/api/periods", params={"granularity": "month"}
    ).json() == {
        "granularity": "month",
        "periods": ["2026-04", "2026-05", "2026-06"],
    }
    assert client.get(
        "/api/periods", params={"granularity": "quarter"}
    ).json() == {
        "granularity": "quarter",
        "periods": ["2026-Q2"],
    }


def test_summary_endpoint_returns_typed_same_store_metrics(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/capacity/summary",
        params={"carrier": "dl", "period": "2026-Q2"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["route_set_policy"] == (
        "same_store_directional_nonzero_current_and_prior_year"
    )
    assert result["carrier_code"] == "DL"
    assert result["comparison_period"] == "2025-Q2"
    assert result["same_store_route_count"] == 3
    assert result["carrier_seats_current"] == 400
    assert result["carrier_seats_prior"] == 330
    assert result["carrier_seat_change_pct"] == pytest.approx(70 / 330)
    assert result["oa_seats_current"] == 730
    assert result["oa_seats_prior"] == 460
    assert result["oa_seat_change_pct"] == pytest.approx(270 / 460)


def test_routes_endpoint_ranks_and_paginates_canonical_routes(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/capacity/routes",
        params={
            "carrier": "DL",
            "period": "2026-Q2",
            "sort": "oa_change",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 3
    assert result["limit"] == 1
    assert result["offset"] == 0
    assert len(result["routes"]) == 1
    assert result["routes"][0]["origin_code"] == "AAA"
    assert result["routes"][0]["destination_code"] == "BBB"
    assert result["routes"][0]["oa_seat_change"] == 160


def test_routes_endpoint_filters_one_exact_directional_route(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/capacity/routes",
        params={
            "carrier": "DL",
            "period": "2026-Q2",
            "origin": "bbb",
            "destination": "aaa",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert len(result["routes"]) == 1
    assert result["routes"][0]["origin_code"] == "BBB"
    assert result["routes"][0]["destination_code"] == "AAA"


def test_api_returns_clear_client_errors(client: TestClient) -> None:
    unavailable_period = client.get(
        "/api/capacity/summary",
        params={"carrier": "DL", "period": "2025-Q2"},
    )
    assert unavailable_period.status_code == 400
    assert "requires data" in unavailable_period.json()["detail"]

    invalid_page = client.get(
        "/api/capacity/routes",
        params={
            "carrier": "DL",
            "period": "2026-Q2",
            "limit": 0,
        },
    )
    assert invalid_page.status_code == 422

    incomplete_od = client.get(
        "/api/capacity/routes",
        params={
            "carrier": "DL",
            "period": "2026-Q2",
            "origin": "AAA",
        },
    )
    assert incomplete_od.status_code == 400
    assert "supplied together" in incomplete_od.json()["detail"]


def test_api_reports_missing_warehouse_as_unavailable(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "missing.duckdb")) as client:
        response = client.get("/api/carriers")

    assert response.status_code == 503
    assert "Run ingestion first" in response.json()["detail"]
