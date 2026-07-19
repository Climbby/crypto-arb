"""In-memory tick store and ccxt async price poller."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

import ccxt.async_support as ccxt

from app.models import Tick, utcnow

logger = logging.getLogger(__name__)

# Map config names -> ccxt class names
EXCHANGE_CLASSES: dict[str, type] = {
    "binance": ccxt.binance,
    "kraken": ccxt.kraken,
    "coinbase": ccxt.coinbase,
}

# Some venues use different symbol formats; ccxt normalizes most.
# Coinbase historically used USD pairs; we request USDT where available
# and fall back to USD equivalents when mapping.
SYMBOL_ALIASES: dict[str, dict[str, str]] = {
    "coinbase": {
        "BTC/USDT": "BTC/USD",
        "ETH/USDT": "ETH/USD",
        "SOL/USDT": "SOL/USD",
    },
}


class TickStore:
    """Thread-safe-enough async store of latest ticks keyed by (exchange, symbol)."""

    def __init__(self) -> None:
        self._ticks: dict[tuple[str, str], Tick] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, tick: Tick) -> None:
        async with self._lock:
            self._ticks[(tick.exchange, tick.symbol)] = tick

    async def get(self, exchange: str, symbol: str) -> Tick | None:
        async with self._lock:
            return self._ticks.get((exchange, symbol))

    async def all_for_symbol(self, symbol: str) -> list[Tick]:
        async with self._lock:
            return [t for (ex, sym), t in self._ticks.items() if sym == symbol]

    async def snapshot(self) -> list[Tick]:
        async with self._lock:
            return list(self._ticks.values())


class PricePoller:
    def __init__(
        self,
        exchanges: list[str],
        symbols: list[str],
        store: TickStore,
        interval: float = 2.0,
        on_update: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.exchanges = exchanges
        self.symbols = symbols
        self.store = store
        self.interval = interval
        self.on_update = on_update
        self._clients: dict[str, ccxt.Exchange] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        for name in self.exchanges:
            cls = EXCHANGE_CLASSES.get(name)
            if cls is None:
                logger.warning("Unknown exchange %s, skipping", name)
                continue
            client = cls({"enableRateLimit": True})
            self._clients[name] = client
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="price-poller")
        logger.info(
            "Price poller started: exchanges=%s symbols=%s interval=%ss",
            list(self._clients),
            self.symbols,
            self.interval,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()

    def _resolve_symbol(self, exchange: str, symbol: str) -> str:
        return SYMBOL_ALIASES.get(exchange, {}).get(symbol, symbol)

    async def _fetch_one(self, exchange: str, client: ccxt.Exchange, symbol: str) -> None:
        market_symbol = self._resolve_symbol(exchange, symbol)
        try:
            ticker = await client.fetch_ticker(market_symbol)
            bid = ticker.get("bid")
            ask = ticker.get("ask")
            last = ticker.get("last")
            if bid is None or ask is None:
                # Fall back to last if book sides missing
                if last is None:
                    return
                bid = float(last)
                ask = float(last)
            tick = Tick(
                exchange=exchange,
                symbol=symbol,  # store canonical symbol
                bid=float(bid),
                ask=float(ask),
                last=float(last) if last is not None else None,
                timestamp=utcnow(),
            )
            await self.store.upsert(tick)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fetch failed %s %s: %s", exchange, market_symbol, exc)

    async def _poll_once(self) -> None:
        tasks = []
        for exchange, client in self._clients.items():
            for symbol in self.symbols:
                tasks.append(self._fetch_one(exchange, client, symbol))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.on_update:
            await self.on_update()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Poll cycle failed")
            await asyncio.sleep(self.interval)
