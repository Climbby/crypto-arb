"""Realistic paper-transfer timing and withdrawal fees."""

from __future__ import annotations

# Seconds until funds credit on the destination venue (optimistic retail).
TRANSFER_DELAY_SECONDS: dict[str, float] = {
    "USDT": 180.0,  # ~3 min stablecoin / internal rail
    "BTC": 1800.0,  # ~30 min
    "ETH": 600.0,  # ~10 min
    "SOL": 300.0,  # ~5 min
}

# Withdrawal / network fee deducted from the send (burned, not credited).
WITHDRAW_FEE: dict[str, float] = {
    "USDT": 1.0,
    "BTC": 0.00015,
    "ETH": 0.0008,
    "SOL": 0.01,
}

DEFAULT_DELAY_SECONDS = 600.0
DEFAULT_WITHDRAW_FEE = 0.0


def delay_seconds_for(asset: str) -> float:
    return float(TRANSFER_DELAY_SECONDS.get(asset.upper(), DEFAULT_DELAY_SECONDS))


def withdraw_fee_for(asset: str) -> float:
    return float(WITHDRAW_FEE.get(asset.upper(), DEFAULT_WITHDRAW_FEE))
