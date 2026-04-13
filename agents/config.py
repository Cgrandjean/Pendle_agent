"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

from const import (
    CHAINS, ASSET_FAMILIES,
    MIN_TVL, MIN_DAYS_TO_EXPIRY, MIN_BORROW_LIQUIDITY_USD,
    SPIKE_WINDOW_DEFAULT, SPIKE_MULTIPLIER_DEFAULT, SPIKE_MIN_YIELD_DEFAULT,
)

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_IDS: list[int] = [
    int(cid.strip())
    for cid in os.environ.get("ALLOWED_CHAT_IDS", "").split(",")
    if cid.strip()
]

DB_PATH: str = os.environ.get("DB_PATH", "data/loop_scout.db")
SCAN_INTERVAL_MINUTES: int = int(os.environ.get("SCAN_INTERVAL_MINUTES", "10"))
