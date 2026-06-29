# Capacity Tool

An analytical application for comparing an airline's same-store directional route capacity with all-other-airline (OA) capacity on that same route set.

## Milestone 1: analytical foundation

The project currently contains a reproducible ingestion command. It reads the two supplied schedule reports, validates their shape and reconciliation, and builds a local DuckDB warehouse.

The source reports are intentionally ignored by Git. They stay in `data/`; generated warehouse files stay in `warehouse/`.

### Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

### Build the warehouse

```sh
.venv/bin/capacity-ingest ingest
```

The command expects these ignored source files:

```text
data/CC Coverage 06-09-26.csv
data/CC OA 06-09-26.csv
```

It creates `warehouse/capacity.duckdb` only after validating:

- the report header and tabular section;
- date, code, seat-value, and duplicate-key rules;
- matching market rows for all carrier O&D/month rows;
- carrier capacity does not exceed market capacity at the O&D/month level.

### Basic route check

```sh
.venv/bin/capacity-ingest route \
  --carrier DL \
  --origin LGA \
  --destination RSW \
  --month 2026-07
```

This returns the selected carrier's seats, total market seats, and implied OA seats for one **directional** O&D/month.

### Verify the test suite

```sh
.venv/bin/python -m pytest
```

## Concepts to understand

- **Raw report versus analytical table:** the provided CSV files are export reports with title and footer metadata, not clean database tables. Ingestion isolates the actual data rows and makes typed tables.
- **DuckDB:** an embedded analytical database stored in one local file. It runs SQL without operating a separate database server.
- **Natural key:** the fields that uniquely identify a source record. Here, carrier capacity uses month + carrier + origin + destination; market capacity uses month + origin + destination.
- **Reconciliation:** a validation that two related sources agree enough to use together. Here, each carrier O&D/month must exist in the market data and combined supplied carrier seats cannot exceed total market seats.

The next milestone implements the same-store monthly and quarterly SQL calculation on this trusted data foundation.

## Milestone 2: same-store analytics

The canonical SQL in `src/capacity_tool/sql/same_store_routes.sql`:

1. Aggregates the selected carrier by directional O&D in the current period.
2. Repeats that aggregation for the equivalent prior-year period.
3. Inner-joins those route sets, excluding new, dropped, and zero-capacity routes.
4. Attaches market capacity for the exact same routes and periods.
5. Calculates current/prior carrier seats, OA seats, absolute changes, and change ratios.

Run an aggregate quarterly comparison:

```sh
.venv/bin/capacity-ingest same-store-summary \
  --carrier DL \
  --period 2026-Q2
```

Inspect the largest route-level OA drivers:

```sh
.venv/bin/capacity-ingest same-store-routes \
  --carrier DL \
  --period 2026-Q2 \
  --sort oa-change \
  --limit 20
```

Periods accept `YYYY-MM` for monthly comparisons and `YYYY-QN` for quarterly comparisons. Percentages are calculated from aggregate seat totals in SQL and returned as ratios; presentation code formats `0.047` as `4.7%`.

## Milestone 3: HTTP API

Start the local FastAPI server from the repository root:

```sh
.venv/bin/uvicorn capacity_tool.api.app:app --reload
```

Then open the generated interactive OpenAPI documentation:

```text
http://127.0.0.1:8000/docs
```

The API exposes:

```text
GET /health
GET /api/carriers
GET /api/periods?granularity=month|quarter
GET /api/capacity/summary?carrier=DL&period=2026-Q2
GET /api/capacity/routes?carrier=DL&period=2026-Q2&sort=oa_change&limit=50&offset=0
GET /api/capacity/routes?carrier=DL&period=2026-Q2&origin=LGA&destination=RSW
```

The endpoint functions validate HTTP input and map typed query results into Pydantic response models. They do not duplicate the same-store calculation; all analytical population and metric logic remains in the canonical SQL query.

`origin` and `destination` are optional exact filters, but they must be supplied together. Because O&Ds are directional, filtering `LGA→RSW` does not also return `RSW→LGA`.
