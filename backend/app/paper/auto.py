"""Auto paper executor — fire fills when live edges clear inventory + threshold."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable

from app.models import Opportunity, Tick
from app.paper.broker import PaperBroker, PaperBrokerError

logger = logging.getLogger(__name__)


class AutoPaperTrader:
    """
    Runs after each scan. Guards:
    - enabled flag
    - min net edge (defaults to scanner threshold if unset)
    - only executable (inventory-aware) opportunities
    - per-opportunity cooldown (same id won't re-fire every tick)
    - max fills per scan + rolling max per minute
    """

    def __init__(
        self,
        broker: PaperBroker,
        *,
        enabled: bool = True,
        notional_usdt: float = 100.0,
        min_net_edge_pct: float | None = None,
        cooldown_seconds: float = 12.0,
        max_per_scan: int = 3,
        max_per_minute: int = 20,
    ) -> None:
        self.broker = broker
        self.enabled = enabled
        self.notional_usdt = notional_usdt
        self.min_net_edge_pct = min_net_edge_pct
        self.cooldown_seconds = cooldown_seconds
        self.max_per_scan = max_per_scan
        self.max_per_minute = max_per_minute
        self._last_fire: dict[str, float] = {}
        self._recent: deque[float] = deque()
        self.last_result: dict[str, Any] | None = None
        self.fills_total = 0
        self.skips_total = 0

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "notional_usdt": self.notional_usdt,
            "min_net_edge_pct": self.min_net_edge_pct,
            "cooldown_seconds": self.cooldown_seconds,
            "max_per_scan": self.max_per_scan,
            "max_per_minute": self.max_per_minute,
            "fills_total": self.fills_total,
            "skips_total": self.skips_total,
            "last_result": self.last_result,
        }

    def _prune_recent(self, now: float) -> None:
        while self._recent and now - self._recent[0] > 60.0:
            self._recent.popleft()

    async def maybe_execute(
        self,
        opportunities: list[Opportunity],
        *,
        fee_map: dict[str, float],
        slippage_bps: float,
        scanner_min_edge: float,
        ticks: list[Tick],
        on_fill: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        now = time.monotonic()
        self._prune_recent(now)
        if len(self._recent) >= self.max_per_minute:
            self.skips_total += 1
            self.last_result = {
                "ok": False,
                "reason": "rate_limit: max fills/minute reached",
                "at": time.time(),
            }
            return []

        threshold = (
            self.min_net_edge_pct
            if self.min_net_edge_pct is not None
            else scanner_min_edge
        )

        blocked = sum(1 for o in opportunities if o.executable is False)
        eligible = [
            o
            for o in opportunities
            if o.executable is not False
            and o.net_edge_pct >= threshold
            and (o.max_notional_usdt is None or o.max_notional_usdt >= 1.0)
        ]
        eligible.sort(key=lambda o: o.net_edge_pct, reverse=True)

        if not eligible:
            if opportunities:
                self.last_result = {
                    "ok": False,
                    "reason": (
                        f"no_executable: {len(opportunities)} edges shown, "
                        f"{blocked} blocked by inventory"
                    ),
                    "at": time.time(),
                }
                self.skips_total += 1
            return []

        fills: list[dict[str, Any]] = []
        cooled = 0
        for opp in eligible:
            if len(fills) >= self.max_per_scan:
                break
            if len(self._recent) >= self.max_per_minute:
                break

            last = self._last_fire.get(opp.id, 0.0)
            if now - last < self.cooldown_seconds:
                cooled += 1
                continue

            size = self.notional_usdt
            if opp.max_notional_usdt is not None:
                size = min(size, float(opp.max_notional_usdt))
            if size < 1.0:
                continue

            ticks_for_venue = None
            if opp.kind == "triangular":
                ticks_for_venue = {
                    t.symbol: t for t in ticks if t.exchange == opp.buy_exchange
                }

            try:
                result = await self.broker.execute(
                    opp,
                    size,
                    fee_map,
                    ticks_for_venue=ticks_for_venue,
                    slippage_bps=slippage_bps,
                )
            except PaperBrokerError as exc:
                logger.info("Auto paper skip %s: %s", opp.id, exc)
                self.skips_total += 1
                self.last_result = {
                    "ok": False,
                    "reason": str(exc),
                    "opp_id": opp.id,
                    "at": time.time(),
                }
                continue

            self._last_fire[opp.id] = now
            self._recent.append(now)
            self.fills_total += 1
            trade = result.get("trade", {})
            payload = {
                "ok": True,
                "opp_id": opp.id,
                "symbol": opp.symbol,
                "kind": opp.kind,
                "net_edge_pct": opp.net_edge_pct,
                "notional_usdt": size,
                "pnl_usdt": trade.get("pnl_usdt"),
                "trade": trade,
                "at": time.time(),
            }
            self.last_result = payload
            fills.append(payload)
            logger.info(
                "Auto paper fill %s edge=%.4f%% size=%.2f pnl=%.4f",
                opp.id,
                opp.net_edge_pct,
                size,
                float(trade.get("pnl_usdt") or 0),
            )
            if on_fill:
                await on_fill(payload)

        if not fills and eligible:
            self.skips_total += 1
            if cooled == len(eligible):
                reason = (
                    f"cooldown: {cooled} executable edge(s) waiting "
                    f"{self.cooldown_seconds:.0f}s per route"
                )
            else:
                reason = f"skipped: {cooled} on cooldown, rest failed inventory/size"
            self.last_result = {
                "ok": False,
                "reason": reason,
                "at": time.time(),
            }

        return fills
