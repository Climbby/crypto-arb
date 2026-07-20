"""FastAPI application: REST + WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db.database import Database
from app.engine.inventory import annotate_inventory
from app.engine.spread import SpreadEngine
from app.engine.triangular import triangular_symbols
from app.feeds.poller import PriceFeed, TickStore
from app.paper.auto import AutoPaperTrader
from app.paper.broker import PaperBroker, PaperBrokerError
from app.paper.equity import (
    backfill_equity_from_trades,
    mark_equity_by_venue,
    mark_equity_usdt,
    purge_backfill_equity,
)
from app.paper.rebalance import AutoRebalancer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExecuteRequest(BaseModel):
    opportunity_id: str
    notional_usdt: float = Field(default=400.0, gt=0)


class TransferRequest(BaseModel):
    asset: str
    from_venue: str
    to_venue: str
    amount: float = Field(gt=0)
    delayed: bool = False


class SettingsUpdate(BaseModel):
    min_net_edge_pct: float | None = None
    slippage_bps: float | None = None
    fee_binance: float | None = None
    fee_kraken: float | None = None
    fee_coinbase: float | None = None
    watched_symbols: list[str] | None = None
    paper_starting_usdt: float | None = None
    auto_paper_enabled: bool | None = None
    auto_paper_notional_usdt: float | None = Field(default=None, gt=0)
    auto_paper_min_net_edge_pct: float | None = None
    auto_paper_cooldown_seconds: float | None = Field(default=None, ge=0)
    auto_paper_max_per_scan: int | None = Field(default=None, ge=1, le=10)
    auto_paper_max_per_minute: int | None = Field(default=None, ge=1, le=60)
    auto_rebalance_enabled: bool | None = None
    auto_rebalance_cooldown_seconds: float | None = Field(default=None, ge=0)
    auto_rebalance_usdt_chunk: float | None = Field(default=None, gt=0)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        data = json.dumps(payload)
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    backend_root = Path(__file__).resolve().parents[2]
    db_path = settings.db_path
    if not Path(db_path).is_absolute():
        db_path = str(backend_root / db_path)

    store = TickStore()
    engine = SpreadEngine(
        fee_map=settings.fee_map(),
        slippage_bps=settings.slippage_bps,
        min_net_edge_pct=settings.min_net_edge_pct,
    )
    db = Database(db_path)
    broker = PaperBroker(
        db=db,
        venues=settings.exchange_list,
        starting_usdt=settings.paper_starting_usdt,
    )
    auto = AutoPaperTrader(
        broker,
        enabled=settings.auto_paper_enabled,
        notional_usdt=settings.auto_paper_notional_usdt,
        min_net_edge_pct=settings.auto_paper_min_net_edge_pct,
        cooldown_seconds=settings.auto_paper_cooldown_seconds,
        max_per_scan=settings.auto_paper_max_per_scan,
        max_per_minute=settings.auto_paper_max_per_minute,
    )
    rebalancer = AutoRebalancer(
        broker,
        enabled=settings.auto_rebalance_enabled,
        notional_usdt=settings.auto_paper_notional_usdt,
        cooldown_seconds=settings.auto_rebalance_cooldown_seconds,
        usdt_chunk=settings.auto_rebalance_usdt_chunk,
        max_transfers_per_scan=4,
        coin_floors={k: v * 0.4 for k, v in broker.seed_coins.items()},
    )
    manager = ConnectionManager()

    cross_symbols = list(settings.symbol_list)
    feed_symbols = sorted(set(cross_symbols) | set(triangular_symbols()))

    state: dict[str, Any] = {
        "settings": settings,
        "symbols": cross_symbols,
        "feed_symbols": feed_symbols,
        "last_opps": [],
        "scan_count": 0,
        "feed_modes": {},
    }
    feed_holder: dict[str, PriceFeed | None] = {"feed": None}
    persist_lock = asyncio.Lock()
    auto_lock = asyncio.Lock()
    backfill_state = {"done": False}

    async def annotate(opps: list) -> list:
        portfolio = await broker.portfolio()
        return annotate_inventory(
            opps,
            portfolio.get("by_venue", {}),
            engine.fee_map,
            default_notional=auto.notional_usdt,
        )

    async def snapshot_equity(ticks: list, note: str | None = None) -> dict[str, Any] | None:
        from app.paper.equity import mark_equity_by_venue, mid_prices_usdt

        px = mid_prices_usdt(ticks)
        if not all(k in px for k in ("BTC", "ETH", "SOL")):
            return None
        portfolio = await broker.portfolio()
        by_venue = portfolio.get("by_venue", {})
        equity, cash = mark_equity_usdt(by_venue, ticks)
        by_eq = mark_equity_by_venue(by_venue, ticks)
        return await db.record_equity(
            equity_usdt=equity,
            realized_pnl_usdt=float(portfolio.get("realized_pnl_usdt") or 0),
            usdt_total=cash,
            note=note,
            by_venue=by_eq,
        )

    async def maybe_backfill_equity(ticks: list) -> None:
        portfolio = await broker.portfolio()
        written = await backfill_equity_from_trades(
            db,
            by_venue=portfolio.get("by_venue", {}),
            ticks=ticks,
            realized_pnl_usdt=float(portfolio.get("realized_pnl_usdt") or 0),
        )
        if written:
            logger.info("Backfilled %s equity points from paper trades", written)
            backfill_state["done"] = True
        elif backfill_state["done"] is False:
            # Keep trying until majors are priced / backfill settles
            px = {t.symbol for t in ticks}
            if {"BTC/USDT", "ETH/USDT", "SOL/USDT"} <= px:
                # Majors present but nothing to write — stop retrying
                backfill_state["done"] = True

    async def on_prices_updated() -> None:
        ticks = await store.snapshot()
        await maybe_backfill_equity(ticks)
        opps = engine.scan(
            ticks,
            state["symbols"],
            include_triangular=settings.enable_triangular,
        )
        opps = await annotate(opps)
        state["last_opps"] = opps
        state["scan_count"] = int(state["scan_count"]) + 1
        feed = feed_holder["feed"]
        if feed:
            state["feed_modes"] = feed.modes

        fills: list[dict[str, Any]] = []
        transfers: list[dict[str, Any]] = []
        async with auto_lock:
            # First move inventory toward blocked edges, then try to fill
            transfers = await rebalancer.maybe_rebalance(
                opps,
                fee_map=engine.fee_map,
                min_edge=engine.min_net_edge_pct,
            )
            if transfers:
                opps = await annotate(opps)
                state["last_opps"] = opps
            fills = await auto.maybe_execute(
                opps,
                fee_map=engine.fee_map,
                slippage_bps=engine.slippage_bps,
                scanner_min_edge=engine.min_net_edge_pct,
                ticks=ticks,
            )
        if fills or transfers:
            opps = await annotate(opps)
            state["last_opps"] = opps
            note = "fill" if fills else "rebalance"
            if fills and transfers:
                note = "fill+rebalance"
            await snapshot_equity(ticks, note=note)
        elif int(state["scan_count"]) % 60 == 0:
            # ~every 30–60s depending on feed rate — denser heartbeats ate retention
            await snapshot_equity(ticks, note="heartbeat")

        await manager.broadcast(
            {
                "type": "opportunities",
                "opportunities": [o.to_dict() for o in opps],
                "prices": [t.to_dict() for t in ticks],
                "scan_count": state["scan_count"],
                "feed_modes": state["feed_modes"],
                "auto_paper": auto.status(),
                "auto_rebalance": rebalancer.status(),
                "auto_fills": fills,
                "auto_transfers": transfers,
            }
        )
        if opps and settings.persist_every_scan:
            async with persist_lock:
                await db.record_opportunities(opps)
                if state["scan_count"] % 100 == 0:
                    pruned = await db.prune_opportunities(keep=8000)
                    if pruned:
                        logger.info("Pruned %s old opportunity snapshots", pruned)
                    eq_pruned = await db.prune_equity(keep=20_000)
                    if eq_pruned:
                        logger.info("Pruned %s old equity snapshots", eq_pruned)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await broker.ensure_seeded()
        purged = await purge_backfill_equity(db)
        if purged:
            logger.info("Purged %s spike-prone backfill equity rows", purged)
        existing = await db.list_equity(limit=1)
        if not existing:
            await db.record_equity(
                equity_usdt=broker.starting_usdt,
                realized_pnl_usdt=0.0,
                usdt_total=broker.starting_usdt,
                note="seed",
            )
        feed = PriceFeed(
            exchanges=settings.exchange_list,
            symbols=state["feed_symbols"],
            store=store,
            interval=settings.poll_interval_seconds,
            emit_ms=settings.feed_emit_ms,
            on_update=on_prices_updated,
            use_ws=settings.use_websocket_feeds,
        )
        feed_holder["feed"] = feed
        await feed.start()
        yield
        await feed.stop()
        await db.close()

    app = FastAPI(title="Crypto Arb Scanner", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "scan_count": state["scan_count"],
            "feed_modes": state["feed_modes"],
            "triangular": settings.enable_triangular,
            "auto_paper": auto.status(),
            "auto_rebalance": rebalancer.status(),
        }

    @app.get("/prices")
    async def get_prices() -> dict[str, Any]:
        ticks = await store.snapshot()
        return {"prices": [t.to_dict() for t in ticks], "feed_modes": state["feed_modes"]}

    @app.get("/opportunities")
    async def get_opportunities() -> dict[str, Any]:
        opps = await annotate(engine.current)
        return {
            "opportunities": [o.to_dict() for o in opps],
            "theoretical": True,
            "note": "Edges are theoretical after fees/slippage; inventory flags are paper-only.",
        }

    @app.get("/opportunities/history")
    async def opportunity_history(limit: int = 100) -> dict[str, Any]:
        rows = await db.recent_opportunities(limit=min(limit, 500))
        return {"history": rows}

    @app.get("/stats")
    async def stats(hours: int = 24) -> dict[str, Any]:
        return await db.opportunity_stats(hours=min(max(hours, 1), 168))

    @app.get("/stats/week")
    async def stats_week(start: str, end: str) -> dict[str, Any]:
        return await db.weekly_summary(start_iso=start, end_iso=end)

    @app.get("/settings")
    async def get_app_settings() -> dict[str, Any]:
        s: Settings = state["settings"]
        return {
            "min_net_edge_pct": engine.min_net_edge_pct,
            "slippage_bps": engine.slippage_bps,
            "fees": engine.fee_map,
            "watched_symbols": state["symbols"],
            "exchanges": s.exchange_list,
            "paper_starting_usdt": broker.starting_usdt,
            "poll_interval_seconds": s.poll_interval_seconds,
            "feed_emit_ms": s.feed_emit_ms,
            "use_websocket_feeds": s.use_websocket_feeds,
            "enable_triangular": s.enable_triangular,
            "feed_modes": state["feed_modes"],
            "auto_paper_enabled": auto.enabled,
            "auto_paper_notional_usdt": auto.notional_usdt,
            "auto_paper_min_net_edge_pct": auto.min_net_edge_pct,
            "auto_paper_cooldown_seconds": auto.cooldown_seconds,
            "auto_paper_max_per_scan": auto.max_per_scan,
            "auto_paper_max_per_minute": auto.max_per_minute,
            "auto_paper": auto.status(),
            "auto_rebalance_enabled": rebalancer.enabled,
            "auto_rebalance_cooldown_seconds": rebalancer.cooldown_seconds,
            "auto_rebalance_usdt_chunk": rebalancer.usdt_chunk,
            "auto_rebalance": rebalancer.status(),
        }

    @app.patch("/settings")
    async def patch_settings(body: SettingsUpdate) -> dict[str, Any]:
        fee_map = dict(engine.fee_map)
        if body.fee_binance is not None:
            fee_map["binance"] = body.fee_binance
        if body.fee_kraken is not None:
            fee_map["kraken"] = body.fee_kraken
        if body.fee_coinbase is not None:
            fee_map["coinbase"] = body.fee_coinbase
        engine.update_settings(
            fee_map=fee_map,
            slippage_bps=body.slippage_bps,
            min_net_edge_pct=body.min_net_edge_pct,
        )
        if body.watched_symbols is not None:
            state["symbols"] = body.watched_symbols
            state["feed_symbols"] = sorted(set(body.watched_symbols) | set(triangular_symbols()))
            feed = feed_holder["feed"]
            if feed:
                feed.symbols = state["feed_symbols"]
        if body.paper_starting_usdt is not None:
            broker.starting_usdt = body.paper_starting_usdt
        if body.auto_paper_enabled is not None:
            auto.enabled = body.auto_paper_enabled
        if body.auto_paper_notional_usdt is not None:
            auto.notional_usdt = body.auto_paper_notional_usdt
            rebalancer.notional_usdt = body.auto_paper_notional_usdt
        if "auto_paper_min_net_edge_pct" in body.model_fields_set:
            auto.min_net_edge_pct = body.auto_paper_min_net_edge_pct
        if body.auto_paper_cooldown_seconds is not None:
            auto.cooldown_seconds = body.auto_paper_cooldown_seconds
        if body.auto_paper_max_per_scan is not None:
            auto.max_per_scan = body.auto_paper_max_per_scan
        if body.auto_paper_max_per_minute is not None:
            auto.max_per_minute = body.auto_paper_max_per_minute
        if body.auto_rebalance_enabled is not None:
            rebalancer.enabled = body.auto_rebalance_enabled
        if body.auto_rebalance_cooldown_seconds is not None:
            rebalancer.cooldown_seconds = body.auto_rebalance_cooldown_seconds
        if body.auto_rebalance_usdt_chunk is not None:
            rebalancer.usdt_chunk = body.auto_rebalance_usdt_chunk
        await db.set_setting(
            "runtime",
            {
                "min_net_edge_pct": engine.min_net_edge_pct,
                "slippage_bps": engine.slippage_bps,
                "fees": engine.fee_map,
                "watched_symbols": state["symbols"],
                "paper_starting_usdt": broker.starting_usdt,
                "auto_paper_enabled": auto.enabled,
                "auto_paper_notional_usdt": auto.notional_usdt,
                "auto_paper_min_net_edge_pct": auto.min_net_edge_pct,
                "auto_paper_cooldown_seconds": auto.cooldown_seconds,
                "auto_paper_max_per_scan": auto.max_per_scan,
                "auto_paper_max_per_minute": auto.max_per_minute,
                "auto_rebalance_enabled": rebalancer.enabled,
                "auto_rebalance_cooldown_seconds": rebalancer.cooldown_seconds,
                "auto_rebalance_usdt_chunk": rebalancer.usdt_chunk,
            },
        )
        await on_prices_updated()
        return await get_app_settings()

    @app.get("/paper")
    async def paper_portfolio() -> dict[str, Any]:
        return await broker.portfolio()

    @app.get("/paper/equity")
    async def paper_equity(limit: int = 400, hours: float | None = None) -> dict[str, Any]:
        from datetime import timedelta

        from app.models import utcnow

        rows = await db.list_equity(
            limit=min(max(limit, 10), 5000),
            hours=hours if hours and hours > 0 else None,
        )
        ticks = await store.snapshot()
        portfolio = await broker.portfolio()
        by_venue = portfolio.get("by_venue", {})
        equity, cash = mark_equity_usdt(by_venue, ticks)
        current_by = mark_equity_by_venue(by_venue, ticks)
        cutoff = (utcnow() - timedelta(hours=24)).isoformat()
        past_by = await db.equity_by_venue_at_or_before(cutoff)
        venues: dict[str, dict[str, Any]] = {}
        for venue, eq in current_by.items():
            daily_pct: float | None = None
            if past_by is not None and venue in past_by:
                base = float(past_by[venue])
                if base > 1e-9:
                    daily_pct = ((eq - base) / base) * 100.0
            venues[venue] = {
                "equity_usdt": eq,
                "daily_pct": daily_pct,
            }
        return {
            "current": {
                "equity_usdt": equity,
                "usdt_total": cash,
                "realized_pnl_usdt": float(portfolio.get("realized_pnl_usdt") or 0),
            },
            "venues": venues,
            "history": rows,
            "hours": hours,
            "auto_rebalance": rebalancer.status(),
        }

    @app.post("/paper/reset")
    async def paper_reset() -> dict[str, Any]:
        return await broker.reset()

    @app.post("/paper/execute")
    async def paper_execute(body: ExecuteRequest) -> dict[str, Any]:
        opp = engine.get(body.opportunity_id)
        if opp is None:
            raise HTTPException(status_code=404, detail="Opportunity not found or expired")
        ticks_for_venue = None
        if opp.kind == "triangular":
            ticks = await store.snapshot()
            ticks_for_venue = {
                t.symbol: t for t in ticks if t.exchange == opp.buy_exchange
            }
        try:
            result = await broker.execute(
                opp,
                body.notional_usdt,
                engine.fee_map,
                ticks_for_venue=ticks_for_venue,
                slippage_bps=engine.slippage_bps,
            )
        except PaperBrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @app.post("/paper/transfer")
    async def paper_transfer(body: TransferRequest) -> dict[str, Any]:
        try:
            return await broker.transfer(
                asset=body.asset.upper(),
                from_venue=body.from_venue.lower(),
                to_venue=body.to_venue.lower(),
                amount=body.amount,
                delayed=body.delayed,
            )
        except PaperBrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/ws/opportunities")
    async def ws_opportunities(ws: WebSocket) -> None:
        await manager.connect(ws)
        ticks = await store.snapshot()
        opps = await annotate(engine.current)
        await ws.send_text(
            json.dumps(
                {
                    "type": "opportunities",
                    "opportunities": [o.to_dict() for o in opps],
                    "prices": [t.to_dict() for t in ticks],
                    "scan_count": state["scan_count"],
                    "feed_modes": state["feed_modes"],
                    "auto_paper": auto.status(),
                    "auto_fills": [],
                    "auto_rebalance": rebalancer.status(),
                    "auto_transfers": [],
                }
            )
        )
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    dist = Path(settings.frontend_dist) if settings.frontend_dist else (
        backend_root.parent / "frontend" / "dist"
    )
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            blocked = (
                "health",
                "prices",
                "opportunities",
                "settings",
                "paper",
                "stats",
                "ws",
                "docs",
                "openapi.json",
                "redoc",
            )
            first = full_path.split("/", 1)[0]
            if first in blocked:
                raise HTTPException(status_code=404, detail="Not found")
            candidate = dist / full_path
            if candidate.is_file():
                try:
                    candidate.resolve().relative_to(dist.resolve())
                except ValueError as exc:
                    raise HTTPException(status_code=404, detail="Not found") from exc
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

        logger.info("Serving frontend from %s", dist)
    else:
        logger.info("No frontend dist at %s — API only (dev mode)", dist)

    return app


app = create_app()
