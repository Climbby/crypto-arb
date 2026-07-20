"""Paper broker tests using in-memory temp SQLite."""

import pytest

from app.db.database import Database
from app.models import Opportunity, utcnow
from app.paper.broker import PaperBroker, PaperBrokerError


@pytest.fixture
async def broker(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    b = PaperBroker(db=db, venues=["binance", "kraken"], starting_usdt=10_000.0)
    await b.reset()
    yield b
    await db.close()


@pytest.mark.asyncio
async def test_seed_balances(broker: PaperBroker):
    portfolio = await broker.portfolio()
    assert abs(portfolio["by_venue"]["binance"]["USDT"] - 5000.0) < 1e-6
    assert abs(portfolio["by_venue"]["kraken"]["USDT"] - 5000.0) < 1e-6
    assert portfolio["by_venue"]["binance"]["BTC"] > 0


@pytest.mark.asyncio
async def test_execute_and_pnl(broker: PaperBroker):
    opp = Opportunity(
        id="BTC/USDT|binance->kraken",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=100.0,
        sell_price=101.0,
        raw_edge_pct=1.0,
        net_edge_pct=0.7,
        buy_fee_pct=0.1,
        sell_fee_pct=0.1,
        slippage_pct=0.1,
        detected_at=utcnow(),
    )
    fee_map = {"binance": 0.001, "kraken": 0.001}
    # Seed BTC is 0.05 — keep notional within inventory
    result = await broker.execute(opp, notional_usdt=5.0, fee_map=fee_map, slippage_bps=0.0)
    trade = result["trade"]
    assert trade["quantity"] == pytest.approx(0.05)
    assert trade["pnl_usdt"] > 0
    assert len(result["portfolio"]["trades"]) == 1
    assert result["portfolio"]["realized_pnl_usdt"] == pytest.approx(trade["pnl_usdt"])


@pytest.mark.asyncio
async def test_realized_pnl_is_lifetime(broker: PaperBroker):
    """Realized PnL must sum all trades, not only the last-100 list window."""
    for i in range(105):
        await broker.db.insert_trade(
            opp_id=f"t-{i}",
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="kraken",
            quantity=0.01,
            buy_price=100.0,
            sell_price=101.0,
            net_edge_pct=0.5,
            pnl_usdt=1.0 if i < 5 else 0.01,
        )
    portfolio = await broker.portfolio()
    assert len(portfolio["trades"]) == 100
    # 5 * 1.0 + 100 * 0.01 = 6.0 — lifetime includes the 5 large early trades
    assert portfolio["realized_pnl_usdt"] == pytest.approx(6.0)
    # Last-100 window alone would be 100 * 0.01 = 1.0
    window = sum(float(t["pnl_usdt"]) for t in portfolio["trades"])
    assert window == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_insufficient_funds(broker: PaperBroker):
    opp = Opportunity(
        id="BTC/USDT|binance->kraken",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=100.0,
        sell_price=101.0,
        raw_edge_pct=1.0,
        net_edge_pct=0.7,
        buy_fee_pct=0.1,
        sell_fee_pct=0.1,
        slippage_pct=0.1,
        detected_at=utcnow(),
    )
    with pytest.raises(PaperBrokerError):
        await broker.execute(opp, notional_usdt=1_000_000.0, fee_map={"binance": 0.001, "kraken": 0.001})


@pytest.mark.asyncio
async def test_transfer(broker: PaperBroker):
    result = await broker.transfer(
        asset="USDT",
        from_venue="binance",
        to_venue="kraken",
        amount=100.0,
        instant=True,
    )
    assert result["transfer"]["status"] == "settled"
    assert result["transfer"]["fee_amount"] == pytest.approx(1.0)
    # Debit 101 (100 + 1 fee); credit 100
    assert result["portfolio"]["by_venue"]["binance"]["USDT"] == pytest.approx(4899.0)
    assert result["portfolio"]["by_venue"]["kraken"]["USDT"] == pytest.approx(5100.0)


@pytest.mark.asyncio
async def test_transfer_pending_then_settle(broker: PaperBroker):
    result = await broker.transfer(
        asset="USDT",
        from_venue="binance",
        to_venue="kraken",
        amount=50.0,
        delayed=True,
    )
    assert result["transfer"]["status"] == "pending"
    assert result["portfolio"]["by_venue"]["binance"]["USDT"] == pytest.approx(4949.0)
    # Not credited yet
    assert result["portfolio"]["by_venue"]["kraken"]["USDT"] == pytest.approx(5000.0)
    assert result["portfolio"]["in_transit"]["USDT"] == pytest.approx(50.0)

    # Force due by rewriting arrives_at
    tid = int(result["transfer"]["id"])
    await broker.db.conn.execute(
        "UPDATE paper_transfers SET arrives_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", tid),
    )
    await broker.db.conn.commit()
    settled = await broker.settle_due_transfers()
    assert len(settled) == 1
    portfolio = await broker.portfolio()
    assert portfolio["by_venue"]["kraken"]["USDT"] == pytest.approx(5050.0)
    assert portfolio.get("in_transit", {}).get("USDT", 0) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_execute_triangular(broker: PaperBroker):
    from app.models import Tick

    book = {
        "BTC/USDT": Tick(exchange="binance", symbol="BTC/USDT", bid=100.0, ask=100.0),
        "ETH/BTC": Tick(exchange="binance", symbol="ETH/BTC", bid=0.05, ask=0.05),
        "ETH/USDT": Tick(exchange="binance", symbol="ETH/USDT", bid=6.0, ask=6.0),
    }
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
        detected_at=utcnow(),
        kind="triangular",
        path="USDT>BTC>ETH>USDT",
    )
    before = (await broker.portfolio())["by_venue"]["binance"]["USDT"]
    result = await broker.execute(
        opp,
        notional_usdt=100.0,
        fee_map={"binance": 0.0},
        ticks_for_venue=book,
        slippage_bps=0.0,
    )
    after = result["portfolio"]["by_venue"]["binance"]["USDT"]
    assert result["trade"]["pnl_usdt"] == pytest.approx(20.0)
    assert after == pytest.approx(before + 20.0)
