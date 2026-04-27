---
title: Pendle Loop Scout
emoji: 🔄
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

# Pendle Loop Scout

> **Telegram bot that detects the best loop opportunities on Pendle Finance**

An autonomous agent that continuously scans Pendle PT (Principal Token) markets across **10 chains** (Ethereum, Arbitrum, Base, Optimism, BNB, Sonic, Mantle, Plasma, Berachain), cross-references data with lending protocols (AAVE V3, Morpho Blue, Euler V2), and identifies the best **loop** opportunities — a DeFi strategy that involves buying discounted PTs, depositing them as collateral, borrowing the underlying asset, and repurchasing PT in a cycle to amplify yield.

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
/loop [count] [chain]
```

Scans Pendle markets and returns the best loop opportunities, ranked by theoretical yield.

**Examples:**
- `/loop` — top 5, all chains
- `/loop 10` — top 10 results
- `/loop eth` — ETH markets on Ethereum
- `/loop arb` — ETH markets on Arbitrum

### Instant report

```
/status
```

Shows the cached results from the last automatic scan. Useful for quick checks without triggering a new scan.

**Note:** `/loop` also triggers a fresh scan and displays results immediately if you want updated data.

### Yield alerts

```
/alert [chain] [yield%]
```

Creates an alert that triggers when a market exceeds the specified theoretical yield. Checked at every automatic scan.

**Examples:**
- `/alert 15%` — alert if any market exceeds 15% theo yield
- `/alert eth 20%` — ETH markets on Ethereum exceed 20%
- `/alert arb 10%` — ETH markets on Arbitrum exceed 10%

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

### Database management

```
/export
```

Displays database summary: total scans, active alerts, last scan info, and top candidates.

```
/resetdb [confirm]
```

Resets the database (requires `confirm` argument). Use after updates to ensure schema is current.

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
     │         collect_markets                  │
     │  (fetches Pendle PT markets)             │
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

## Supported Chains

| Chain      | ID     | Notes              |
|------------|--------|---------------------|
| Ethereum   | 1      | Mainnet            |
| Arbitrum   | 42161  |                    |
| Base       | 8453   |                    |
| BNB        | 56     | BSC                |
| Optimism   | 10     |                    |
| Sonic      | 146    |                    |
| Mantle     | 5000   |                    |
| Plasma     | 9745   |                    |
| Berachain  | 80094  |                    |

---

## 🚀 Deploy on Fly.io (recommended — free, reliable)

Fly.io free tier has unrestricted outbound networking. Telegram bot polling works perfectly.

### 1. Install Fly CLI and login
```bash
brew install flyctl
flyctl auth login
```

### 2. Launch app (first time only)
```bash
cd Pendle_agent
fly launch --no-deploy
# Follow prompts: app name = pendle-loop-scout, region = cdg (Paris)
```

### 3. Set secrets
```bash
fly secrets set TELEGRAM_BOT_TOKEN=your_token_here
fly secrets set ALLOWED_CHAT_IDS=123456789
fly secrets set SCAN_INTERVAL_MINUTES=10
```

### 4. Create persistent volume (data persists across deploys)
```bash
fly volume create pendle_data --size 1
```

### 5. Deploy
```bash
fly deploy
```

### 6. Check logs
```bash
fly logs
```

### 7. Update after code changes
```bash
fly deploy
```

---

## 🧪 Hugging Face Spaces (legacy — has network restrictions)

⚠️ HF Spaces free tier has restricted outbound access. Telegram polling may fail with `ConnectTimeout`. If that happens, migrate to Fly.io (see above).

### Deploy on HF Spaces
```bash
git push hf main  # auto-deploys via repo sync
```

### Secrets (in HF Space Settings → Variables and secrets)
```
TELEGRAM_BOT_TOKEN=your_token_here
ALLOWED_CHAT_IDS=123456789
SCAN_INTERVAL_MINUTES=10
WEBHOOK_URL=https://your-space.hf.space  # optional, webhook mode
```

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

# Or run the agent directly (CLI)
python scripts/run_agent.py [count] [chain]
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *(required)* | Telegram bot token |
| `ALLOWED_CHAT_IDS` | *(empty)* | Authorized chat IDs (comma-separated) |
| `SCAN_INTERVAL_MINUTES` | `10` | Silent scan frequency |
| `DB_PATH` | `data/loop_scout.db` | SQLite database path |
| `WEBHOOK_URL` | *(empty)* | Webhook URL (HF Spaces only, leave empty for polling) |
| `WEBHOOK_PORT` | `7860` | Webhook port |

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
| **Score** | Composite /100 (spread, TVL, expiry, money market count) |

---

## Project structure

```
Pendle_agent/
├── agents/
│   ├── loop_scout_agent.py   # Main LangGraph agent (finds loop opportunities)
│   └── config.py             # Configuration (chains, assets, thresholds, LTV defaults)
│
├── utils/
│   ├── fetch_pendle.py       # Fetch Pendle PT markets (10 chains)
│   ├── fetch_aave.py         # AAVE V3 borrow rates
│   ├── fetch_morpho.py       # Morpho Blue PT markets
│   ├── fetch_euler.py        # Euler V2 PT and stable vaults
│   ├── formatting.py        # Telegram message formatting
│   ├── parsing.py            # PT symbol parsing and asset detection
│   └── database.py           # SQLite persistence (scans, alerts, yield history)
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
│   ├── run_agent.py          # Local CLI runner
│   ├── explore_db.py         # Database exploration utility
│   ├── reset_db.py           # Database reset utility
│   └── test_alerts.py        # Alert testing utility
│
├── const.py                  # All constants (chains, defaults, help text)
│
├── Dockerfile                # Docker image (HF Spaces + Fly.io)
├── fly.toml                  # Fly.io config
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