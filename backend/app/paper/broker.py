"""Paper trading broker with multi-venue balances."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.db.database import Database
from app.models import Opportunity, utcnow
from app.paper.transfer_realism import delay_seconds_for, withdraw_fee_for


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
        await self.db.clear_equity()
        per_venue = self.starting_usdt / max(len(self.venues), 1)
        for venue in self.venues:
            await self.db.set_balance(venue, "USDT", per_venue)
            for coin, amount in self.seed_coins.items():
                await self.db.set_balance(venue, coin, amount)
        await self.db.record_equity(
            equity_usdt=self.starting_usdt,
            realized_pnl_usdt=0.0,
            usdt_total=self.starting_usdt,
            note="reset",
        )
        return await self.portfolio()

    async def _balance_map(self) -> dict[tuple[str, str], float]:
        rows = await self.db.get_balances()
        return {(r["venue"], r["asset"]): float(r["amount"]) for r in rows}

    async def portfolio(self) -> dict[str, Any]:
        balances = await self.db.get_balances()
        trades = await self.db.list_trades(limit=100)
        transfers = await self.db.list_transfers(limit=50)
        pending = await self.db.list_pending_transfers()
        realized_pnl = await self.db.sum_trade_pnl_usdt()
        by_venue: dict[str, dict[str, float]] = {}
        for row in balances:
            by_venue.setdefault(row["venue"], {})[row["asset"]] = float(row["amount"])
        in_transit: dict[str, float] = {}
        for row in pending:
            asset = str(row["asset"])
            in_transit[asset] = in_transit.get(asset, 0.0) + float(
                row.get("net_amount") if row.get("net_amount") is not None else row["amount"]
            )
        return {
            "balances": balances,
            "by_venue": by_venue,
            "trades": trades,
            "transfers": transfers,
            "pending_transfers": pending,
            "in_transit": in_transit,
            "realized_pnl_usdt": realized_pnl,
            "starting_usdt": self.starting_usdt,
            "note": (
                "Paper mode: fills include modeled fees + slippage; "
                "cross-venue transfers debit immediately, credit after delay, "
                "and burn a withdrawal fee while in transit."
            ),
        }

    async def settle_due_transfers(self) -> list[dict[str, Any]]:
        """Credit destinations for transfers whose arrives_at has passed."""
        now = utcnow()
        due = await self.db.list_due_pending_transfers(now.isoformat())
        settled: list[dict[str, Any]] = []
        for row in due:
            asset = str(row["asset"])
            to_venue = str(row["to_venue"])
            net = float(
                row["net_amount"] if row.get("net_amount") is not None else row["amount"]
            )
            bal = await self._balance_map()
            dest = bal.get((to_venue, asset), 0.0) + net
            await self.db.set_balance(to_venue, asset, dest)
            settled_at = now.isoformat()
            await self.db.mark_transfer_settled(int(row["id"]), settled_at)
            settled.append({**dict(row), "status": "settled", "settled_at": settled_at})
        return settled

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
        return await self._execute_cross(
            opportunity, notional_usdt, fee_map, slippage_bps=slippage_bps
        )

    async def _execute_cross(
        self,
        opportunity: Opportunity,
        notional_usdt: float,
        fee_map: dict[str, float],
        *,
        slippage_bps: float = 5.0,
    ) -> dict[str, Any]:
        buy_fee = fee_map.get(opportunity.buy_exchange, 0.001)
        sell_fee = fee_map.get(opportunity.sell_exchange, 0.001)
        slip = max(0.0, float(slippage_bps)) / 10_000.0

        # Worsen execution vs quoted top-of-book (pay more to buy, receive less to sell)
        buy_price = float(opportunity.buy_price) * (1.0 + slip)
        sell_price = float(opportunity.sell_price) * (1.0 - slip)
        if buy_price <= 0 or sell_price <= 0:
            raise PaperBrokerError("invalid prices after slippage")

        buy_cost = notional_usdt
        quantity = buy_cost / buy_price
        buy_fee_usdt = buy_cost * buy_fee
        total_usdt_out = buy_cost + buy_fee_usdt

        sell_proceeds = quantity * sell_price
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
            buy_price=buy_price,
            sell_price=sell_price,
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
        delayed: bool = True,
        instant: bool = False,
    ) -> dict[str, Any]:
        """
        Move inventory between venues.

        `amount` is what the destination should receive. Source is debited
        amount + withdrawal fee immediately. Destination is credited after a
        realistic delay (unless instant=True for tests).
        """
        if amount <= 0:
            raise PaperBrokerError("amount must be positive")
        if from_venue == to_venue:
            raise PaperBrokerError("from_venue and to_venue must differ")
        if from_venue not in self.venues or to_venue not in self.venues:
            raise PaperBrokerError("unknown venue")

        fee = withdraw_fee_for(asset)
        debit = amount + fee
        bal = await self._balance_map()
        available = bal.get((from_venue, asset), 0.0)
        if available < debit:
            raise PaperBrokerError(
                f"Insufficient {asset} on {from_venue}: need {debit} "
                f"(incl. withdraw fee {fee}), have {available}"
            )

        await self.db.set_balance(from_venue, asset, available - debit)

        use_delay = delayed and not instant
        now = utcnow()
        if use_delay:
            delay_s = delay_seconds_for(asset)
            arrives = (now + timedelta(seconds=delay_s)).isoformat()
            record = await self.db.insert_transfer(
                asset=asset,
                from_venue=from_venue,
                to_venue=to_venue,
                amount=debit,
                delayed=True,
                fee_amount=fee,
                net_amount=amount,
                status="pending",
                arrives_at=arrives,
                settled_at=None,
            )
            note = (
                f"Withdrawn {debit:.6g} {asset} from {from_venue} "
                f"(fee {fee:.6g}). {amount:.6g} arrives on {to_venue} in "
                f"~{delay_s / 60:.0f} min — in transit until then."
            )
        else:
            dest = bal.get((to_venue, asset), 0.0) + amount
            await self.db.set_balance(to_venue, asset, dest)
            record = await self.db.insert_transfer(
                asset=asset,
                from_venue=from_venue,
                to_venue=to_venue,
                amount=debit,
                delayed=False,
                fee_amount=fee,
                net_amount=amount,
                status="settled",
                arrives_at=now.isoformat(),
                settled_at=now.isoformat(),
            )
            note = (
                f"Instant paper transfer (test/debug): credited {amount:.6g} {asset} "
                f"on {to_venue}; fee {fee:.6g} burned."
            )

        return {
            "transfer": record,
            "portfolio": await self.portfolio(),
            "note": note,
        }
