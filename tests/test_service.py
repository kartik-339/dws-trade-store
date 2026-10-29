from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from sqlalchemy.exc import IntegrityError

from trade_store.database import Base, create_database
from trade_store.models import Trade
from trade_store.service import mark_matured_trades_expired, upsert_trade


@pytest.fixture
def session_factory():
    engine, factory = create_database("sqlite://")
    Base.metadata.create_all(engine)
    yield factory
    engine.dispose()


def test_upsert_rejects_lower_version_and_preserves_current_record(session_factory):
    with session_factory() as session:
        upsert_trade(
            session,
            trade_id="T1",
            version=2,
            counterparty_id="CP-2",
            portfolio_id="B2",
            maturity_date=date(2030, 5, 20),
            created_date=date(2030, 1, 1),
        )

        with pytest.raises(ValueError, match="lower than the stored version"):
            upsert_trade(
                session,
                trade_id="T1",
                version=1,
                counterparty_id="CP-1",
                portfolio_id="B1",
                maturity_date=date(2030, 5, 20),
                created_date=date(2030, 1, 2),
            )

        current = session.get(Trade, "T1")
        assert current is not None
        assert current.version == 2
        assert current.counterparty_id == "CP-2"


def test_expiry_service_marks_only_trades_past_maturity(session_factory):
    today = date(2030, 1, 1)
    with session_factory() as session:
        session.add_all(
            [
                Trade(
                    trade_id="PAST",
                    version=1,
                    counterparty_id="CP-1",
                    portfolio_id="B1",
                    maturity_date=today - timedelta(days=1),
                    created_date=today - timedelta(days=10),
                    expired=False,
                ),
                Trade(
                    trade_id="TODAY",
                    version=1,
                    counterparty_id="CP-1",
                    portfolio_id="B1",
                    maturity_date=today,
                    created_date=today - timedelta(days=10),
                    expired=False,
                ),
            ]
        )
        session.commit()

    assert mark_matured_trades_expired(session_factory, today) == 1

    with session_factory() as session:
        assert session.get(Trade, "PAST").expired is True
        assert session.get(Trade, "TODAY").expired is False


def test_concurrent_updates_keep_the_highest_version(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'concurrent.db'}")
    Base.metadata.create_all(engine)
    with factory() as session:
        upsert_trade(
            session,
            trade_id="T1",
            version=1,
            counterparty_id="CP-1",
            portfolio_id="B1",
            maturity_date=date(2030, 5, 20),
            created_date=date(2030, 1, 1),
        )

    versions = list(range(2, 10))
    barrier = Barrier(len(versions))

    def submit(version: int) -> None:
        barrier.wait()
        with factory() as session:
            try:
                upsert_trade(
                    session,
                    trade_id="T1",
                    version=version,
                    counterparty_id=f"CP-{version}",
                    portfolio_id="B1",
                    maturity_date=date(2030, 5, 20),
                    created_date=date(2030, 1, 1),
                )
            except ValueError:
                pass

    try:
        with ThreadPoolExecutor(max_workers=len(versions)) as executor:
            list(executor.map(submit, versions))

        with factory() as session:
            stored_trade = session.get(Trade, "T1")
            assert stored_trade is not None
            assert stored_trade.version == max(versions)
    finally:
        engine.dispose()


def test_database_constraints_reject_invalid_trade_values(session_factory):
    with session_factory() as session:
        session.add(
            Trade(
                trade_id="INVALID",
                version=0,
                counterparty_id="CP-1",
                portfolio_id="B1",
                maturity_date=date(2030, 5, 20),
                created_date=date(2030, 1, 1),
                expired=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
