from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from trade_store.database import Base


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_trades_positive_version"),
        CheckConstraint(
            "length(trim(trade_id)) > 0", name="ck_trades_nonempty_trade_id"
        ),
        CheckConstraint(
            "length(trade_id) <= 64", name="ck_trades_trade_id_max_length"
        ),
        CheckConstraint(
            "length(trim(counterparty_id)) > 0",
            name="ck_trades_nonempty_counterparty_id",
        ),
        CheckConstraint(
            "length(counterparty_id) <= 64",
            name="ck_trades_counterparty_id_max_length",
        ),
        CheckConstraint(
            "length(trim(portfolio_id)) > 0",
            name="ck_trades_nonempty_portfolio_id",
        ),
        CheckConstraint(
            "length(portfolio_id) <= 64",
            name="ck_trades_portfolio_id_max_length",
        ),
        Index("ix_trades_expiry", "expired", "maturity_date"),
    )

    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    counterparty_id: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_date: Mapped[date] = mapped_column(Date, nullable=False)
    expired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
