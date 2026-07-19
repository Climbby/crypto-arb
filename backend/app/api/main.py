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
from app.engine.spread import SpreadEngine
from app.feeds.poller import PricePoller, TickStore
from app.paper.broker import PaperBroker, PaperBrokerError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExecuteRequest(BaseModel):
    opportunity_id: str
    notional_usdt: float = Field(default=100.0, gt=0)


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
    # Resolve DB path relative to backend/ (…/backend/app/api/main.py → parents[2])
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
    manager = ConnectionManager()
    state: dict[str, Any] = {
        "settings": settings,
        "symbols": list(settings.symbol_list),
        "last_opps": [],
        "scan_count": 0,
    }
    poller_holder: dict[str, PricePoller | None] = {"poller": None}
    persist_lock = asyncio.Lock()

    async def on_prices_updated() -> None:
        ticks = await store.snapshot()
        opps = engine.scan(ticks, state["symbols"])
        state["last_opps"] = opps
        state["scan_count"] = int(state["scan_count"]) + 1
        await manager.broadcast(
            {
                "type": "opportunities",
                "opportunities": [o.to_dict() for o in opps],
                "prices": [t.to_dict() for t in ticks],
                "scan_count": state["scan_count"],
            }
        )
        # Persist theoretical opportunities every scan (24/7 diary)
        if opps and settings.persist_every_scan:
            async with persist_lock:
                await db.record_opportunities(opps)
                if state["scan_count"] % 100 == 0:
                    pruned = await db.prune_opportunities(keep=5000)
                    if pruned:
                        logger.info("Pruned %s old opportunity snapshots", pruned)
        elif opps and state["scan_count"] % 5 == 0:
            async with persist_lock:
                await db.record_opportunities(opps)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await broker.ensure_seeded()
        poller = PricePoller(
            exchanges=settings.exchange_list,
            symbols=state["symbols"],
            store=store,
            interval=settings.poll_interval_seconds,
            on_update=on_prices_updated,
        )
        poller_holder["poller"] = poller
        await poller.start()
        yield
        await poller.stop()
        await db.close()

    app = FastAPI(title="Crypto Arb Scanner", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "scan_count": state["scan_count"]}

    @app.get("/prices")
    async def get_prices() -> dict[str, Any]:
        ticks = await store.snapshot()
        return {"prices": [t.to_dict() for t in ticks]}

    @app.get("/opportunities")
    async def get_opportunities() -> dict[str, Any]:
        opps = engine.current
        return {
            "opportunities": [o.to_dict() for o in opps],
            "theoretical": True,
            "note": "Edges are theoretical after fees/slippage; ignore latency and depth.",
        }

    @app.get("/opportunities/history")
    async def opportunity_history(limit: int = 100) -> dict[str, Any]:
        rows = await db.recent_opportunities(limit=min(limit, 500))
        return {"history": rows}

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
        }

    @app.patch("/settings")
    async def patch_settings(body: SettingsUpdate) -> dict[str, Any]:
        s: Settings = state["settings"]
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
            poller = poller_holder["poller"]
            if poller:
                poller.symbols = body.watched_symbols
        if body.paper_starting_usdt is not None:
            broker.starting_usdt = body.paper_starting_usdt
        await db.set_setting(
            "runtime",
            {
                "min_net_edge_pct": engine.min_net_edge_pct,
                "slippage_bps": engine.slippage_bps,
                "fees": engine.fee_map,
                "watched_symbols": state["symbols"],
                "paper_starting_usdt": broker.starting_usdt,
            },
        )
        # Re-scan with new thresholds
        await on_prices_updated()
        return await get_app_settings()

    @app.get("/paper")
    async def paper_portfolio() -> dict[str, Any]:
        return await broker.portfolio()

    @app.post("/paper/reset")
    async def paper_reset() -> dict[str, Any]:
        return await broker.reset()

    @app.post("/paper/execute")
    async def paper_execute(body: ExecuteRequest) -> dict[str, Any]:
        opp = engine.get(body.opportunity_id)
        if opp is None:
            raise HTTPException(status_code=404, detail="Opportunity not found or expired")
        try:
            result = await broker.execute(opp, body.notional_usdt, engine.fee_map)
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
        # Send current snapshot immediately
        ticks = await store.snapshot()
        opps = engine.current
        await ws.send_text(
            json.dumps(
                {
                    "type": "opportunities",
                    "opportunities": [o.to_dict() for o in opps],
                    "prices": [t.to_dict() for t in ticks],
                    "scan_count": state["scan_count"],
                }
            )
        )
        try:
            while True:
                # Keep alive; client messages ignored
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    # Production: serve built Vite SPA from the same process
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
            # Never steal API / WS paths if a client hits GET on them
            blocked = (
                "health",
                "prices",
                "opportunities",
                "settings",
                "paper",
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
