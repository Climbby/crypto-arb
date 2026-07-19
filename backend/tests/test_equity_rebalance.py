"""Tests for equity marking and auto-rebalance."""

import pytest

from app.db.database import Database
from app.models import Opportunity, Tick, utcnow
from app.paper.broker import PaperBroker
from app.paper.equity import mark_equity_usdt
from app.paper.rebalance import AutoRebalancer


def test_mark_equity_cash_and_coins():
    by_venue = {
        "binance": {"USDT": 1000.0, "BTC": 0.1},
        "kraken": {"USDT": 500.0},
    }
    ticks = [Tick(exchange="binance", symbol="BTC/USDT", bid=50_000.0, ask=50_000.0)]
    equity, cash = mark_equity_usdt(by_venue, ticks)
    assert cash == pytest.approx(1500.0)
    assert equity == pytest.approx(1500.0 + 5000.0)


@pytest.fixture
async def broker(tmp_path):
    db = Database(str(tmp_path / "rebal.db"))
    await db.connect()
    b = PaperBroker(db=db, venues=["binance", "kraken", "coinbase"], starting_usdt=9_000.0)
    await b.reset()
    # Drain kraken USDT so buy-side is blocked
    await b.transfer(asset="USDT", from_venue="kraken", to_venue="binance", amount=2900.0)
    yield b
    await db.close()


@pytest.mark.asyncio
async def test_auto_rebalance_moves_usdt(broker: PaperBroker):
    rebalancer = AutoRebalancer(
        broker,
        enabled=True,
        notional_usdt=100.0,
        cooldown_seconds=0.0,
        usdt_chunk=500.0,
        leave_usdt_reserve=50.0,
    )
    opp = Opportunity(
        id="BTC/USDT|kraken->binance",
        symbol="BTC/USDT",
        buy_exchange="kraken",
        sell_exchange="binance",
        buy_price=100.0,
        sell_price=101.0,
        raw_edge_pct=1.0,
        net_edge_pct=0.5,
        buy_fee_pct=0.1,
        sell_fee_pct=0.1,
        slippage_pct=0.1,
        detected_at=utcnow(),
        executable=False,
        inventory_note="low USDT on kraken",
        max_notional_usdt=0.0,
    )
    before = (await broker.portfolio())["by_venue"]["kraken"]["USDT"]
    transfers = await rebalancer.maybe_rebalance(
        [opp],
        fee_map={"binance": 0.001, "kraken": 0.0026},
        min_edge=0.05,
    )
    assert len(transfers) >= 1
    usdt_moves = [t for t in transfers if t["asset"] == "USDT" and t["to_venue"] == "kraken"]
    assert len(usdt_moves) == 1
    after = (await broker.portfolio())["by_venue"]["kraken"]["USDT"]
    assert after > before


@pytest.mark.asyncio
async def test_equity_recorded_on_reset(broker: PaperBroker):
    rows = await broker.db.list_equity(limit=10)
    assert len(rows) >= 1
    assert rows[0]["note"] == "reset"
