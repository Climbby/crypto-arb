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
    """

    def __init__(
        self,
        broker: PaperBroker,
        *,
        enabled: bool = True,
        notional_usdt: float = 100.0,
        cooldown_seconds: float = 20.0,
        max_transfers_per_scan: int = 2,
        usdt_chunk: float = 500.0,
        leave_usdt_reserve: float = 50.0,
    ) -> None:
        self.broker = broker
        self.enabled = enabled
        self.notional_usdt = notional_usdt
        self.cooldown_seconds = cooldown_seconds
        self.max_transfers_per_scan = max_transfers_per_scan
        self.usdt_chunk = usdt_chunk
        self.leave_usdt_reserve = leave_usdt_reserve
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

        for opp in blocked:
            if len(done) >= self.max_transfers_per_scan:
                break
            needs = self._needs(opp, by_venue, fee_map)
            for asset, to_venue, amount in needs:
                if len(done) >= self.max_transfers_per_scan:
                    break
                key = f"{asset}->{to_venue}"
                if self._cooled(key, now):
                    continue
                donor = self._richest(by_venue, asset, exclude=to_venue)
                if donor is None:
                    continue
                available = float(by_venue.get(donor, {}).get(asset, 0.0))
                if asset == "USDT":
                    send = min(amount, available - self.leave_usdt_reserve, self.usdt_chunk)
                else:
                    # leave a tiny dust reserve
                    send = min(amount, available * 0.9)
                if send < (1.0 if asset == "USDT" else 1e-6):
                    continue
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
                    continue

                self._last[key] = now
                self.transfers_total += 1
                # refresh local map for subsequent needs in this scan
                by_venue = result["portfolio"].get("by_venue", by_venue)
                payload = {
                    "ok": True,
                    "asset": asset,
                    "from_venue": donor,
                    "to_venue": to_venue,
                    "amount": send,
                    "for_opp": opp.id,
                    "net_edge_pct": opp.net_edge_pct,
                    "transfer": result.get("transfer"),
                    "at": time.time(),
                }
                self.last_result = payload
                done.append(payload)
                logger.info(
                    "Auto rebalance %s %.6f %s → %s (for %s)",
                    asset,
                    send,
                    donor,
                    to_venue,
                    opp.id,
                )

        if not done and blocked:
            self.last_result = {
                "ok": False,
                "reason": f"{len(blocked)} blocked edge(s); no donor inventory available",
                "at": time.time(),
            }
        return done

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
        want_coin = qty * 1.05
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
