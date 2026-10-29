# Trade Store API

A Python REST API that stores trades in SQLite, validates incoming versions and maturity dates, and automatically marks matured trades as expired.

## Requirements

- Python 3.12+
- Packages in `requirements.txt`

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn trade_store.main:app --reload
```

The default database is `./trades.db`. Atomic version-aware upserts are implemented for SQLite and PostgreSQL; PostgreSQL also requires an installed SQLAlchemy driver. The API is available at `http://127.0.0.1:8000`; interactive OpenAPI documentation is at `/docs`.

## API

### `POST /trades`

Create or replace a trade. `created_date` is optional and defaults to the server's current date.

```json
{
  "trade_id": "T1",
  "version": 1,
  "counterparty_id": "CP-1",
  "portfolio_id": "B1",
  "maturity_date": "2030-05-20"
}
```

- Returns `201 Created` for a new trade and `200 OK` when replacing an existing trade.
- Equal or higher versions replace the existing record. Lower versions return `409 Conflict`.
- IDs must be non-empty strings of at most 64 characters, and `version` must be a positive JSON integer.
- Dates must be valid calendar dates in exact `YYYY-MM-DD` format. A maturity date before today or a supplied creation date after today returns `422 Unprocessable Entity`.
- Unknown fields and explicit `null` values for required fields (or for a supplied `created_date`) return `422 Unprocessable Entity`.
- Swagger's request example uses representative trade values; placeholder identifiers such as `"string"` are rejected.

### `GET /trades`

Lists trades ordered by trade ID (not by transmission/arrival order). Supports `limit` (default 100, maximum 1000) and `offset` (default 0). If the assignment requires arrival order, that ordering needs to be defined and stored explicitly.

### `GET /trades/{trade_id}`

Returns one trade or `404 Not Found`.

Matured trades are persisted as expired at application startup and periodically while the service is running (once per minute by default). Reads report a trade as expired as soon as its maturity date is earlier than today, without running a table-wide update for each API request. A trade maturing today is not yet expired.

Database constraints also enforce positive versions and non-empty, bounded identifiers for databases initialized with the current schema.

## Tests

```bash
python -m pytest -q
```

The tests cover trade creation, version replacement and rejection, concurrent version updates, database constraints, required/null fields, strict date formats and calendar dates, identifier and version constraints, maturity validation and expiry, not-found responses, and pagination.

## Manual functional testing

To test from an empty database without changing the project's default `trades.db`, start the API with a separate temporary SQLite database:

```bash
cd /path/to/dws-trade-store
source .venv/bin/activate
export DATABASE_URL="sqlite:////tmp/trade-store-test.db"
python -m uvicorn trade_store.main:app --reload
```

If your virtual environment is in another location, activate that environment instead. Keep this terminal open while testing. Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), expand **POST `/trades`**, click **Try it out**, replace the example values as needed, and click **Execute**. Use **GET `/trades/{trade_id}`** to inspect a trade and **GET `/trades`** to list trades.

Run these scenarios in order, using a maturity date later than today's date:

| Scenario | Request | Expected result |
|---|---|---|
| Create T1 | Version `1`, counterparty `CP-1`, maturity date in the future | `201 Created`; response has today's `created_date` and `expired: false` |
| Replace with same version | T1, version `1`, change counterparty to `CP-2` | `200 OK`; GET T1 shows `CP-2` |
| Replace with higher version | T1, version `2`, counterparty `CP-3` | `200 OK`; GET T1 shows version `2` and `CP-3` |
| Reject lower version | T1, version `1`, counterparty `CP-OLD` | `409 Conflict`; GET T1 still shows version `2` and `CP-3` |
| Reject past maturity | New trade ID, maturity date earlier than today | `422 Unprocessable Entity`; trade is rejected |
| Reject malformed date | New trade ID, maturity date such as `20/05/2035` | `422 Unprocessable Entity` |
| Reject Swagger placeholder | Set an identifier to `"string"` | `422 Unprocessable Entity` |

The original sample maturity dates (2014–2021) are now in the past; use future dates when testing successful trade submissions.

To test automatic expiration without waiting for a real maturity date to pass, run the simulated-date background-worker test in a second terminal:

```bash
cd /path/to/dws-trade-store
source .venv/bin/activate
python -m pytest -q tests/test_api.py::test_background_worker_expires_matured_trades_without_requests
```

The API persists expired flags periodically (once per minute by default). A read also reports a trade as expired as soon as its maturity date is before today.

## CI and dependency scanning

GitHub Actions runs the automated test suite and scans dependencies with Trivy on pushes and pull requests. The scan fails the build if it finds a critical vulnerability.

## Deployment

The Render Blueprint in `render.yaml` defines the FastAPI web service and its PostgreSQL database. The GitHub Actions deploy job triggers a Render deploy hook only after tests and the vulnerability scan pass on a push to `main`; pull requests do not deploy. Deployment is disabled until configured:

1. In Render, create a Blueprint Instance for this repository and wait for the service and database to be created. The web service has automatic deploys disabled so deployments remain gated by CI.
2. In the Render service settings, create a deploy hook and copy its URL.
3. In the GitHub repository, open **Settings > Secrets and variables > Actions**. Add the repository secret `RENDER_DEPLOY_HOOK_URL` with the hook URL and the repository variable `RENDER_DEPLOY_ENABLED` with value `true`.
4. Push a change to `main`. The deploy job will run after both CI jobs succeed. The service URL and deployment status are available in Render.

The included free Render plans are intended for a demo; review Render's current availability, limits, and database retention before relying on them for production data.

## Diagrams

The trade-ingestion sequence diagram is maintained as a standalone PlantUML source file: [docs/trade-store-sequence.puml](docs/trade-store-sequence.puml). Open that file in VS Code and use **PlantUML: Preview Current Diagram** to render it.
