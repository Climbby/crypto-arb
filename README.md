# Crypto Arb Scanner + Paper Trader (ArbWatch)

Cross-exchange arbitrage **scanner** and **paper trader**. Detects theoretical price gaps across Binance, Kraken, and Coinbase, shows net edge after fees/slippage, logs opportunities 24/7 to SQLite, and lets you simulate fills with virtual capital.

**Not a live trading bot.** Paper fills ignore latency, order-book depth, and real withdrawal times.

## Does it run forever and log trades?

| Mode | What happens |
|------|----------------|
| **Scanner (always on)** | Polls venues ~1s, computes net edge, **writes every qualifying opportunity to SQLite** (`opportunity_snapshots`) |
| **Paper trades** | Only when you click **Paper exec** — not automatic |
| **TradingView chart** | Embedded widget (TradingView’s data); independent of our scanner |

So: yes, a deployed instance keeps scanning and **notes possible theoretical trades** in history. It does **not** auto-execute.

## Local quick start

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api.main:app --reload --port 8000

# Frontend (dev)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (Vite proxies `/api` and `/ws`).

### Production-style local (one process)

```bash
cd frontend && npm run build && cd ..
cd backend && source .venv/bin/activate
uvicorn app.api.main:app --port 8010
```

Open http://localhost:8010 — API + SPA from the same server.

## Homelab 24/7 (Proxmox)

Deploys to **CT115** (`192.168.1.13`) alongside Project Viz:

| Piece | Value |
|-------|--------|
| Path | `/opt/crypto-arb` |
| App | uvicorn `:8010` |
| nginx | `:8081` → app |
| Public (after tunnel) | `https://arb.guessitgame.me` |

```bash
# First time on the CT
sudo bash homelab/install.sh

# From WSL after git push
./homelab/deploy.sh root@192.168.1.13
```

See [homelab/cloudflare-tunnel.md](homelab/cloudflare-tunnel.md).

## Optimizations (current + future)

**Done in v1**
- ~1s poll interval (was 2s)
- Persist opportunities every scan (not every 5th)
- REST + WebSocket UI updates
- Single-process prod serve (no separate Vite in prod)

**Worth doing later (if you care about speed)**
- Exchange **WebSocket** tickers via `ccxt.pro` (sub-second, less REST rate-limit risk)
- Co-locate the CT closer to exchange regions (latency still won’t beat HFT)
- Lower `MIN_NET_EDGE_PCT` to log more near-misses (more DB rows)

Retail cross-exchange arb is mostly educational: fees + transfer delay eat most edges.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + scan count |
| GET | `/prices` | Latest ticks |
| GET | `/opportunities` | Current net-positive edges |
| GET | `/opportunities/history` | SQLite diary of theoretical edges |
| WS | `/ws/opportunities` | Live push |
| GET/PATCH | `/settings` | Fees, min edge, symbols |
| GET/POST | `/paper/*` | Portfolio, execute, transfer, reset |

## Configuration

Copy `.env.example` → `backend/.env`. No exchange API keys required for scanning.

## Phase 2 (deferred)

- Triangular arbitrage
- Live trading + risk limits
- Withdrawal latency modeling
