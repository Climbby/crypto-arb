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
    recorded_at TEXT NOT NULL,
    by_venue_json TEXT
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
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        cur = await self.conn.execute("PRAGMA table_info(paper_equity)")
        cols = {str(r["name"]) for r in await cur.fetchall()}
        if "by_venue_json" not in cols:
            await self.conn.execute(
                "ALTER TABLE paper_equity ADD COLUMN by_venue_json TEXT"
            )

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
            SELECT
              symbol,
              buy_exchange,
              sell_exchange,
              ROUND(net_edge_pct, 3) AS net_edge_pct,
              MAX(recorded_at) AS recorded_at,
              COUNT(*) AS count
            FROM opportunity_snapshots
            WHERE recorded_at >= ?
            GROUP BY symbol, buy_exchange, sell_exchange, ROUND(net_edge_pct, 3)
            ORDER BY net_edge_pct DESC
            LIMIT 40
            """,
            (cutoff,),
        )
        top = [dict(r) for r in await cur3.fetchall()]
        for item in top:
            item["net_edge_pct"] = float(item["net_edge_pct"] or 0)
            item["count"] = int(item["count"] or 1)
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
        by_venue: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        now = recorded_at or utcnow().isoformat()
        by_venue_json = json.dumps(by_venue) if by_venue is not None else None
        cur = await self.conn.execute(
            """
            INSERT INTO paper_equity
            (equity_usdt, realized_pnl_usdt, usdt_total, note, recorded_at, by_venue_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (equity_usdt, realized_pnl_usdt, usdt_total, note, now, by_venue_json),
        )
        await self.conn.commit()
        return {
            "id": cur.lastrowid,
            "equity_usdt": equity_usdt,
            "realized_pnl_usdt": realized_pnl_usdt,
            "usdt_total": usdt_total,
            "note": note,
            "recorded_at": now,
            "by_venue": by_venue,
        }

    async def equity_by_venue_at_or_before(self, iso: str) -> dict[str, float] | None:
        cur = await self.conn.execute(
            """
            SELECT by_venue_json FROM paper_equity
            WHERE by_venue_json IS NOT NULL AND recorded_at <= ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (iso,),
        )
        row = await cur.fetchone()
        if row is None or not row["by_venue_json"]:
            return None
        try:
            data = json.loads(str(row["by_venue_json"]))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return {str(k): float(v) for k, v in data.items()}

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
                  AND COALESCE(note, '') NOT LIKE 'backfill%'
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (cutoff, limit),
            )
        else:
            cur = await self.conn.execute(
                """
                SELECT * FROM paper_equity
                WHERE COALESCE(note, '') NOT LIKE 'backfill%'
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

    async def prune_equity(self, keep: int = 20_000) -> int:
        """Keep newest `keep` non-backfill rows; always drop backfill debris."""
        await self.conn.execute(
            "DELETE FROM paper_equity WHERE note LIKE 'backfill%'"
        )
        cur = await self.conn.execute(
            """
            SELECT COUNT(*) AS c FROM paper_equity
            WHERE COALESCE(note, '') NOT LIKE 'backfill%'
            """
        )
        row = await cur.fetchone()
        count = int(row["c"]) if row else 0
        if count <= keep:
            await self.conn.commit()
            return 0
        drop = count - keep
        await self.conn.execute(
            """
            DELETE FROM paper_equity WHERE id IN (
              SELECT id FROM paper_equity
              WHERE COALESCE(note, '') NOT LIKE 'backfill%'
              ORDER BY id ASC LIMIT ?
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
