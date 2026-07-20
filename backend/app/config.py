"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    poll_interval_seconds: float = 1.0
    feed_emit_ms: float = 150.0
    use_websocket_feeds: bool = True
    enable_triangular: bool = True
    min_net_edge_pct: float = 0.05
    slippage_bps: float = 5.0  # 5 bps = 0.05% per leg estimate
    watched_symbols: str = "BTC/USDT,ETH/USDT,SOL/USDT"
    exchanges: str = "binance,kraken,coinbase"
    db_path: str = "data/crypto_arb.db"
    paper_starting_usdt: float = 10_000.0
    # Auto paper: fill when edge + inventory clear (paper only)
    auto_paper_enabled: bool = True
    # Size = min(max, buy_venue_usdt * pct); skip below min
    auto_paper_notional_pct: float = 0.03
    auto_paper_notional_max_usdt: float = 500.0
    auto_paper_notional_min_usdt: float = 10.0
    # Legacy alias — treated as max cap if max unset in older .env
    auto_paper_notional_usdt: float = 500.0
    # None → use min_net_edge_pct; set higher to be pickier than the board
    auto_paper_min_net_edge_pct: float | None = None
    auto_paper_cooldown_seconds: float = 12.0
    auto_paper_max_per_scan: int = 3
    auto_paper_max_per_minute: int = 20
    # Move paper inventory when a venue is short for an edge
    auto_rebalance_enabled: bool = True
    auto_rebalance_cooldown_seconds: float = 180.0
    auto_rebalance_usdt_chunk: float = 500.0
    # Persist every opportunity that clears the threshold (24/7 diary)
    persist_every_scan: bool = True
    # Optional path to built frontend (defaults to ../frontend/dist from backend/)
    frontend_dist: str = ""
    # Default taker fees (fraction of notional)
    fee_binance: float = 0.001
    fee_kraken: float = 0.0026
    fee_coinbase: float = 0.006

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.watched_symbols.split(",") if s.strip()]

    @property
    def exchange_list(self) -> list[str]:
        return [e.strip().lower() for e in self.exchanges.split(",") if e.strip()]

    def fee_map(self) -> dict[str, float]:
        return {
            "binance": self.fee_binance,
            "kraken": self.fee_kraken,
            "coinbase": self.fee_coinbase,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
