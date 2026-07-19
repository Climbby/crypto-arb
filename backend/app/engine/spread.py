"""Fee-aware cross-exchange spread engine."""

from __future__ import annotations

from itertools import permutations

from app.models import Opportunity, Tick, utcnow


def bps_to_pct(bps: float) -> float:
    """Convert basis points to percent (5 bps -> 0.05%)."""
    return bps / 100.0


def fee_fraction_to_pct(fee: float) -> float:
    """Convert fee fraction (0.001) to percent (0.1)."""
    return fee * 100.0


def compute_raw_edge_pct(buy_price: float, sell_price: float) -> float:
    """Raw edge as percent of buy price: (sell - buy) / buy * 100."""
    if buy_price <= 0:
        return 0.0
    return ((sell_price - buy_price) / buy_price) * 100.0


def compute_net_edge_pct(
    buy_price: float,
    sell_price: float,
    buy_fee: float,
    sell_fee: float,
    slippage_bps: float,
) -> tuple[float, float, float, float]:
    """
    Net edge after taker fees on both legs and slippage estimate.

    Fees are fractions of notional (e.g. 0.001 = 0.1%).
    Slippage is applied once per leg in bps.

    Returns (raw_edge_pct, net_edge_pct, buy_fee_pct, sell_fee_pct).
    """
    raw = compute_raw_edge_pct(buy_price, sell_price)
    buy_fee_pct = fee_fraction_to_pct(buy_fee)
    sell_fee_pct = fee_fraction_to_pct(sell_fee)
    # Two legs of slippage
    slip_pct = bps_to_pct(slippage_bps) * 2.0
    # Approximate: fees reduce proceeds / increase cost as % of buy notional
    net = raw - buy_fee_pct - sell_fee_pct - slip_pct
    return raw, net, buy_fee_pct, sell_fee_pct


def opportunity_id(symbol: str, buy_ex: str, sell_ex: str) -> str:
    return f"{symbol}|{buy_ex}->{sell_ex}"


def find_opportunities(
    ticks: list[Tick],
    fee_map: dict[str, float],
    slippage_bps: float,
    min_net_edge_pct: float,
) -> list[Opportunity]:
    """
    Evaluate all ordered exchange pairs for a single symbol's ticks.

    Buy at ask on buy_exchange, sell at bid on sell_exchange.
    """
    by_exchange = {t.exchange: t for t in ticks}
    opps: list[Opportunity] = []
    now = utcnow()

    for buy_ex, sell_ex in permutations(by_exchange.keys(), 2):
        buy_tick = by_exchange[buy_ex]
        sell_tick = by_exchange[sell_ex]
        buy_price = buy_tick.ask
        sell_price = sell_tick.bid
        if buy_price <= 0 or sell_price <= 0:
            continue

        buy_fee = fee_map.get(buy_ex, 0.001)
        sell_fee = fee_map.get(sell_ex, 0.001)
        raw, net, buy_fee_pct, sell_fee_pct = compute_net_edge_pct(
            buy_price, sell_price, buy_fee, sell_fee, slippage_bps
        )
        if net < min_net_edge_pct:
            continue

        slip_pct = bps_to_pct(slippage_bps) * 2.0
        opps.append(
            Opportunity(
                id=opportunity_id(buy_tick.symbol, buy_ex, sell_ex),
                symbol=buy_tick.symbol,
                buy_exchange=buy_ex,
                sell_exchange=sell_ex,
                buy_price=buy_price,
                sell_price=sell_price,
                raw_edge_pct=raw,
                net_edge_pct=net,
                buy_fee_pct=buy_fee_pct,
                sell_fee_pct=sell_fee_pct,
                slippage_pct=slip_pct,
                detected_at=now,
            )
        )

    opps.sort(key=lambda o: o.net_edge_pct, reverse=True)
    return opps


class SpreadEngine:
    def __init__(
        self,
        fee_map: dict[str, float],
        slippage_bps: float = 5.0,
        min_net_edge_pct: float = 0.05,
    ) -> None:
        self.fee_map = dict(fee_map)
        self.slippage_bps = slippage_bps
        self.min_net_edge_pct = min_net_edge_pct
        self._current: dict[str, Opportunity] = {}

    def update_settings(
        self,
        fee_map: dict[str, float] | None = None,
        slippage_bps: float | None = None,
        min_net_edge_pct: float | None = None,
    ) -> None:
        if fee_map is not None:
            self.fee_map = dict(fee_map)
        if slippage_bps is not None:
            self.slippage_bps = slippage_bps
        if min_net_edge_pct is not None:
            self.min_net_edge_pct = min_net_edge_pct

    def scan(self, all_ticks: list[Tick], symbols: list[str]) -> list[Opportunity]:
        found: list[Opportunity] = []
        for symbol in symbols:
            ticks = [t for t in all_ticks if t.symbol == symbol]
            if len(ticks) < 2:
                continue
            found.extend(
                find_opportunities(
                    ticks, self.fee_map, self.slippage_bps, self.min_net_edge_pct
                )
            )
        self._current = {o.id: o for o in found}
        return found

    @property
    def current(self) -> list[Opportunity]:
        return sorted(self._current.values(), key=lambda o: o.net_edge_pct, reverse=True)

    def get(self, opp_id: str) -> Opportunity | None:
        return self._current.get(opp_id)
