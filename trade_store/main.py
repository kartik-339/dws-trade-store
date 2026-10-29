import asyncio
import logging
import os
from collections.abc import Callable, Generator
from contextlib import asynccontextmanager, suppress
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_store.database import Base, create_database
from trade_store.models import Trade
from trade_store.schemas import TradeCreate, TradeRead
from trade_store.service import mark_matured_trades_expired, upsert_trade

logger = logging.getLogger(__name__)
DEFAULT_DATABASE_URL = "sqlite:///./trades.db"


def create_app(
    database_url: str | None = None,
    *,
    expiry_interval_seconds: float = 60,
    today_provider: Callable[[], date] = date.today,
) -> FastAPI:
    if expiry_interval_seconds <= 0:
        raise ValueError("expiry_interval_seconds must be greater than zero")

    resolved_database_url = database_url or os.getenv(
        "DATABASE_URL", DEFAULT_DATABASE_URL
    )
    engine, session_factory = create_database(resolved_database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(engine)
        await asyncio.to_thread(
            mark_matured_trades_expired, session_factory, today_provider()
        )

        async def expire_periodically() -> None:
            while True:
                await asyncio.sleep(expiry_interval_seconds)
                try:
                    await asyncio.to_thread(
                        mark_matured_trades_expired,
                        session_factory,
                        today_provider(),
                    )
                except Exception:
                    logger.exception("Failed to expire matured trades")

        expiry_task = asyncio.create_task(expire_periodically())
        try:
            yield
        finally:
            expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await expiry_task
            engine.dispose()

    app = FastAPI(title="Trade Store API", version="1.0.0", lifespan=lifespan)

    def get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    SessionDependency = Annotated[Session, Depends(get_session)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/trades", response_model=TradeRead)
    def receive_trade(
        payload: TradeCreate,
        response: Response,
        session: SessionDependency,
    ) -> Trade:
        today = today_provider()
        if payload.maturity_date < today:
            raise HTTPException(
                status_code=422,
                detail="maturity_date cannot be earlier than today",
            )
        if payload.created_date is not None and payload.created_date > today:
            raise HTTPException(
                status_code=422,
                detail="created_date cannot be later than today",
            )
        try:
            trade, is_new = upsert_trade(
                session,
                trade_id=payload.trade_id,
                version=payload.version,
                counterparty_id=payload.counterparty_id,
                portfolio_id=payload.portfolio_id,
                maturity_date=payload.maturity_date,
                created_date=payload.created_date or today,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        response.status_code = 201 if is_new else 200
        return trade

    @app.get("/trades", response_model=list[TradeRead])
    def list_trades(
        session: SessionDependency,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[Trade]:
        query = select(Trade).order_by(Trade.trade_id).limit(limit).offset(offset)
        today = today_provider()
        trades = list(session.scalars(query))
        for trade in trades:
            trade.expired = trade.expired or trade.maturity_date < today
        return trades

    @app.get("/trades/{trade_id}", response_model=TradeRead)
    def get_trade(trade_id: str, session: SessionDependency) -> Trade:
        trade = session.get(Trade, trade_id)
        if trade is None:
            raise HTTPException(status_code=404, detail="Trade not found")
        trade.expired = trade.expired or trade.maturity_date < today_provider()
        return trade

    return app


app = create_app()
