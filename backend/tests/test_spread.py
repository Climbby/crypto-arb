"""Unit tests for fee/slippage-aware spread math."""

from app.engine.spread import (
    bps_to_pct,
    compute_net_edge_pct,
    compute_raw_edge_pct,
    find_opportunities,
    opportunity_id,
)
from app.models import Tick


def test_bps_to_pct():
    assert bps_to_pct(5.0) == 0.05
    assert bps_to_pct(10.0) == 0.1


def test_raw_edge_pct():
    # Buy 100, sell 101 -> 1%
    assert abs(compute_raw_edge_pct(100.0, 101.0) - 1.0) < 1e-9


def test_net_edge_subtracts_fees_and_slippage():
    # raw 1%, fees 0.1% + 0.1% = 0.2%, slippage 5bps*2 = 0.1% -> net 0.7%
    raw, net, buy_fee_pct, sell_fee_pct = compute_net_edge_pct(
        buy_price=100.0,
        sell_price=101.0,
        buy_fee=0.001,
        sell_fee=0.001,
        slippage_bps=5.0,
    )
    assert abs(raw - 1.0) < 1e-9
    assert abs(buy_fee_pct - 0.1) < 1e-9
    assert abs(sell_fee_pct - 0.1) < 1e-9
    assert abs(net - 0.7) < 1e-9


def test_find_opportunities_filters_by_min_edge():
    ticks = [
        Tick(exchange="binance", symbol="BTC/USDT", bid=100.0, ask=100.1),
        Tick(exchange="kraken", symbol="BTC/USDT", bid=101.0, ask=101.1),
    ]
    fee_map = {"binance": 0.001, "kraken": 0.001}
    # Buy binance ask 100.1, sell kraken bid 101.0
    opps = find_opportunities(ticks, fee_map, slippage_bps=5.0, min_net_edge_pct=0.05)
    assert len(opps) >= 1
    best = opps[0]
    assert best.buy_exchange == "binance"
    assert best.sell_exchange == "kraken"
    assert best.net_edge_pct > 0.05


def test_find_opportunities_empty_when_below_threshold():
    ticks = [
        Tick(exchange="binance", symbol="BTC/USDT", bid=100.0, ask=100.05),
        Tick(exchange="kraken", symbol="BTC/USDT", bid=100.1, ask=100.15),
    ]
    # Tiny raw spread, high fees -> filtered out
    fee_map = {"binance": 0.001, "kraken": 0.0026}
    opps = find_opportunities(ticks, fee_map, slippage_bps=5.0, min_net_edge_pct=0.05)
    assert opps == []


def test_opportunity_id():
    assert opportunity_id("BTC/USDT", "binance", "kraken") == "BTC/USDT|binance->kraken"
