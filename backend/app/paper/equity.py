"""Mark-to-market paper equity from balances + live ticks."""

from __future__ import annotations

from app.models import Tick

MAJOR_USDT = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def mid_prices_usdt(ticks: list[Tick]) -> dict[str, float]:
    """Best-effort mid USD(T) prices keyed by base asset (BTC, ETH, SOL)."""
    prices: dict[str, float] = {}
    # Prefer later ticks; still fine if multiple venues overwrite
    for t in ticks:
        if t.symbol not in MAJOR_USDT:
            continue
        if t.mid <= 0:
            continue
        base = t.symbol.split("/")[0]
        prices[base] = t.mid
    return prices


def mark_equity_usdt(
    by_venue: dict[str, dict[str, float]],
    ticks: list[Tick],
) -> tuple[float, float]:
    """
    Return (total_equity_usdt, cash_usdt_only).

    Coins are marked at mid of */USDT books. Unknown assets are ignored.
    """
    px = mid_prices_usdt(ticks)
    equity = 0.0
    cash = 0.0
    for assets in by_venue.values():
        for asset, amount in assets.items():
            amt = float(amount)
            if asset == "USDT":
                equity += amt
                cash += amt
            elif asset in px:
                equity += amt * px[asset]
    return equity, cash
