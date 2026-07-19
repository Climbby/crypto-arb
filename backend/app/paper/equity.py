"""Mark-to-market paper equity from balances + live ticks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.database import Database
from app.models import Tick

MAJOR_USDT = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def mid_prices_usdt(ticks: list[Tick]) -> dict[str, float]:
    """Best-effort mid USD(T) prices keyed by base asset (BTC, ETH, SOL)."""
    prices: dict[str, float] = {}
    for t in ticks:
        if t.symbol not in MAJOR_USDT:
            continue
        if t.mid <= 0:
            continue
        base = t.symbol.split("/")[0]
        prices[base] = t.mid
    return prices


def mark_equity_usdt(
    by_venue: dict[str, dict[str, float]],
    ticks: list[Tick],
) -> tuple[float, float]:
    """
    Return (total_equity_usdt, cash_usdt_only).

    Coins are marked at mid of */USDT books. Unknown assets are ignored.
    """
    px = mid_prices_usdt(ticks)
    equity = 0.0
    cash = 0.0
    for assets in by_venue.values():
        for asset, amount in assets.items():
            amt = float(amount)
            if asset == "USDT":
                equity += amt
                cash += amt
            elif asset in px:
                equity += amt * px[asset]
    return equity, cash


async def backfill_equity_from_trades(
    db: Database,
    *,
    by_venue: dict[str, dict[str, float]],
    ticks: list[Tick],
    realized_pnl_usdt: float,
) -> int:
    """
    Reconstruct earlier equity points from the paper trade log.

    Uses today's mark-to-market as a flat baseline and layers cumulative
    realized PnL so the chart covers trading that happened before equity
    snapshots existed.
    """
    px = mid_prices_usdt(ticks)
    # Wait until major books are present so baseline isn't understated
    if not all(k in px for k in ("BTC", "ETH", "SOL")):
        return 0

    trades = await db.list_trades(limit=5000)
    if not trades:
        return 0

    chronological = list(reversed(trades))
    first_at = str(chronological[0].get("executed_at") or "")
    if not first_at:
        return 0

    equity_now, cash_now = mark_equity_usdt(by_venue, ticks)
    mtm_baseline = equity_now - float(realized_pnl_usdt)
    cash_baseline = cash_now - float(realized_pnl_usdt)

    if await db.has_backfill_equity():
        # Replace a bad early backfill (ran before price books were warm)
        cur = await db.conn.execute(
            """
            SELECT equity_usdt FROM paper_equity
            WHERE note = 'backfill:start'
            ORDER BY id ASC LIMIT 1
            """
        )
        row = await cur.fetchone()
        if row is not None:
            start_eq = float(row["equity_usdt"])
            if abs(start_eq - mtm_baseline) < 50.0:
                return 0
        await db.conn.execute("DELETE FROM paper_equity WHERE note LIKE 'backfill%'")
        await db.conn.commit()
    else:
        earliest = await db.earliest_equity_at()
        if earliest and earliest <= first_at:
            return 0

    try:
        start_dt = datetime.fromisoformat(first_at.replace("Z", "+00:00")) - timedelta(seconds=1)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        start_iso = start_dt.isoformat()
    except ValueError:
        start_iso = first_at

    await db.record_equity(
        equity_usdt=mtm_baseline,
        realized_pnl_usdt=0.0,
        usdt_total=cash_baseline,
        note="backfill:start",
        recorded_at=start_iso,
    )

    cum = 0.0
    written = 1
    for trade in chronological:
        cum += float(trade.get("pnl_usdt") or 0.0)
        ts = str(trade.get("executed_at") or "")
        if not ts:
            continue
        await db.record_equity(
            equity_usdt=mtm_baseline + cum,
            realized_pnl_usdt=cum,
            usdt_total=cash_baseline + cum,
            note="backfill:trade",
            recorded_at=ts,
        )
        written += 1

    # Drop cash-only seed / understated early snapshots that predate warm books
    await db.conn.execute(
        """
        DELETE FROM paper_equity
        WHERE note = 'seed'
           OR (
             COALESCE(note, '') NOT LIKE 'backfill%'
             AND equity_usdt < ?
           )
        """,
        (mtm_baseline * 0.7,),
    )
    await db.conn.commit()
    return written
