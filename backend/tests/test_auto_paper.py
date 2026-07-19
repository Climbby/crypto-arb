"""Tests for auto paper trader."""

import pytest

from app.db.database import Database
from app.models import Opportunity, Tick, utcnow
from app.paper.auto import AutoPaperTrader
from app.paper.broker import PaperBroker


@pytest.fixture
async def broker(tmp_path):
    db = Database(str(tmp_path / "auto.db"))
    await db.connect()
    b = PaperBroker(db=db, venues=["binance", "kraken"], starting_usdt=10_000.0)
    await b.reset()
    yield b
    await db.close()


def _cross_opp(edge: float = 1.0) -> Opportunity:
    return Opportunity(
        id="BTC/USDT|binance->kraken",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=100.0,
        sell_price=101.0,
        raw_edge_pct=edge,
        net_edge_pct=edge,
        buy_fee_pct=0.0,
        sell_fee_pct=0.0,
        slippage_pct=0.0,
        detected_at=utcnow(),
        executable=True,
        max_notional_usdt=500.0,
    )


@pytest.mark.asyncio
async def test_auto_fills_when_enabled(broker: PaperBroker):
    auto = AutoPaperTrader(
        broker,
        enabled=True,
        notional_usdt=5.0,
        min_net_edge_pct=0.1,
        cooldown_seconds=60.0,
        max_per_scan=1,
    )
    opp = _cross_opp(0.5)
    opp.max_notional_usdt = 5.0
    before = (await broker.portfolio())["realized_pnl_usdt"]
    fills = await auto.maybe_execute(
        [opp],
        fee_map={"binance": 0.0, "kraken": 0.0},
        slippage_bps=0.0,
        scanner_min_edge=0.05,
        ticks=[],
    )
    assert len(fills) == 1
    assert fills[0]["ok"] is True
    assert auto.fills_total == 1
    after = (await broker.portfolio())["realized_pnl_usdt"]
    assert after != before


@pytest.mark.asyncio
async def test_auto_respects_disabled(broker: PaperBroker):
    auto = AutoPaperTrader(broker, enabled=False, notional_usdt=5.0)
    fills = await auto.maybe_execute(
        [_cross_opp()],
        fee_map={"binance": 0.0, "kraken": 0.0},
        slippage_bps=0.0,
        scanner_min_edge=0.05,
        ticks=[],
    )
    assert fills == []


@pytest.mark.asyncio
async def test_auto_cooldown(broker: PaperBroker):
    auto = AutoPaperTrader(
        broker,
        enabled=True,
        notional_usdt=5.0,
        cooldown_seconds=999.0,
        max_per_scan=1,
        min_net_edge_pct=0.0,
    )
    opp = _cross_opp()
    opp.max_notional_usdt = 5.0
    kwargs = dict(
        fee_map={"binance": 0.0, "kraken": 0.0},
        slippage_bps=0.0,
        scanner_min_edge=0.0,
        ticks=[],
    )
    first = await auto.maybe_execute([opp], **kwargs)
    second = await auto.maybe_execute([opp], **kwargs)
    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_auto_skips_non_executable(broker: PaperBroker):
    auto = AutoPaperTrader(broker, enabled=True, notional_usdt=50.0, min_net_edge_pct=0.0)
    opp = _cross_opp()
    opp.executable = False
    fills = await auto.maybe_execute(
        [opp],
        fee_map={"binance": 0.0, "kraken": 0.0},
        slippage_bps=0.0,
        scanner_min_edge=0.0,
        ticks=[],
    )
    assert fills == []


@pytest.mark.asyncio
async def test_auto_triangular(broker: PaperBroker):
    auto = AutoPaperTrader(
        broker,
        enabled=True,
        notional_usdt=100.0,
        min_net_edge_pct=0.0,
        cooldown_seconds=0.0,
    )
    book_ticks = [
        Tick(exchange="binance", symbol="BTC/USDT", bid=100.0, ask=100.0),
        Tick(exchange="binance", symbol="ETH/BTC", bid=0.05, ask=0.05),
        Tick(exchange="binance", symbol="ETH/USDT", bid=6.0, ask=6.0),
    ]
    opp = Opportunity(
        id="tri|binance|USDT>BTC>ETH>USDT",
        symbol="USDT>BTC>ETH>USDT",
        buy_exchange="binance",
        sell_exchange="binance",
        buy_price=100.0,
        sell_price=6.0,
        raw_edge_pct=20.0,
        net_edge_pct=20.0,
        buy_fee_pct=0.0,
        sell_fee_pct=0.0,
        slippage_pct=0.0,
        kind="triangular",
        path="USDT>BTC>ETH>USDT",
        executable=True,
        max_notional_usdt=1000.0,
    )
    fills = await auto.maybe_execute(
        [opp],
        fee_map={"binance": 0.0},
        slippage_bps=0.0,
        scanner_min_edge=0.0,
        ticks=book_ticks,
    )
    assert len(fills) == 1
    assert fills[0]["pnl_usdt"] == pytest.approx(20.0)
