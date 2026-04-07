"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_IDS: list[int] = [
    int(cid.strip())
    for cid in os.environ.get("ALLOWED_CHAT_IDS", "").split(",")
    if cid.strip()
]

PENDLE_MCP_URL: str = "https://api-v2.pendle.finance/core/mcp"

# Database
DB_PATH: str = os.environ.get("DB_PATH", "data/loop_scout.db")

SCAN_INTERVAL_MINUTES: int = int(os.environ.get("SCAN_INTERVAL_MINUTES", "10"))
DEFAULT_REPORT_QUERY: str = os.environ.get("DEFAULT_REPORT_QUERY", "top 5 stable loops")

# Chain ID mapping
CHAINS: dict[str, int] = {
    "ethereum": 1,
    "eth": 1,
    "mainnet": 1,
    "arbitrum": 42161,
    "arb": 42161,
    "base": 8453,
    "bnb": 56,
    "bsc": 56,
    "optimism": 10,
    "op": 10,
    "mantle": 5000,
    "sonic": 146,
}

# Asset family keywords
ASSET_FAMILIES: dict[str, list[str]] = {
    "stable": [
        "usdc", "usdt", "dai", "usde", "usdtb", "gho", "frax", "lusd",
        "curveusd", "crvusd", "susd", "stable", "usd",
    ],
    "eth": [
        "eth", "weth", "steth", "wsteth", "reth", "cbeth", "ezeth",
        "rseth", "weeth", "eeth", "meth", "lst", "lrt",
    ],
    "btc": [
        "btc", "wbtc", "lbtc", "ebtc", "solvbtc", "tbtc", "cbbtc",
    ],
}

# Market filters
MIN_TVL = 100_000
MIN_DAYS_TO_EXPIRY = 0

# Spike detection
SPIKE_WINDOW: int = int(os.environ.get("SPIKE_WINDOW", "30"))
SPIKE_MULTIPLIER: float = float(os.environ.get("SPIKE_MULTIPLIER", "1.5"))
SPIKE_MIN_YIELD: float = float(os.environ.get("SPIKE_MIN_YIELD", "0.05"))
