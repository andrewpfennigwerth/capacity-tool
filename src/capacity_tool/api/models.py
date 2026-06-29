"""Typed API contracts exposed through OpenAPI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ROUTE_SET_POLICY = "same_store_directional_nonzero_current_and_prior_year"


class HealthResponse(BaseModel):
    status: Literal["ok"]


class CarrierListResponse(BaseModel):
    carriers: list[str]


class PeriodListResponse(BaseModel):
    granularity: Literal["month", "quarter"]
    periods: list[str]


class SameStoreSummaryResponse(BaseModel):
    route_set_policy: str = ROUTE_SET_POLICY
    carrier_code: str
    period: str
    comparison_period: str
    same_store_route_count: int = Field(ge=0)
    carrier_seats_current: int = Field(ge=0)
    carrier_seats_prior: int = Field(ge=0)
    carrier_seat_change: int
    carrier_seat_change_pct: float | None
    oa_seats_current: int = Field(ge=0)
    oa_seats_prior: int = Field(ge=0)
    oa_seat_change: int
    oa_seat_change_pct: float | None


class SameStoreRouteResponse(BaseModel):
    origin_code: str
    destination_code: str
    carrier_seats_current: int = Field(ge=0)
    carrier_seats_prior: int = Field(ge=0)
    carrier_seat_change: int
    carrier_seat_change_pct: float | None
    market_seats_current: int = Field(ge=0)
    market_seats_prior: int = Field(ge=0)
    oa_seats_current: int = Field(ge=0)
    oa_seats_prior: int = Field(ge=0)
    oa_seat_change: int
    oa_seat_change_pct: float | None


class SameStoreRoutePageResponse(BaseModel):
    route_set_policy: str = ROUTE_SET_POLICY
    carrier_code: str
    period: str
    comparison_period: str
    sort: Literal["oa_change", "carrier_change"]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    routes: list[SameStoreRouteResponse]
