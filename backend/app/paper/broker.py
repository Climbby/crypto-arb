"""Paper trading broker with multi-venue balances."""

from __future__ import annotations

from typing import Any

from app.db.database import Database
from app.models import Opportunity


class PaperBrokerError(Exception):
    pass


class PaperBroker:
    def __init__(
        self,
        db: Database,
        venues: list[str],
        starting_usdt: float = 10_000.0,
        seed_coins: dict[str, float] | None = None,
    ) -> None:
        self.db = db
        self.venues = venues
        self.starting_usdt = starting_usdt
        # Optional per-venue coin inventory so sell-side can execute without transfer
        self.seed_coins = seed_coins or {"BTC": 0.05, "ETH": 1.0, "SOL": 20.0}

    async def ensure_seeded(self) -> None:
        balances = await self.db.get_balances()
        if balances:
            return
        await self.reset()

    async def reset(self) -> dict[str, Any]:
        await self.db.clear_balances()
        await self.db.clear_trades()
        await self.db.clear_transfers()
        per_venue = self.starting_usdt / max(len(self.venues), 1)
        for venue in self.venues:
            await self.db.set_balance(venue, "USDT", per_venue)
            for coin, amount in self.seed_coins.items():
                await self.db.set_balance(venue, coin, amount)
        return await self.portfolio()

    async def _balance_map(self) -> dict[tuple[str, str], float]:
        rows = await self.db.get_balances()
        return {(r["venue"], r["asset"]): float(r["amount"]) for r in rows}

    async def portfolio(self) -> dict[str, Any]:
        balances = await self.db.get_balances()
        trades = await self.db.list_trades(limit=100)
        transfers = await self.db.list_transfers(limit=50)
        realized_pnl = sum(float(t["pnl_usdt"]) for t in trades)
        by_venue: dict[str, dict[str, float]] = {}
        for row in balances:
            by_venue.setdefault(row["venue"], {})[row["asset"]] = float(row["amount"])
        return {
            "balances": balances,
            "by_venue": by_venue,
            "trades": trades,
            "transfers": transfers,
            "realized_pnl_usdt": realized_pnl,
            "starting_usdt": self.starting_usdt,
            "note": (
                "Paper fills are theoretical: no latency, depth, or transfer delay "
                "unless you use the rebalance helper with delayed=true (flag only)."
            ),
        }

    async def execute(
        self,
        opportunity: Opportunity,
        notional_usdt: float,
        fee_map: dict[str, float],
        *,
        ticks_for_venue: dict[str, Any] | None = None,
        slippage_bps: float = 5.0,
    ) -> dict[str, Any]:
        if notional_usdt <= 0:
            raise PaperBrokerError("notional_usdt must be positive")
        if opportunity.kind == "triangular":
            from app.models import Tick

            if not ticks_for_venue:
                raise PaperBrokerError("triangular exec requires live venue ticks")
            book = {
                sym: tick
                for sym, tick in ticks_for_venue.items()
                if isinstance(tick, Tick)
            }
            return await self._execute_triangular(
                opportunity, notional_usdt, fee_map, book, slippage_bps
            )
        return await self._execute_cross(opportunity, notional_usdt, fee_map)

    async def _execute_cross(
        self,
        opportunity: Opportunity,
        notional_usdt: float,
        fee_map: dict[str, float],
    ) -> dict[str, Any]:
        buy_fee = fee_map.get(opportunity.buy_exchange, 0.001)
        sell_fee = fee_map.get(opportunity.sell_exchange, 0.001)

        # Buy leg: spend USDT on buy exchange at ask
        buy_cost = notional_usdt
        quantity = buy_cost / opportunity.buy_price
        buy_fee_usdt = buy_cost * buy_fee
        total_usdt_out = buy_cost + buy_fee_usdt

        # Sell leg: sell quantity at bid, pay fee on proceeds
        sell_proceeds = quantity * opportunity.sell_price
        sell_fee_usdt = sell_proceeds * sell_fee
        net_usdt_in = sell_proceeds - sell_fee_usdt

        bal = await self._balance_map()
        buy_usdt = bal.get((opportunity.buy_exchange, "USDT"), 0.0)
        base = opportunity.symbol.split("/")[0]
        sell_coin = bal.get((opportunity.sell_exchange, base), 0.0)

        if buy_usdt < total_usdt_out:
            raise PaperBrokerError(
                f"Insufficient USDT on {opportunity.buy_exchange}: "
                f"need {total_usdt_out:.4f}, have {buy_usdt:.4f}"
            )
        if sell_coin < quantity:
            raise PaperBrokerError(
                f"Insufficient {base} on {opportunity.sell_exchange}: "
                f"need {quantity:.8f}, have {sell_coin:.8f}. "
                "Use paper transfer to rebalance inventory."
            )

        # Apply: buy venue loses USDT, gains base; sell venue loses base, gains USDT
        new_buy_usdt = buy_usdt - total_usdt_out
        new_buy_coin = bal.get((opportunity.buy_exchange, base), 0.0) + quantity
        new_sell_coin = sell_coin - quantity
        new_sell_usdt = bal.get((opportunity.sell_exchange, "USDT"), 0.0) + net_usdt_in

        await self.db.set_balance(opportunity.buy_exchange, "USDT", new_buy_usdt)
        await self.db.set_balance(opportunity.buy_exchange, base, new_buy_coin)
        await self.db.set_balance(opportunity.sell_exchange, base, new_sell_coin)
        await self.db.set_balance(opportunity.sell_exchange, "USDT", new_sell_usdt)

        pnl = net_usdt_in - total_usdt_out
        trade = await self.db.insert_trade(
            opp_id=opportunity.id,
            symbol=opportunity.symbol,
            buy_exchange=opportunity.buy_exchange,
            sell_exchange=opportunity.sell_exchange,
            quantity=quantity,
            buy_price=opportunity.buy_price,
            sell_price=opportunity.sell_price,
            net_edge_pct=opportunity.net_edge_pct,
            pnl_usdt=pnl,
        )
        return {"trade": trade, "portfolio": await self.portfolio()}

    async def _execute_triangular(
        self,
        opportunity: Opportunity,
        notional_usdt: float,
        fee_map: dict[str, float],
        book: dict[str, Any],
        slippage_bps: float,
    ) -> dict[str, Any]:
        from app.engine.spread import bps_to_pct
        from app.engine.triangular import path_required_symbols, simulate_unit_return

        path = opportunity.path or opportunity.symbol
        venue = opportunity.buy_exchange
        required = path_required_symbols(path)
        if required is None:
            raise PaperBrokerError(f"Unknown triangular path: {path}")
        missing = [s for s in required if s not in book]
        if missing:
            raise PaperBrokerError(f"Missing live ticks for {', '.join(missing)} on {venue}")

        fee = fee_map.get(venue, 0.001)
        slip_frac = bps_to_pct(slippage_bps) / 100.0
        unit = simulate_unit_return(path, book, fee, slip_frac)
        if unit is None or unit <= 0:
            raise PaperBrokerError("Could not simulate triangular path with current books")

        bal = await self._balance_map()
        usdt = bal.get((venue, "USDT"), 0.0)
        if usdt < notional_usdt:
            raise PaperBrokerError(
                f"Insufficient USDT on {venue}: need {notional_usdt:.4f}, have {usdt:.4f}"
            )

        end_usdt = notional_usdt * unit
        pnl = end_usdt - notional_usdt
        await self.db.set_balance(venue, "USDT", usdt - notional_usdt + end_usdt)

        trade = await self.db.insert_trade(
            opp_id=opportunity.id,
            symbol=path,
            buy_exchange=venue,
            sell_exchange=venue,
            quantity=notional_usdt,
            buy_price=opportunity.buy_price,
            sell_price=opportunity.sell_price,
            net_edge_pct=opportunity.net_edge_pct,
            pnl_usdt=pnl,
        )
        return {
            "trade": trade,
            "portfolio": await self.portfolio(),
            "note": (
                f"Triangular paper fill on {venue}: {path}. "
                f"Spent {notional_usdt:.4f} USDT → {end_usdt:.4f} USDT "
                f"(unit return {unit:.6f}). Intermediate coin legs are simulated, not inventory."
            ),
        }

    async def transfer(
        self,
        *,
        asset: str,
        from_venue: str,
        to_venue: str,
        amount: float,
        delayed: bool = False,
    ) -> dict[str, Any]:
        if amount <= 0:
            raise PaperBrokerError("amount must be positive")
        if from_venue == to_venue:
            raise PaperBrokerError("from_venue and to_venue must differ")
        if from_venue not in self.venues or to_venue not in self.venues:
            raise PaperBrokerError("unknown venue")

        bal = await self._balance_map()
        available = bal.get((from_venue, asset), 0.0)
        if available < amount:
            raise PaperBrokerError(
                f"Insufficient {asset} on {from_venue}: need {amount}, have {available}"
            )

        await self.db.set_balance(from_venue, asset, available - amount)
        dest = bal.get((to_venue, asset), 0.0) + amount
        await self.db.set_balance(to_venue, asset, dest)
        record = await self.db.insert_transfer(
            asset=asset,
            from_venue=from_venue,
            to_venue=to_venue,
            amount=amount,
            delayed=delayed,
        )
        return {
            "transfer": record,
            "portfolio": await self.portfolio(),
            "note": (
                "Transfer applied instantly in paper mode. "
                "delayed=true is a flag only — real withdrawals are out of scope for v1."
                if delayed
                else "Transfer applied instantly in paper mode."
            ),
        }
