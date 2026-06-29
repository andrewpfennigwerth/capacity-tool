"""FastAPI application exposing the validated analytical query layer."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request

from capacity_tool.api.models import (
    CarrierListResponse,
    HealthResponse,
    PeriodListResponse,
    SameStoreRoutePageResponse,
    SameStoreRouteResponse,
    SameStoreSummaryResponse,
)
from capacity_tool.queries import (
    get_available_periods,
    get_carriers,
    get_same_store_route_page,
    get_same_store_summary,
    parse_analysis_period,
)

DEFAULT_DATABASE_PATH = Path(
    os.environ.get("CAPACITY_DATABASE_PATH", "warehouse/capacity.duckdb")
)


def _database_path(request: Request) -> Path:
    path: Path = request.app.state.database_path
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Capacity warehouse is unavailable at {path}. Run ingestion first.",
        )
    return path


def _bad_request(error: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def create_app(database_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Capacity Tool API",
        version="0.1.0",
        description=(
            "Same-store directional airline capacity and all-other-airline analytics."
        ),
    )
    app.state.database_path = database_path or DEFAULT_DATABASE_PATH

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/carriers", response_model=CarrierListResponse, tags=["metadata"])
    def carriers(request: Request) -> CarrierListResponse:
        try:
            return CarrierListResponse(carriers=list(get_carriers(_database_path(request))))
        except duckdb.Error as error:
            raise HTTPException(status_code=503, detail="Warehouse query failed.") from error

    @app.get("/api/periods", response_model=PeriodListResponse, tags=["metadata"])
    def periods(
        request: Request,
        granularity: Annotated[Literal["month", "quarter"], Query()],
    ) -> PeriodListResponse:
        try:
            values = get_available_periods(_database_path(request), granularity)
            return PeriodListResponse(granularity=granularity, periods=list(values))
        except (ValueError, duckdb.Error) as error:
            if isinstance(error, ValueError):
                raise _bad_request(error) from error
            raise HTTPException(status_code=503, detail="Warehouse query failed.") from error

    @app.get(
        "/api/capacity/summary",
        response_model=SameStoreSummaryResponse,
        tags=["capacity"],
    )
    def capacity_summary(
        request: Request,
        carrier: Annotated[str, Query(min_length=2, max_length=2)],
        period: Annotated[str, Query(min_length=7, max_length=7)],
    ) -> SameStoreSummaryResponse:
        try:
            summary = get_same_store_summary(
                _database_path(request), carrier, period
            )
            return SameStoreSummaryResponse(**asdict(summary))
        except ValueError as error:
            raise _bad_request(error) from error
        except duckdb.Error as error:
            raise HTTPException(status_code=503, detail="Warehouse query failed.") from error

    @app.get(
        "/api/capacity/routes",
        response_model=SameStoreRoutePageResponse,
        tags=["capacity"],
    )
    def capacity_routes(
        request: Request,
        carrier: Annotated[str, Query(min_length=2, max_length=2)],
        period: Annotated[str, Query(min_length=7, max_length=7)],
        sort: Annotated[
            Literal["oa_change", "carrier_change"], Query()
        ] = "oa_change",
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SameStoreRoutePageResponse:
        try:
            parsed_period = parse_analysis_period(period)
            page = get_same_store_route_page(
                _database_path(request),
                carrier,
                period,
                sort,
                limit,
                offset,
            )
            return SameStoreRoutePageResponse(
                carrier_code=carrier.upper(),
                period=parsed_period.label,
                comparison_period=parsed_period.comparison_label,
                sort=sort,
                total=page.total,
                limit=page.limit,
                offset=page.offset,
                routes=[
                    SameStoreRouteResponse(**asdict(route)) for route in page.routes
                ],
            )
        except ValueError as error:
            raise _bad_request(error) from error
        except duckdb.Error as error:
            raise HTTPException(status_code=503, detail="Warehouse query failed.") from error

    return app


app = create_app()
