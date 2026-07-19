# ArbWatch — Cloudflare Tunnel + Access

Same pattern as Project Viz / Nourish: tunnel on **CT105**, app on **CT115**.

## 1. DNS + tunnel route

In **Cloudflare Zero Trust → Networks → Tunnels**:

| Field | Value |
|---|---|
| Subdomain | `arb` (→ `arb.guessitgame.me`) |
| Domain | `guessitgame.me` |
| Service | `http://192.168.1.13:8081` (CT115 nginx → uvicorn `:8010`) |

## 2. Zero Trust Access (recommended)

Self-hosted app on `arb.guessitgame.me` with an email allowlist (same as projects.guessitgame.me).

## 3. Deploy loop

```bash
# First time on CT115
git clone git@github.com:Climbby/crypto-arb.git /opt/crypto-arb
cd /opt/crypto-arb && sudo bash homelab/install.sh

# After pushes (from WSL)
./homelab/deploy.sh root@192.168.1.13
```
