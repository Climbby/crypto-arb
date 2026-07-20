"""Equity marking + trade backfill."""

import pytest

from app.db.database import Database
from app.models import Opportunity, Tick, utcnow
from app.paper.broker import PaperBroker
from app.paper.equity import (
    backfill_equity_from_trades,
    mark_equity_usdt,
    recompute_equity_realized_from_trades,
)


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
    db = Database(str(tmp_path / "eq.db"))
    await db.connect()
    b = PaperBroker(db=db, venues=["binance", "kraken"], starting_usdt=10_000.0)
    await b.reset()
    yield b
    await db.close()


@pytest.mark.asyncio
async def test_backfill_from_trades(broker: PaperBroker):
    opp = Opportunity(
        id="BTC/USDT|binance->kraken",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=100.0,
        sell_price=101.0,
        raw_edge_pct=1.0,
        net_edge_pct=0.7,
        buy_fee_pct=0.0,
        sell_fee_pct=0.0,
        slippage_pct=0.0,
        detected_at=utcnow(),
    )
    await broker.execute(opp, notional_usdt=5.0, fee_map={"binance": 0.0, "kraken": 0.0})
    await broker.db.clear_equity()
    await broker.db.record_equity(
        equity_usdt=10_050.0,
        realized_pnl_usdt=5.0,
        usdt_total=10_000.0,
        note="late",
        recorded_at="2099-01-01T00:00:00+00:00",
    )
    ticks = [
        Tick(exchange="binance", symbol="BTC/USDT", bid=100.0, ask=100.0),
        Tick(exchange="binance", symbol="ETH/USDT", bid=2000.0, ask=2000.0),
        Tick(exchange="binance", symbol="SOL/USDT", bid=100.0, ask=100.0),
    ]
    portfolio = await broker.portfolio()
    written = await backfill_equity_from_trades(
        broker.db,
        by_venue=portfolio["by_venue"],
        ticks=ticks,
        realized_pnl_usdt=float(portfolio["realized_pnl_usdt"]),
    )
    assert written >= 2
    cur = await broker.db.conn.execute(
        "SELECT note FROM paper_equity WHERE note LIKE 'backfill%' ORDER BY id ASC"
    )
    notes = [r["note"] for r in await cur.fetchall()]
    assert "backfill:start" in notes
    assert "backfill:trade" in notes
    # Chart API hides backfill; raw rows must still exist for one-shot reconstruction
    chart = await broker.db.list_equity(limit=50)
    assert all(not str(r.get("note") or "").startswith("backfill") for r in chart)


@pytest.mark.asyncio
async def test_recompute_equity_realized_from_trades(broker: PaperBroker):
    await broker.db.clear_equity()
    await broker.db.insert_trade(
        opp_id="a",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        quantity=0.01,
        buy_price=100.0,
        sell_price=101.0,
        net_edge_pct=0.5,
        pnl_usdt=10.0,
    )
    # Force wrong executed_at ordering via direct inserts with timestamps
    await broker.db.conn.execute("DELETE FROM paper_trades")
    await broker.db.conn.commit()
    await broker.db.conn.execute(
        """
        INSERT INTO paper_trades
        (opp_id, symbol, buy_exchange, sell_exchange, quantity,
         buy_price, sell_price, net_edge_pct, pnl_usdt, executed_at)
        VALUES
        ('a','BTC/USDT','binance','kraken',0.01,100,101,0.5,10.0,'2026-01-01T00:00:00+00:00'),
        ('b','BTC/USDT','binance','kraken',0.01,100,101,0.5,5.0,'2026-01-01T01:00:00+00:00')
        """
    )
    await broker.db.conn.commit()
    await broker.db.record_equity(
        equity_usdt=10000.0,
        realized_pnl_usdt=0.0,
        usdt_total=10000.0,
        note="heartbeat",
        recorded_at="2026-01-01T00:30:00+00:00",
    )
    await broker.db.record_equity(
        equity_usdt=10000.0,
        realized_pnl_usdt=1.0,  # wrong rolling-window value
        usdt_total=10000.0,
        note="heartbeat",
        recorded_at="2026-01-01T02:00:00+00:00",
    )
    n = await recompute_equity_realized_from_trades(broker.db)
    assert n == 2
    rows = await broker.db.list_equity(limit=10)
    assert rows[0]["realized_pnl_usdt"] == pytest.approx(10.0)
    assert rows[1]["realized_pnl_usdt"] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_auto_rebalance_moves_usdt(tmp_path):
    from app.paper.rebalance import AutoRebalancer

    db = Database(str(tmp_path / "rebal.db"))
    await db.connect()
    broker = PaperBroker(
        db=db, venues=["binance", "kraken", "coinbase"], starting_usdt=9_000.0
    )
    await broker.reset()
    await broker.transfer(
        asset="USDT",
        from_venue="kraken",
        to_venue="binance",
        amount=2900.0,
        instant=True,
    )

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
    donor_before = (await broker.portfolio())["by_venue"]["binance"]["USDT"]
    transfers = await rebalancer.maybe_rebalance(
        [opp],
        fee_map={"binance": 0.001, "kraken": 0.0026},
        min_edge=0.05,
    )
    assert len(transfers) >= 1
    usdt_moves = [t for t in transfers if t["asset"] == "USDT" and t["to_venue"] == "kraken"]
    assert len(usdt_moves) == 1
    portfolio = await broker.portfolio()
    # Destination not credited until settle; funds are in transit
    assert portfolio["by_venue"]["kraken"]["USDT"] == pytest.approx(before)
    assert portfolio["by_venue"]["binance"]["USDT"] < donor_before
    assert portfolio["in_transit"].get("USDT", 0) > 0
    assert usdt_moves[0]["transfer"]["status"] == "pending"
    await db.close()


@pytest.mark.asyncio
async def test_equity_recorded_on_reset(broker: PaperBroker):
    rows = await broker.db.list_equity(limit=10)
    assert len(rows) >= 1
    assert rows[0]["note"] == "reset"
