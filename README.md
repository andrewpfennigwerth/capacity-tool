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
