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
