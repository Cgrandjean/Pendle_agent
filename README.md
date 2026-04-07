# Pendle Loop Scout

> **Telegram bot that detects the best loop opportunities on Pendle Finance**

An autonomous agent that continuously scans Pendle PT (Principal Token) markets, cross-references data with lending protocols (AAVE, Morpho, Euler), and identifies the best **loop** opportunities — a DeFi strategy that involves buying discounted PTs, depositing them as collateral, borrowing the underlying asset, and repurchasing PT in a cycle to amplify yield.

---

## Why this bot?

On Pendle, PTs trade at a discount to their face value. This discount implies a **fixed yield** (implied APY) that can be attractive. But the real potential comes when you combine:

1. **Buy PT** at a discount on Pendle
2. **Deposit as collateral** on a money market (AAVE, Morpho, Euler)
3. **Borrow the underlying** (e.g. USDC) against the PT
4. **Repurchase PT** with the borrowed underlying
5. **Repeat** the cycle = leverage

Theoretical yield with leverage = `implied APY + (implied APY - borrow cost) × (leverage - 1)`

This bot automates the search for these opportunities and alerts you when an interesting yield appears.

---

## Commands

### Loop search

```
/loop [count] [asset] [chain]
```

Scans Pendle markets and returns the best loop opportunities, ranked by theoretical yield.

**Examples:**
- `/loop` — top 5 all assets, all chains
- `/loop stable` — stablecoins only (USDC, USDT, USDS...)
- `/loop eth arbitrum` — ETH markets on Arbitrum
- `/loop top 10 btc` — top 10 BTC markets

**What the bot does:**
1. Fetches filtered Pendle markets
2. Enriches with external protocols (AAVE, Morpho, Euler)
3. Calculates real borrow rates for each money market
4. Estimates max leverage based on LTV
5. Calculates max theoretical yield
6. Scores and ranks opportunities

### Instant report

```
/status
```

Runs a full scan and displays the report. This is the **only way** to get a full report — the automatic background scan is silent and only sends alerts.

### Yield alerts

```
/alert [asset] [chain] [yield%]
```

Creates an alert that triggers when a market exceeds the specified theoretical yield. Checked at every automatic scan.

**Examples:**
- `/alert stable 15%` — alert if a stablecoin exceeds 15% theo yield
- `/alert eth 20%` — alert if an ETH market exceeds 20%
- `/alert 25%` — all assets > 25%
- `/alert stable arbitrum 10%` — stables on Arbitrum > 10%

**Management:**
- `/alerts` — view active alerts
- `/delalert <id>` — delete an alert

### Spike detection

```
/spike [parameter] [value]
```

Detects **sudden yield increases** by comparing current yield to the average of the last N scans. Useful for spotting ephemeral opportunities (e.g. a PT that suddenly trades at an abnormal discount).

**Configuration:**
- `/spike` — view current config
- `/spike window 10` — average over 10 scans (default: 30 = 5h)
- `/spike multiplier 2.0` — alert if yield > average × 2.0 (default: ×1.5)
- `/spike min 0.10` — ignore yields < 10% (default: 5%)

**Why it's useful:** A yield spike can indicate:
- A PT that just dropped to an abnormal discount
- A borrow rate that crashed on a money market
- A temporary opportunity before the market rebalances

### Help

```
/help
```

Displays full help with all commands.

---

## Architecture

### LangGraph Agent (scan → analyze → synthesize)

The bot uses a LangGraph graph with nodes that run in parallel:

```
                    ┌─────────────┐
                    │    START    │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │  AAVE    │   │  Morpho  │   │  Euler   │
    │  skim    │   │  skim    │   │  skim    │
    └────┬─────┘   └────┬─────┘   └────┬─────┘
         │               │               │
         ▼               ▼               ▼
    ┌─────────────────────────────────────────┐
    │         collect_protocols               │
    │  (merges lending data)                  │
    └─────────────────┬───────────────────────┘
                      ▼
    ┌─────────────────────────────────────────┐
    │         analyze_loops                   │
    │  - Calculates real borrow rates         │
    │  - Estimates max leverage from LTV      │
    │  - Calculates theoretical yield         │
    │  - Scores each opportunity              │
    └─────────────────┬───────────────────────┘
                      ▼
    ┌─────────────────────────────────────────┐
    │         synthesize                      │
    │  - Formats result for Telegram          │
    │  - Top N candidates with details        │
    └─────────────────────────────────────────┘
```

### Silent automatic scan

Every **10 minutes** (configurable), the bot:
1. Runs the LangGraph graph
2. Saves results to SQLite
3. Checks **threshold alerts** (yield > configured threshold)
4. Checks **spikes** (yield > average × multiplier)
5. **Only sends a message if an alert triggers**

No automatic report — you must run `/status` to see the full report.

### Persistence (SQLite)

