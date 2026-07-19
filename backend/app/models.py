"""Shared domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Tick:
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float | None = None
    timestamp: datetime = field(default_factory=utcnow)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": self.mid,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Opportunity:
    id: str
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    raw_edge_pct: float
    net_edge_pct: float
    buy_fee_pct: float
    sell_fee_pct: float
    slippage_pct: float
    detected_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "raw_edge_pct": self.raw_edge_pct,
            "net_edge_pct": self.net_edge_pct,
            "buy_fee_pct": self.buy_fee_pct,
            "sell_fee_pct": self.sell_fee_pct,
            "slippage_pct": self.slippage_pct,
            "detected_at": self.detected_at.isoformat(),
            "theoretical": True,
        }
