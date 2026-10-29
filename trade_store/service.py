from datetime import date

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from trade_store.models import Trade


def mark_matured_trades_expired(
    session_factory: sessionmaker[Session], today: date
) -> int:
    with session_factory() as session:
        result = session.execute(
            update(Trade)
            .where(Trade.expired.is_(False), Trade.maturity_date < today)
            .values(expired=True)
        )
        session.commit()
        return result.rowcount or 0


def upsert_trade(
    session: Session,
    *,
    trade_id: str,
    version: int,
    counterparty_id: str,
    portfolio_id: str,
    maturity_date: date,
    created_date: date,
) -> tuple[Trade, bool]:
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "sqlite":
        insert = sqlite_insert
    elif dialect_name == "postgresql":
        insert = postgresql_insert
    else:
        raise RuntimeError(
            f"Atomic trade upserts are not supported for {dialect_name!r}"
        )

    existing = session.get(Trade, trade_id)
    is_new = existing is None
    session.commit()

    statement = insert(Trade).values(
        trade_id=trade_id,
        version=version,
        counterparty_id=counterparty_id,
        portfolio_id=portfolio_id,
        maturity_date=maturity_date,
        created_date=created_date,
        expired=False,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Trade.trade_id],
        set_={
            "version": statement.excluded.version,
            "counterparty_id": statement.excluded.counterparty_id,
            "portfolio_id": statement.excluded.portfolio_id,
            "maturity_date": statement.excluded.maturity_date,
            "created_date": statement.excluded.created_date,
            "expired": False,
        },
        where=statement.excluded.version >= Trade.version,
    ).returning(Trade)

    trade = session.scalars(
        statement, execution_options={"populate_existing": True}
    ).one_or_none()
    if trade is None:
        session.rollback()
        stored_trade = session.get(Trade, trade_id)
        if stored_trade is None:
            raise RuntimeError(
                f"Trade {trade_id!r} disappeared during version comparison"
            )
        raise ValueError(
            f"Trade {trade_id!r} version {version} is lower than "
            f"the stored version {stored_trade.version}"
        )

    session.commit()
    return trade, is_new
