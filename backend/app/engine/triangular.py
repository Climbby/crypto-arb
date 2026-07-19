"""Same-exchange triangular arbitrage detection."""

from __future__ import annotations

from app.engine.spread import bps_to_pct, fee_fraction_to_pct
from app.models import Opportunity, Tick, utcnow

# (path_id, required symbols)
# Simulation is hard-coded per path for correct bid/ask sides.
TRI_PATHS: list[tuple[str, tuple[str, ...]]] = [
    ("USDT>BTC>ETH>USDT", ("BTC/USDT", "ETH/BTC", "ETH/USDT")),
    ("USDT>ETH>BTC>USDT", ("ETH/USDT", "ETH/BTC", "BTC/USDT")),
    ("USDT>BTC>SOL>USDT", ("BTC/USDT", "SOL/BTC", "SOL/USDT")),
    ("USDT>SOL>BTC>USDT", ("SOL/USDT", "SOL/BTC", "BTC/USDT")),
    ("USDT>ETH>SOL>USDT", ("ETH/USDT", "SOL/ETH", "SOL/USDT")),
    ("USDT>SOL>ETH>USDT", ("SOL/USDT", "SOL/ETH", "ETH/USDT")),
]


def triangular_symbols() -> list[str]:
    syms: set[str] = set()
    for _, required in TRI_PATHS:
        syms.update(required)
    # Always keep majors even if only cross-exchange is enabled
    syms.update(("BTC/USDT", "ETH/USDT", "SOL/USDT"))
    return sorted(syms)


def _run_path(path: str, book: dict[str, Tick], fee: float, slip_frac: float) -> float | None:
    """Return ending USDT from 1.0 start, or None if missing books."""
    try:
        if path == "USDT>BTC>ETH>USDT":
            btc_usdt, eth_btc, eth_usdt = book["BTC/USDT"], book["ETH/BTC"], book["ETH/USDT"]
            btc = (1.0 / (btc_usdt.ask * (1 + slip_frac))) * (1 - fee)
            eth = (btc / (eth_btc.ask * (1 + slip_frac))) * (1 - fee)
            return (eth * (eth_usdt.bid * (1 - slip_frac))) * (1 - fee)
        if path == "USDT>ETH>BTC>USDT":
            eth_usdt, eth_btc, btc_usdt = book["ETH/USDT"], book["ETH/BTC"], book["BTC/USDT"]
            eth = (1.0 / (eth_usdt.ask * (1 + slip_frac))) * (1 - fee)
            btc = (eth * (eth_btc.bid * (1 - slip_frac))) * (1 - fee)
            return (btc * (btc_usdt.bid * (1 - slip_frac))) * (1 - fee)
        if path == "USDT>BTC>SOL>USDT":
            btc_usdt, sol_btc, sol_usdt = book["BTC/USDT"], book["SOL/BTC"], book["SOL/USDT"]
            btc = (1.0 / (btc_usdt.ask * (1 + slip_frac))) * (1 - fee)
            sol = (btc / (sol_btc.ask * (1 + slip_frac))) * (1 - fee)
            return (sol * (sol_usdt.bid * (1 - slip_frac))) * (1 - fee)
        if path == "USDT>SOL>BTC>USDT":
            sol_usdt, sol_btc, btc_usdt = book["SOL/USDT"], book["SOL/BTC"], book["BTC/USDT"]
            sol = (1.0 / (sol_usdt.ask * (1 + slip_frac))) * (1 - fee)
            btc = (sol * (sol_btc.bid * (1 - slip_frac))) * (1 - fee)
            return (btc * (btc_usdt.bid * (1 - slip_frac))) * (1 - fee)
        if path == "USDT>ETH>SOL>USDT":
            eth_usdt, sol_eth, sol_usdt = book["ETH/USDT"], book["SOL/ETH"], book["SOL/USDT"]
            eth = (1.0 / (eth_usdt.ask * (1 + slip_frac))) * (1 - fee)
            sol = (eth / (sol_eth.ask * (1 + slip_frac))) * (1 - fee)
            return (sol * (sol_usdt.bid * (1 - slip_frac))) * (1 - fee)
        if path == "USDT>SOL>ETH>USDT":
            sol_usdt, sol_eth, eth_usdt = book["SOL/USDT"], book["SOL/ETH"], book["ETH/USDT"]
            sol = (1.0 / (sol_usdt.ask * (1 + slip_frac))) * (1 - fee)
            eth = (sol * (sol_eth.bid * (1 - slip_frac))) * (1 - fee)
            return (eth * (eth_usdt.bid * (1 - slip_frac))) * (1 - fee)
    except KeyError:
        return None
    return None


def find_triangular_opportunities(
    ticks: list[Tick],
    fee_map: dict[str, float],
    slippage_bps: float,
    min_net_edge_pct: float,
) -> list[Opportunity]:
    by_ex: dict[str, dict[str, Tick]] = {}
    for t in ticks:
        by_ex.setdefault(t.exchange, {})[t.symbol] = t

    slip_frac = bps_to_pct(slippage_bps) / 100.0
    opps: list[Opportunity] = []

    for exchange, book in by_ex.items():
        fee = fee_map.get(exchange, 0.001)
        fee_pct = fee_fraction_to_pct(fee)
        slip_pct = bps_to_pct(slippage_bps) * 3.0
        for path, required in TRI_PATHS:
            if any(s not in book for s in required):
                continue
            end = _run_path(path, book, fee, slip_frac)
            if end is None:
                continue
            net = (end - 1.0) * 100.0
            if net < min_net_edge_pct:
                continue
            first = book[required[0]]
            last = book[required[2]]
            opps.append(
                Opportunity(
                    id=f"tri|{exchange}|{path}",
                    symbol=path,
                    buy_exchange=exchange,
                    sell_exchange=exchange,
                    buy_price=first.ask,
                    sell_price=last.bid,
                    raw_edge_pct=net + fee_pct * 3 + slip_pct,
                    net_edge_pct=net,
                    buy_fee_pct=fee_pct,
                    sell_fee_pct=fee_pct * 2,
                    slippage_pct=slip_pct,
                    detected_at=utcnow(),
                    kind="triangular",
                    path=path,
                )
            )

    opps.sort(key=lambda o: o.net_edge_pct, reverse=True)
    return opps


def simulate_unit_return(
    path: str,
    book: dict[str, Tick],
    fee: float,
    slip_frac: float,
) -> float | None:
    """USDT received per 1 USDT started after fees/slippage, or None if books missing."""
    return _run_path(path, book, fee, slip_frac)


def path_required_symbols(path: str) -> tuple[str, ...] | None:
    for pid, required in TRI_PATHS:
        if pid == path:
            return required
    return None
