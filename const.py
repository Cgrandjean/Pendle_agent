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

# ─── Market Filters ────────────────────────────────────────────────────────
MIN_TVL = 100_000
MIN_DAYS_TO_EXPIRY = 0
MIN_BORROW_LIQUIDITY_USD = 10_000

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

🔍 `/loop [count] [chain]` — search loops
   `/loop` `/loop 10 eth` `/loop 5 arb`

🔔 `/alert [chain] [yield%]` — create alert (default: 15%)
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