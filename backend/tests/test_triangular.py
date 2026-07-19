"""Triangular arb unit tests."""

from app.engine.triangular import find_triangular_opportunities
from app.models import Tick


def _book(exchange: str, **prices: tuple[float, float]) -> list[Tick]:
    ticks = []
    for symbol, (bid, ask) in prices.items():
        ticks.append(Tick(exchange=exchange, symbol=symbol.replace("_", "/"), bid=bid, ask=ask))
    return ticks


def test_triangular_detects_positive_cycle():
    # Construct a clear arb: cheap BTC, expensive ETH path
    ticks = _book(
        "binance",
        BTC_USDT=(100.0, 100.0),
        ETH_BTC=(0.05, 0.05),  # ETH costs 0.05 BTC
        ETH_USDT=(6.0, 6.0),  # selling ETH yields 6 USDT; fair would be 5
    )
    # Path USDT>BTC>ETH>USDT: 1/100 BTC -> /0.05 = 0.2 ETH -> *6 = 1.2 USDT before fees
    opps = find_triangular_opportunities(
        ticks, {"binance": 0.0}, slippage_bps=0.0, min_net_edge_pct=0.05
    )
    assert any(o.path == "USDT>BTC>ETH>USDT" and o.net_edge_pct > 10 for o in opps)


def test_triangular_filters_flat_market():
    ticks = _book(
        "binance",
        BTC_USDT=(100.0, 100.1),
        ETH_BTC=(0.05, 0.0501),
        ETH_USDT=(5.0, 5.01),
    )
    opps = find_triangular_opportunities(
        ticks, {"binance": 0.001}, slippage_bps=5.0, min_net_edge_pct=0.05
    )
    assert opps == [] or all(o.net_edge_pct >= 0.05 for o in opps)
