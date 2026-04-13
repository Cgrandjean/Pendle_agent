"""All constants in one place."""

import re

# ─── Chains ────────────────────────────────────────────────────────────────
CHAINS = {
    "ethereum": 1, "eth": 1, "mainnet": 1,
    "arbitrum": 42161, "arb": 42161,
    "base": 8453,
    "bnb": 56, "bsc": 56,
    "optimism": 10, "op": 10,
    "mantle": 5000,
    "sonic": 146,
    "plasma": 9745,
    "berachain": 80094, "bera": 80094,
}

# ─── Asset Families ───────────────────────────────────────────────────────
ASSET_FAMILIES = {
    "stable": [
        "usdc", "usdt", "usds", "usde", "usdtb", "gho", "frax", "lusd",
        "ausd", "aUSD", "curveusd", "crvusd", "susd", "stable", "usd",
    ],
    "eth": [
        "eth", "weth", "steth", "wsteth", "reth", "cbeth", "ezeth",
        "rseth", "weeth", "eeth", "meth", "lst", "lrt",
    ],
    "btc": ["btc", "wbtc", "lbtc", "ebtc", "solvbtc", "tbtc", "cbbtc"],
}

# ─── Market Filters ────────────────────────────────────────────────────────
MIN_TVL = 100_000
MIN_DAYS_TO_EXPIRY = 0
MIN_BORROW_LIQUIDITY_USD = 10_000

# ─── Scoring Weights (must sum to 100) ────────────────────────────────────
WEIGHT_SPREAD = 35
WEIGHT_TVL = 15
WEIGHT_DAYS = 15
WEIGHT_BORROW = 20
WEIGHT_PT_DISCOUNT = 5
WEIGHT_LEVERAGE = 5
WEIGHT_MM_COUNT = 5

# Scoring thresholds
SPREAD_MAX_SCORE = 0.05    # 5% spread = max score
SPREAD_CAP = 3.0           # 3x multiplier cap
TVL_MAX_SCORE = 10_000_000  # $10M TVL = max score
TVL_CAP = 2.0
BORROW_MAX = 0.30           # 30%+ borrow = 0 score
PT_DISCOUNT_MAX = 0.10      # 10%+ discount = max score
LEVERAGE_MAX = 10           # 10x max leverage
CONTANGO_BONUS = 10
TVL_PENALTY_THRESHOLD = 500_000  # <$500k TVL = penalty
TVL_PENALTY = 5

# Days scoring thresholds
DAYS_NEGATIVE = 5
DAYS_VERY_SHORT = 2    # <7 days
DAYS_SHORT = 10        # 7-30 days
DAYS_MEDIUM = 15       # 30-180 days
DAYS_LONG = 10         # 180-365 days
DAYS_VERY_LONG = 6     # >365 days

# ─── Spike Detection Defaults ─────────────────────────────────────────────
SPIKE_WINDOW_DEFAULT = 30
SPIKE_MULTIPLIER_DEFAULT = 1.5
SPIKE_MIN_YIELD_DEFAULT = 0.05

# ─── Telegram ─────────────────────────────────────────────────────────────
MSG_MAX_LENGTH = 4096
SPIKE_KEY_MAP = {
    "window": ("spike_window", int), "w": ("spike_window", int),
    "multiplier": ("spike_multiplier", float), "mult": ("spike_multiplier", float), "x": ("spike_multiplier", float),
    "min": ("spike_min_yield", float), "min_yield": ("spike_min_yield", float),
}

HELP = """
📖 *Help — Pendle Loop Scout*

🔍 `/loop [count] [asset] [chain]` — search loops
   `/loop` `/loop stable` `/loop 10 eth arb` `/loop btc`

🔔 `/alert [asset] [chain] [yield%]` — create alert (default: 15%)
   `/alerts` `/delalert <id>`

⚡ `/spike [window|mult|min] [val]` — configure spike detection
   `/spike window 10` `/spike mult 2.0` `/spike min 0.10`

📊 `/status` — instant report | `/export` — DB summary

📐 Implied = PT rate | Spread = implied - underlying | Theo = max yield × leverage
""".strip()

# ─── Parsing ──────────────────────────────────────────────────────────────
MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
DATE_RE = re.compile(r"(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4})", re.IGNORECASE)
