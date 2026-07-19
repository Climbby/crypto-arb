"""Hybrid REST + WebSocket (ccxt.pro) price feeds with debounced updates."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import ccxt.async_support as ccxt_async

from app.models import Tick, utcnow

logger = logging.getLogger(__name__)

try:
    import ccxt.pro as ccxt_pro

    HAS_PRO = True
except ImportError:  # pragma: no cover
    ccxt_pro = None  # type: ignore
    HAS_PRO = False

SYMBOL_ALIASES: dict[str, dict[str, str]] = {
    "coinbase": {
        "BTC/USDT": "BTC/USD",
        "ETH/USDT": "ETH/USD",
        "SOL/USDT": "SOL/USD",
        "ETH/BTC": "ETH/BTC",
        "SOL/BTC": "SOL/BTC",
        "SOL/ETH": "SOL/ETH",
    },
}

ASYNC_CLASSES: dict[str, type] = {
    "binance": ccxt_async.binance,
    "kraken": ccxt_async.kraken,
    "coinbase": ccxt_async.coinbase,
}

PRO_CLASSES: dict[str, type] = {}
if HAS_PRO:
    PRO_CLASSES = {
        "binance": ccxt_pro.binance,
        "kraken": ccxt_pro.kraken,
        "coinbase": ccxt_pro.coinbase,
    }


class TickStore:
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


def resolve_symbol(exchange: str, symbol: str) -> str:
    return SYMBOL_ALIASES.get(exchange, {}).get(symbol, symbol)


class PriceFeed:
    """
    Prefer ccxt.pro watch_ticker loops (sub-second). Fall back to REST polling
    per exchange when WS is unavailable. Debounce on_update to ~emit_ms.
    """

    def __init__(
        self,
        exchanges: list[str],
        symbols: list[str],
        store: TickStore,
        interval: float = 1.0,
        emit_ms: float = 150.0,
        on_update: Callable[[], Awaitable[None]] | None = None,
        use_ws: bool = True,
    ) -> None:
        self.exchanges = exchanges
        self.symbols = symbols
        self.store = store
        self.interval = interval
        self.emit_ms = emit_ms
        self.on_update = on_update
        self.use_ws = use_ws and HAS_PRO
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._emit_lock = asyncio.Lock()
        self._last_emit = 0.0
        self._pending_emit = False
        self._mode: dict[str, str] = {}

    @property
    def modes(self) -> dict[str, str]:
        return dict(self._mode)

    async def start(self) -> None:
        self._running = True
        for name in self.exchanges:
            self._tasks.append(asyncio.create_task(self._run_exchange(name), name=f"feed-{name}"))
        self._tasks.append(asyncio.create_task(self._emit_loop(), name="feed-emit"))
        logger.info(
            "Price feed started: exchanges=%s symbols=%s ws=%s emit_ms=%s",
            self.exchanges,
            self.symbols,
            self.use_ws,
            self.emit_ms,
        )

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _request_emit(self) -> None:
        self._pending_emit = True

    async def _emit_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.emit_ms / 1000.0)
            if not self._pending_emit or not self.on_update:
                continue
            async with self._emit_lock:
                self._pending_emit = False
                try:
                    await self.on_update()
                except Exception:  # noqa: BLE001
                    logger.exception("on_update failed")

    async def _run_exchange(self, exchange: str) -> None:
        if self.use_ws and exchange in PRO_CLASSES:
            try:
                await self._ws_loop(exchange)
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("WS feed failed for %s — falling back to REST", exchange, exc_info=True)
        await self._rest_loop(exchange)

    async def _apply_ticker(self, exchange: str, symbol: str, ticker: dict) -> None:
        bid = ticker.get("bid")
        ask = ticker.get("ask")
        last = ticker.get("last")
        if bid is None or ask is None:
            if last is None:
                return
            bid = float(last)
            ask = float(last)
        await self.store.upsert(
            Tick(
                exchange=exchange,
                symbol=symbol,
                bid=float(bid),
                ask=float(ask),
                last=float(last) if last is not None else None,
                timestamp=utcnow(),
            )
        )
        await self._request_emit()

    async def _ws_loop(self, exchange: str) -> None:
        cls = PRO_CLASSES[exchange]
        client = cls({"enableRateLimit": True})
        self._mode[exchange] = "ws"
        logger.info("WS feed active for %s", exchange)
        try:
            while self._running:
                # Round-robin watch across symbols so each gets updates
                for symbol in list(self.symbols):
                    if not self._running:
                        break
                    market = resolve_symbol(exchange, symbol)
                    try:
                        ticker = await client.watch_ticker(market)
                        await self._apply_ticker(exchange, symbol, ticker)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("watch_ticker %s %s: %s", exchange, market, exc)
                        await asyncio.sleep(0.5)
        finally:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass

    async def _rest_loop(self, exchange: str) -> None:
        cls = ASYNC_CLASSES.get(exchange)
        if cls is None:
            logger.warning("Unknown exchange %s", exchange)
            return
        client = cls({"enableRateLimit": True})
        self._mode[exchange] = "rest"
        logger.info("REST feed active for %s (interval=%ss)", exchange, self.interval)
        try:
            while self._running:
                for symbol in list(self.symbols):
                    market = resolve_symbol(exchange, symbol)
                    try:
                        ticker = await client.fetch_ticker(market)
                        await self._apply_ticker(exchange, symbol, ticker)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("fetch_ticker %s %s: %s", exchange, market, exc)
                await asyncio.sleep(self.interval)
        finally:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass


# Backwards-compatible alias used by older imports / tests
PricePoller = PriceFeed
