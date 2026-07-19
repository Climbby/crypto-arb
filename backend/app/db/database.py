"""SQLite persistence for opportunities, paper portfolio, and settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from app.models import Opportunity, utcnow


SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    buy_exchange TEXT NOT NULL,
    sell_exchange TEXT NOT NULL,
    buy_price REAL NOT NULL,
    sell_price REAL NOT NULL,
    raw_edge_pct REAL NOT NULL,
    net_edge_pct REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_balances (
    venue TEXT NOT NULL,
    asset TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (venue, asset)
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    buy_exchange TEXT NOT NULL,
    sell_exchange TEXT NOT NULL,
    quantity REAL NOT NULL,
    buy_price REAL NOT NULL,
    sell_price REAL NOT NULL,
    net_edge_pct REAL NOT NULL,
    pnl_usdt REAL NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    from_venue TEXT NOT NULL,
    to_venue TEXT NOT NULL,
    amount REAL NOT NULL,
    delayed INTEGER NOT NULL DEFAULT 0,
    transferred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equity_usdt REAL NOT NULL,
    realized_pnl_usdt REAL NOT NULL,
    usdt_total REAL NOT NULL,
    note TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def record_opportunities(self, opps: list[Opportunity]) -> None:
        if not opps:
            return
        now = utcnow().isoformat()
        await self.conn.executemany(
            """
            INSERT INTO opportunity_snapshots
            (opp_id, symbol, buy_exchange, sell_exchange, buy_price, sell_price,
             raw_edge_pct, net_edge_pct, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    o.id,
                    o.symbol,
                    o.buy_exchange,
                    o.sell_exchange,
                    o.buy_price,
                    o.sell_price,
                    o.raw_edge_pct,
                    o.net_edge_pct,
                    now,
                )
                for o in opps
            ],
        )
        await self.conn.commit()

    async def recent_opportunities(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM opportunity_snapshots
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def prune_opportunities(self, keep: int = 5000) -> int:
        """Keep the newest N snapshot rows so the diary cannot grow forever."""
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM opportunity_snapshots")
        row = await cur.fetchone()
        count = int(row["c"]) if row else 0
        if count <= keep:
            return 0
        delete_count = count - keep
        await self.conn.execute(
            """
            DELETE FROM opportunity_snapshots
            WHERE id IN (
              SELECT id FROM opportunity_snapshots ORDER BY id ASC LIMIT ?
            )
            """,
            (delete_count,),
        )
        await self.conn.commit()
        return delete_count

    async def opportunity_stats(self, hours: int = 24) -> dict[str, Any]:
        """Aggregate opportunity diary for charts / LifeOS weekly digest."""
        from datetime import timedelta

        cutoff = (utcnow() - timedelta(hours=hours)).isoformat()
        cur = await self.conn.execute(
            """
            SELECT
              COUNT(*) AS count,
              COALESCE(AVG(net_edge_pct), 0) AS avg_net,
              COALESCE(MAX(net_edge_pct), 0) AS max_net,
              COALESCE(MIN(net_edge_pct), 0) AS min_net
            FROM opportunity_snapshots
            WHERE recorded_at >= ?
            """,
            (cutoff,),
        )
        row = await cur.fetchone()
        cur2 = await self.conn.execute(
            """
            SELECT
              substr(recorded_at, 1, 13) || ':00:00' AS bucket,
              COUNT(*) AS count,
              AVG(net_edge_pct) AS avg_net,
              MAX(net_edge_pct) AS max_net
            FROM opportunity_snapshots
            WHERE recorded_at >= ?
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            (cutoff,),
        )
        buckets = [dict(r) for r in await cur2.fetchall()]
        cur3 = await self.conn.execute(
            """
            SELECT symbol, buy_exchange, sell_exchange, net_edge_pct, recorded_at
            FROM opportunity_snapshots
            WHERE recorded_at >= ?
            ORDER BY net_edge_pct DESC
            LIMIT 5
            """,
            (cutoff,),
        )
        top = [dict(r) for r in await cur3.fetchall()]
        return {
            "hours": hours,
            "count": int(row["count"]) if row else 0,
            "avg_net_edge_pct": float(row["avg_net"]) if row else 0.0,
            "max_net_edge_pct": float(row["max_net"]) if row else 0.0,
            "min_net_edge_pct": float(row["min_net"]) if row else 0.0,
            "buckets": buckets,
            "top": top,
        }

    async def weekly_summary(self, start_iso: str, end_iso: str) -> dict[str, Any]:
        cur = await self.conn.execute(
            """
            SELECT
              COUNT(*) AS count,
              COALESCE(AVG(net_edge_pct), 0) AS avg_net,
              COALESCE(MAX(net_edge_pct), 0) AS max_net
            FROM opportunity_snapshots
            WHERE recorded_at >= ? AND recorded_at < ?
            """,
            (start_iso, end_iso),
        )
        row = await cur.fetchone()
        trades = await self.list_trades(limit=500)
        week_trades = [
            t
            for t in trades
            if start_iso <= str(t.get("executed_at", "")) < end_iso
        ]
        pnl = sum(float(t["pnl_usdt"]) for t in week_trades)
        return {
            "start": start_iso,
            "end": end_iso,
            "opportunity_count": int(row["count"]) if row else 0,
            "avg_net_edge_pct": float(row["avg_net"]) if row else 0.0,
            "max_net_edge_pct": float(row["max_net"]) if row else 0.0,
            "paper_trades": len(week_trades),
            "paper_pnl_usdt": pnl,
        }


    async def get_balances(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT venue, asset, amount FROM paper_balances ORDER BY venue, asset"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def set_balance(self, venue: str, asset: str, amount: float) -> None:
        await self.conn.execute(
            """
            INSERT INTO paper_balances (venue, asset, amount) VALUES (?, ?, ?)
            ON CONFLICT(venue, asset) DO UPDATE SET amount = excluded.amount
            """,
            (venue, asset, amount),
        )
        await self.conn.commit()

    async def clear_balances(self) -> None:
        await self.conn.execute("DELETE FROM paper_balances")
        await self.conn.commit()

    async def insert_trade(
        self,
        *,
        opp_id: str,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        net_edge_pct: float,
        pnl_usdt: float,
    ) -> dict[str, Any]:
        now = utcnow().isoformat()
        cur = await self.conn.execute(
            """
            INSERT INTO paper_trades
            (opp_id, symbol, buy_exchange, sell_exchange, quantity,
             buy_price, sell_price, net_edge_pct, pnl_usdt, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opp_id,
                symbol,
                buy_exchange,
                sell_exchange,
                quantity,
                buy_price,
                sell_price,
                net_edge_pct,
                pnl_usdt,
                now,
            ),
        )
        await self.conn.commit()
        return {
            "id": cur.lastrowid,
            "opp_id": opp_id,
            "symbol": symbol,
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "quantity": quantity,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "net_edge_pct": net_edge_pct,
            "pnl_usdt": pnl_usdt,
            "executed_at": now,
        }

    async def list_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def clear_trades(self) -> None:
        await self.conn.execute("DELETE FROM paper_trades")
        await self.conn.commit()

    async def insert_transfer(
        self,
        *,
        asset: str,
        from_venue: str,
        to_venue: str,
        amount: float,
        delayed: bool,
    ) -> dict[str, Any]:
        now = utcnow().isoformat()
        cur = await self.conn.execute(
            """
            INSERT INTO paper_transfers
            (asset, from_venue, to_venue, amount, delayed, transferred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (asset, from_venue, to_venue, amount, 1 if delayed else 0, now),
        )
        await self.conn.commit()
        return {
            "id": cur.lastrowid,
            "asset": asset,
            "from_venue": from_venue,
            "to_venue": to_venue,
            "amount": amount,
            "delayed": delayed,
            "transferred_at": now,
        }

    async def list_transfers(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM paper_transfers ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def clear_transfers(self) -> None:
        await self.conn.execute("DELETE FROM paper_transfers")
        await self.conn.commit()

    async def record_equity(
        self,
        *,
        equity_usdt: float,
        realized_pnl_usdt: float,
        usdt_total: float,
        note: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        now = recorded_at or utcnow().isoformat()
        cur = await self.conn.execute(
            """
            INSERT INTO paper_equity
            (equity_usdt, realized_pnl_usdt, usdt_total, note, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (equity_usdt, realized_pnl_usdt, usdt_total, note, now),
        )
        await self.conn.commit()
        return {
            "id": cur.lastrowid,
            "equity_usdt": equity_usdt,
            "realized_pnl_usdt": realized_pnl_usdt,
            "usdt_total": usdt_total,
            "note": note,
            "recorded_at": now,
        }

    async def list_equity(
        self, limit: int = 500, hours: float | None = None
    ) -> list[dict[str, Any]]:
        if hours is not None and hours > 0:
            from datetime import timedelta

            cutoff = (utcnow() - timedelta(hours=hours)).isoformat()
            cur = await self.conn.execute(
                """
                SELECT * FROM paper_equity
                WHERE recorded_at >= ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (cutoff, limit),
            )
        else:
            cur = await self.conn.execute(
                """
                SELECT * FROM paper_equity
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = await cur.fetchall()
        # chronological for charts
        return list(reversed([dict(r) for r in rows]))

    async def earliest_equity_at(self) -> str | None:
        cur = await self.conn.execute(
            "SELECT MIN(recorded_at) AS t FROM paper_equity"
        )
        row = await cur.fetchone()
        return None if row is None or row["t"] is None else str(row["t"])

    async def has_backfill_equity(self) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM paper_equity WHERE note LIKE 'backfill%' LIMIT 1"
        )
        return await cur.fetchone() is not None

    async def clear_equity(self) -> None:
        await self.conn.execute("DELETE FROM paper_equity")
        await self.conn.commit()

    async def prune_equity(self, keep: int = 4000) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM paper_equity")
        row = await cur.fetchone()
        count = int(row["c"]) if row else 0
        if count <= keep:
            return 0
        drop = count - keep
        await self.conn.execute(
            """
            DELETE FROM paper_equity WHERE id IN (
              SELECT id FROM paper_equity ORDER BY id ASC LIMIT ?
            )
            """,
            (drop,),
        )
        await self.conn.commit()
        return drop

    async def get_setting(self, key: str) -> str | None:
        cur = await self.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return None if row is None else row["value"]

    async def set_setting(self, key: str, value: Any) -> None:
        payload = value if isinstance(value, str) else json.dumps(value)
        await self.conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, payload),
        )
        await self.conn.commit()
