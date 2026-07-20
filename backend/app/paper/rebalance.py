"""Auto-rebalance paper inventory across venues when edges are blocked."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.models import Opportunity
from app.paper.broker import PaperBroker, PaperBrokerError

logger = logging.getLogger(__name__)


class AutoRebalancer:
    """
    When an attractive edge is blocked by inventory, move paper funds/coins
    from the richest donor venue to the venue that needs them.

    Also maintains light coin floors so a drained sell venue (e.g. Kraken)
    gets topped up before the next edge appears.
    """

    def __init__(
        self,
        broker: PaperBroker,
        *,
        enabled: bool = True,
        notional_usdt: float = 100.0,
        cooldown_seconds: float = 20.0,
        max_transfers_per_scan: int = 4,
        usdt_chunk: float = 500.0,
        leave_usdt_reserve: float = 50.0,
        coin_floors: dict[str, float] | None = None,
    ) -> None:
        self.broker = broker
        self.enabled = enabled
        self.notional_usdt = notional_usdt
        self.cooldown_seconds = cooldown_seconds
        self.max_transfers_per_scan = max_transfers_per_scan
        self.usdt_chunk = usdt_chunk
        self.leave_usdt_reserve = leave_usdt_reserve
        # Minimum coin balances to keep per venue (proactive top-up)
        self.coin_floors = coin_floors or {"BTC": 0.02, "ETH": 0.4, "SOL": 8.0}
        self._last: dict[str, float] = {}
        self.transfers_total = 0
        self.last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "notional_usdt": self.notional_usdt,
            "cooldown_seconds": self.cooldown_seconds,
            "max_transfers_per_scan": self.max_transfers_per_scan,
            "usdt_chunk": self.usdt_chunk,
            "coin_floors": self.coin_floors,
            "transfers_total": self.transfers_total,
            "last_result": self.last_result,
        }

    def _cooled(self, key: str, now: float) -> bool:
        return now - self._last.get(key, 0.0) < self.cooldown_seconds

    async def maybe_rebalance(
        self,
        opportunities: list[Opportunity],
        *,
        fee_map: dict[str, float],
        min_edge: float,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        now = time.monotonic()
        blocked = [
            o
            for o in opportunities
            if o.executable is False and o.net_edge_pct >= min_edge
        ]
        blocked.sort(key=lambda o: o.net_edge_pct, reverse=True)

        portfolio = await self.broker.portfolio()
        by_venue: dict[str, dict[str, float]] = portfolio.get("by_venue", {})
        done: list[dict[str, Any]] = []

        # 1) Reactive: unblock attractive edges
        for opp in blocked:
            if len(done) >= self.max_transfers_per_scan:
                break
            needs = self._needs(opp, by_venue, fee_map)
            for asset, to_venue, amount in needs:
                if len(done) >= self.max_transfers_per_scan:
                    break
                moved = await self._try_transfer(
                    by_venue, asset, to_venue, amount, now, for_opp=opp
                )
                if moved is None:
                    continue
                by_venue, payload = moved
                done.append(payload)

        # 2) Proactive: top up venues below coin floors from surplus donors
        if len(done) < self.max_transfers_per_scan:
            floor_moves = await self._top_up_floors(by_venue, now, budget=self.max_transfers_per_scan - len(done))
            done.extend(floor_moves)

        if not done and blocked:
            self.last_result = {
                "ok": False,
                "reason": f"{len(blocked)} blocked edge(s); no donor inventory available",
                "at": time.time(),
            }
        return done

    async def _top_up_floors(
        self,
        by_venue: dict[str, dict[str, float]],
        now: float,
        *,
        budget: int,
    ) -> list[dict[str, Any]]:
        done: list[dict[str, Any]] = []
        for venue, assets in list(by_venue.items()):
            if len(done) >= budget:
                break
            for coin, floor in self.coin_floors.items():
                if len(done) >= budget:
                    break
                have = float(assets.get(coin, 0.0))
                if have >= floor:
                    continue
                need = floor - have
                moved = await self._try_transfer(
                    by_venue, coin, venue, need, now, for_opp=None
                )
                if moved is None:
                    continue
                by_venue, payload = moved
                payload["reason"] = f"floor top-up {coin} on {venue}"
                done.append(payload)
        return done

    async def _try_transfer(
        self,
        by_venue: dict[str, dict[str, float]],
        asset: str,
        to_venue: str,
        amount: float,
        now: float,
        *,
        for_opp: Opportunity | None,
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]] | None:
        key = f"{asset}->{to_venue}"
        if self._cooled(key, now):
            return None
        donor = self._richest(by_venue, asset, exclude=to_venue)
        if donor is None:
            return None
        available = float(by_venue.get(donor, {}).get(asset, 0.0))
        if asset == "USDT":
            send = min(amount, available - self.leave_usdt_reserve, self.usdt_chunk)
        else:
            # Leave donor above its own floor when possible
            donor_floor = float(self.coin_floors.get(asset, 0.0))
            spare = max(0.0, available - donor_floor)
            send = min(amount, spare if spare > 0 else available * 0.5)
        if send < (1.0 if asset == "USDT" else 1e-6):
            return None
        try:
            result = await self.broker.transfer(
                asset=asset,
                from_venue=donor,
                to_venue=to_venue,
                amount=send,
                delayed=True,
            )
        except PaperBrokerError as exc:
            logger.info("Auto rebalance skip %s: %s", key, exc)
            self.last_result = {
                "ok": False,
                "reason": str(exc),
                "at": time.time(),
            }
            return None

        self._last[key] = now
        self.transfers_total += 1
        by_venue = result["portfolio"].get("by_venue", by_venue)
        payload: dict[str, Any] = {
            "ok": True,
            "asset": asset,
            "from_venue": donor,
            "to_venue": to_venue,
            "amount": send,
            "for_opp": for_opp.id if for_opp else None,
            "net_edge_pct": for_opp.net_edge_pct if for_opp else None,
            "transfer": result.get("transfer"),
            "at": time.time(),
        }
        self.last_result = payload
        logger.info(
            "Auto rebalance %s %.6f %s → %s%s",
            asset,
            send,
            donor,
            to_venue,
            f" (for {for_opp.id})" if for_opp else " (floor)",
        )
        return by_venue, payload

    def _needs(
        self,
        opp: Opportunity,
        by_venue: dict[str, dict[str, float]],
        fee_map: dict[str, float],
    ) -> list[tuple[str, str, float]]:
        """Return list of (asset, to_venue, amount_needed)."""
        needs: list[tuple[str, str, float]] = []
        notional = self.notional_usdt

        if opp.kind == "triangular":
            fee = fee_map.get(opp.buy_exchange, 0.001)
            want = notional * (1 + fee) * 1.05
            have = float(by_venue.get(opp.buy_exchange, {}).get("USDT", 0.0))
            if have < want:
                needs.append(("USDT", opp.buy_exchange, want - have))
            return needs

        base = opp.symbol.split("/")[0]
        buy_fee = fee_map.get(opp.buy_exchange, 0.001)
        want_usdt = notional * (1 + buy_fee) * 1.05
        have_usdt = float(by_venue.get(opp.buy_exchange, {}).get("USDT", 0.0))
        if have_usdt < want_usdt:
            needs.append(("USDT", opp.buy_exchange, want_usdt - have_usdt))

        qty = notional / opp.buy_price if opp.buy_price > 0 else 0.0
        # Request enough for several fills, not just one
        want_coin = qty * 3.0
        floor = float(self.coin_floors.get(base, 0.0))
        want_coin = max(want_coin, floor)
        have_coin = float(by_venue.get(opp.sell_exchange, {}).get(base, 0.0))
        if have_coin < want_coin:
            needs.append((base, opp.sell_exchange, want_coin - have_coin))
        return needs

    @staticmethod
    def _richest(
        by_venue: dict[str, dict[str, float]],
        asset: str,
        *,
        exclude: str,
    ) -> str | None:
        best: str | None = None
        best_amt = 0.0
        for venue, assets in by_venue.items():
            if venue == exclude:
                continue
            amt = float(assets.get(asset, 0.0))
            if amt > best_amt:
                best_amt = amt
                best = venue
        return best if best_amt > 0 else None
