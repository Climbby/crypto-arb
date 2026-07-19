"""Annotate opportunities with paper-inventory executability."""

from __future__ import annotations

from app.models import Opportunity


def annotate_inventory(
    opportunities: list[Opportunity],
    by_venue: dict[str, dict[str, float]],
    fee_map: dict[str, float],
    default_notional: float = 100.0,
) -> list[Opportunity]:
    for opp in opportunities:
        if opp.kind == "triangular":
            usdt = float(by_venue.get(opp.buy_exchange, {}).get("USDT", 0.0))
            fee = fee_map.get(opp.buy_exchange, 0.001)
            # Need USDT for first leg (plus fees on notional)
            max_n = usdt / (1 + fee) if usdt > 0 else 0.0
            opp.max_notional_usdt = max_n
            if max_n < 1:
                opp.executable = False
                opp.inventory_note = f"Need USDT on {opp.buy_exchange} for triangular path"
            else:
                opp.executable = True
                opp.inventory_note = f"Up to ~{max_n:.2f} USDT on {opp.buy_exchange}"
            continue

        # Cross-exchange: USDT on buy venue + base coin on sell venue
        base = opp.symbol.split("/")[0]
        buy_usdt = float(by_venue.get(opp.buy_exchange, {}).get("USDT", 0.0))
        sell_coin = float(by_venue.get(opp.sell_exchange, {}).get(base, 0.0))
        buy_fee = fee_map.get(opp.buy_exchange, 0.001)

        max_from_usdt = buy_usdt / (1 + buy_fee) if buy_usdt > 0 else 0.0
        max_from_coin = sell_coin * opp.buy_price if opp.buy_price > 0 else 0.0
        max_n = min(max_from_usdt, max_from_coin)
        opp.max_notional_usdt = max_n

        if max_n < 1:
            opp.executable = False
            reasons = []
            if max_from_usdt < 1:
                reasons.append(f"low USDT on {opp.buy_exchange}")
            if max_from_coin < 1:
                reasons.append(f"low {base} on {opp.sell_exchange}")
            opp.inventory_note = "; ".join(reasons) or "insufficient inventory"
        else:
            opp.executable = True
            note = f"Up to ~{max_n:.2f} USDT"
            if max_n < default_notional:
                note += f" (default paper size {default_notional:.0f} may not fit)"
            opp.inventory_note = note

    return opportunities