```
data/loop_scout.db
├── scans              # Scan history
├── candidates         # Detailed results per scan
├── alerts             # User alerts
├── yield_history      # Yield history per market
└── settings           # Spike config (window, multiplier, min_yield)
```

The `yield_history` table enables moving average calculation for spike detection.

---

## Deploy on Hugging Face Spaces (free)

Hugging Face Spaces offers free Docker hosting, perfect for a Telegram bot.

### Step 1: Create the Space

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space)
2. Choose a name (e.g. `pendle-loop-scout`)
3. Select **Docker** as SDK
4. Visibility: **Private** (recommended to protect the token)

### Step 2: Configure secrets

In the Space **Settings** → **Repository secrets**, add:

| Secret | Value | Description |
|--------|-------|-------------|
| `TELEGRAM_BOT_TOKEN` | `your_bot_token_here` | Token from @BotFather |
| `ALLOWED_CHAT_IDS` | `your_chat_id_here` | Your chat ID (via @userinfobot) |
| `SCAN_INTERVAL_MINUTES` | `10` | Scan frequency (minutes) |
| `SPIKE_WINDOW` | `30` | Scans for average (30 × 10min = 5h) |
| `SPIKE_MULTIPLIER` | `1.5` | Spike trigger ratio |
| `SPIKE_MIN_YIELD` | `0.05` | Minimum yield for spikes (5%) |
| `DEFAULT_REPORT_QUERY` | `top 10 stable loops` | Default query for /status |

### Step 3: Push the code

```bash
# Clone the Space (replace USERNAME and SPACE_NAME)
git clone https://huggingface.co/spaces/USERNAME/SPACE_NAME
cd SPACE_NAME

# Copy all bot files
cp -r /path/to/Pendle_agent/* .

# Commit and push
git add .
git commit -m "Initial commit: Pendle Loop Scout"
git push
```

### Step 4: Verify

- The Space builds automatically
- Check the **Logs** tab for bot logs
- Send `/start` on Telegram to test

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *(required)* | Telegram bot token |
| `ALLOWED_CHAT_IDS` | *(empty)* | Authorized chat IDs (comma-separated) |
| `SCAN_INTERVAL_MINUTES` | `10` | Silent scan frequency |
| `DEFAULT_REPORT_QUERY` | `top 5 stable loops` | Default query for /status |
| `SPIKE_WINDOW` | `30` | Number of scans for moving average |
| `SPIKE_MULTIPLIER` | `1.5` | Spike trigger ratio |
| `SPIKE_MIN_YIELD` | `0.05` | Minimum yield for spikes |
| `DB_PATH` | `data/loop_scout.db` | SQLite database path |

---

## How to read results

Each displayed opportunity contains:

| Field | Description |
|-------|-------------|
| **Implied APY** | Fixed rate of the PT (guaranteed if held to maturity) |
| **Underlying APY** | Yield of the underlying asset |
| **Spread** | `implied - underlying` — gross loop margin |
| **PT Discount** | PT discount to face value |
| **TVL** | Total Value Locked of the market |
| **Liquidity** | Available liquidity to buy/sell |
| **Days to expiry** | Days remaining until PT maturity |
| **Borrow cost** | Real borrow rate on the cheapest money market |
| **Yield theo** | Max estimated yield with leverage |
| **Score** | Composite /100 (spread, TVL, expiry, money market count, contango) |

---

## Local development

```bash
# Install dependencies
poetry install

# Configure environment
cp .env.example .env
# Edit .env with your Telegram token

# Run the bot
python -m telegram_bot.bot
```

### Project structure

```
Pendle_agent/
├── agents/
│   ├── loop_scout_agent.py   # Main LangGraph agent
│   ├── pendle_mcp.py         # Pendle MCP API client
│   └── config.py             # Configuration (chains, assets, thresholds)
│
├── utils/
│   ├── fetch_aave.py         # AAVE rate fetching
│   ├── fetch_morpho.py       # Morpho rate fetching
│   ├── fetch_euler.py        # Euler rate fetching
│   ├── scoring.py            # Candidate scoring algorithm
│   ├── formatting.py         # Telegram message formatting
│   ├── parsing.py            # User query parsing
│   └── database.py           # SQLite persistence
│
├── telegram_bot/
│   ├── bot.py                # Bot entry point
│   └── handlers.py           # Telegram command handlers
│
├── schemas/
│   └── agent_state.py        # Agent state TypedDict schema
│
├── scripts/
│   ├── hf_runner.py          # Hugging Face Spaces runner
│   └── run_agent.py          # Local runner
│
├── Dockerfile                # Docker image for HF Spaces
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## Disclaimer

This bot is a **read-only** decision support tool. Displayed yields are **theoretical** estimates. In practice:

- Real LTVs may differ from theoretical LTVs
- Borrow rates change in real time
- Slippage on PT purchases reduces yield
- Gas fees impact loop profitability
- Pendle markets can be illiquid

**DYOR** (Do Your Own Research) and always verify on-chain parameters before executing a loop.