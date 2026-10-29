from datetime import date, timedelta
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from trade_store.main import create_app


@pytest.fixture
def api():
    current_day = [date(2030, 1, 1)]
    app = create_app(
        database_url="sqlite://",
        expiry_interval_seconds=3600,
        today_provider=lambda: current_day[0],
    )
    with TestClient(app) as client:
        yield client, current_day


def trade_payload(**overrides):
    payload = {
        "trade_id": "T1",
        "version": 1,
        "counterparty_id": "CP-1",
        "portfolio_id": "B1",
        "maturity_date": "2030-02-01",
    }
    return payload | overrides


def test_create_trade_sets_created_date_and_is_not_expired(api):
    client, _ = api

    response = client.post("/trades", json=trade_payload())

    assert response.status_code == 201
    assert response.json() == {
        **trade_payload(),
        "created_date": "2030-01-01",
        "expired": False,
    }


def test_same_version_replaces_current_trade(api):
    client, _ = api
    client.post("/trades", json=trade_payload())

    response = client.post(
        "/trades",
        json=trade_payload(counterparty_id="CP-2", portfolio_id="B2"),
    )

    assert response.status_code == 200
    assert response.json()["counterparty_id"] == "CP-2"
    assert response.json()["portfolio_id"] == "B2"
    assert len(client.get("/trades").json()) == 1


def test_higher_version_replaces_current_trade(api):
    client, _ = api
    client.post("/trades", json=trade_payload())

    response = client.post("/trades", json=trade_payload(version=2))

    assert response.status_code == 200
    assert response.json()["version"] == 2


def test_lower_version_is_rejected_without_changing_trade(api):
    client, _ = api
    client.post("/trades", json=trade_payload(version=2))

    response = client.post(
        "/trades",
        json=trade_payload(version=1, counterparty_id="CP-OLD"),
    )

    assert response.status_code == 409
    assert client.get("/trades/T1").json()["version"] == 2
    assert client.get("/trades/T1").json()["counterparty_id"] == "CP-1"


def test_maturity_date_before_today_is_rejected(api):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(maturity_date="2029-12-31"),
    )

    assert response.status_code == 422


def test_matured_trade_is_marked_expired_when_read(api):
    client, current_day = api
    client.post("/trades", json=trade_payload(maturity_date="2030-01-02"))
    current_day[0] += timedelta(days=2)

    response = client.get("/trades/T1")

    assert response.status_code == 200
    assert response.json()["expired"] is True


def test_background_worker_expires_matured_trades_without_requests(tmp_path):
    current_day = [date(2030, 1, 1)]
    database_path = tmp_path / "trades.db"
    app = create_app(
        database_url=f"sqlite:///{database_path}",
        expiry_interval_seconds=0.01,
        today_provider=lambda: current_day[0],
    )

    with TestClient(app) as client:
        response = client.post(
            "/trades",
            json=trade_payload(maturity_date="2030-01-02"),
        )
        assert response.status_code == 201
        current_day[0] += timedelta(days=2)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with sqlite3.connect(database_path) as connection:
                row = connection.execute(
                    "SELECT expired FROM trades WHERE trade_id = ?",
                    ("T1",),
                ).fetchone()
            if row == (1,):
                break
            time.sleep(0.01)

    assert row == (1,)


def test_trade_with_maturity_today_is_not_expired(api):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(maturity_date="2030-01-01"),
    )

    assert response.status_code == 201
    assert response.json()["expired"] is False


def test_get_missing_trade_returns_404(api):
    client, _ = api

    assert client.get("/trades/unknown").status_code == 404


def test_list_trades_is_ordered_and_paginated(api):
    client, _ = api
    client.post("/trades", json=trade_payload(trade_id="T2"))
    client.post("/trades", json=trade_payload(trade_id="T1"))

    response = client.get("/trades", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert [trade["trade_id"] for trade in response.json()] == ["T2"]


def test_invalid_trade_fields_are_rejected(api):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(version=0),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["trade_id", "version", "counterparty_id", "portfolio_id", "maturity_date"],
)
def test_required_fields_reject_null(api, field):
    client, _ = api

    response = client.post("/trades", json=trade_payload(**{field: None}))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["maturity_date", "created_date"],
)
@pytest.mark.parametrize(
    "value",
    [
        "20/05/2030",
        "2030-2-01",
        "not-a-date",
        "2030-02-01T00:00:00",
        "2030-02-30",
    ],
)
def test_dates_require_exact_iso_calendar_date_format(api, field, value):
    client, _ = api
    payload = trade_payload(**{field: value})

    response = client.post("/trades", json=payload)

    assert response.status_code == 422


def test_explicit_null_created_date_is_rejected(api):
    client, _ = api

    response = client.post("/trades", json=trade_payload(created_date=None))

    assert response.status_code == 422


def test_future_created_date_is_rejected(api):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(created_date="2030-01-02"),
    )

    assert response.status_code == 422


def test_unknown_fields_are_rejected(api):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(expired=False),
    )

    assert response.status_code == 422


@pytest.mark.parametrize("version", [True, 1.5, "1"])
def test_version_must_be_an_integer(api, version):
    client, _ = api

    response = client.post("/trades", json=trade_payload(version=version))

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trade_id", ""),
        ("trade_id", " " * 3),
        ("counterparty_id", 123),
        ("portfolio_id", "B" * 65),
    ],
)
def test_identifiers_must_be_non_empty_bounded_strings(api, field, value):
    client, _ = api

    response = client.post("/trades", json=trade_payload(**{field: value}))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["trade_id", "counterparty_id", "portfolio_id"],
)
def test_schema_placeholder_identifiers_are_rejected(api, field):
    client, _ = api

    response = client.post(
        "/trades",
        json=trade_payload(**{field: "string"}),
    )

    assert response.status_code == 422


def test_openapi_trade_request_has_realistic_example(api):
    client, _ = api

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()["components"]["schemas"]["TradeCreate"]
    assert schema["examples"][0] == {
        "trade_id": "T1001",
        "version": 1,
        "counterparty_id": "CP-1",
        "portfolio_id": "B1",
        "maturity_date": "2099-12-31",
    }
