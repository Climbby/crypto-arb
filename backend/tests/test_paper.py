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
    result = await broker.execute(opp, notional_usdt=5.0, fee_map=fee_map)
    trade = result["trade"]
    assert trade["quantity"] == pytest.approx(0.05)
    assert trade["pnl_usdt"] > 0
    assert len(result["portfolio"]["trades"]) == 1


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
        asset="USDT", from_venue="binance", to_venue="kraken", amount=100.0, delayed=True
    )
    assert result["transfer"]["delayed"] is True
    assert result["portfolio"]["by_venue"]["binance"]["USDT"] == pytest.approx(4900.0)
    assert result["portfolio"]["by_venue"]["kraken"]["USDT"] == pytest.approx(5100.0)


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
