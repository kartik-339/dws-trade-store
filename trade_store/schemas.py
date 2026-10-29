from datetime import date
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TradeCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "trade_id": "T1001",
                    "version": 1,
                    "counterparty_id": "CP-1",
                    "portfolio_id": "B1",
                    "maturity_date": "2099-12-31",
                }
            ]
        },
    )

    trade_id: str = Field(min_length=1, max_length=64, strict=True)
    version: int = Field(gt=0, strict=True)
    counterparty_id: str = Field(min_length=1, max_length=64, strict=True)
    portfolio_id: str = Field(min_length=1, max_length=64, strict=True)
    maturity_date: date
    created_date: date | None = None

    @field_validator("trade_id", "counterparty_id", "portfolio_id")
    @classmethod
    def reject_schema_placeholder(cls, value: str) -> str:
        if value.casefold() == "string":
            raise ValueError(
                "replace the example placeholder with a real identifier"
            )
        return value

    @field_validator("maturity_date", "created_date", mode="before")
    @classmethod
    def require_iso_calendar_date(cls, value: Any) -> date:
        if not isinstance(value, str) or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
        ) is None:
            raise ValueError("date must use YYYY-MM-DD format")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("date must be a valid calendar date") from error


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: str
    version: int
    counterparty_id: str
    portfolio_id: str
    maturity_date: date
    created_date: date
    expired: bool
