"""Telegram bot handlers."""

import logging
import re
from datetime import datetime, timezone

from telegram import Update, Bot
from telegram.ext import ContextTypes

from agents.loop_scout_agent import LoopScoutAgent
from agents.config import ALLOWED_CHAT_IDS, DEFAULT_REPORT_QUERY, CHAINS
from utils.database import (
    add_alert, get_alerts, delete_alert,
    check_alerts_for_candidates, get_scan_count,
    get_last_scan_candidates, detect_yield_spikes,
    get_spike_config, set_setting,
    reset_db, export_db_summary,
)
from utils.formatting import fmt_pct, format_candidate

log = logging.getLogger(__name__)

# Module-level agent singleton
_agent = None

# Help text sections
HELP_INTRO = (
    "📖 *Help — Pendle Loop Scout*\n\n"
    "*What is a loop?*\n"
    "Buy a discounted PT on Pendle, deposit it as collateral on a money market "
    "(AAVE, Morpho, Euler…), borrow the underlying asset, and buy more PT. "
    "Repeat = leverage.\n"
    "Max theoretical yield = implied APY × estimated leverage."
)

HELP_LOOP = (
    "*🔍 Loop search:*\n"
    "`/loop [count] [asset] [chain]`\n"
    "• `/loop` — top 5 all assets, all chains\n"
    "• `/loop stable` — stablecoins only\n"
    "• `/loop top 10 eth arbitrum` — top 10 ETH on Arbitrum\n"
    "• `/loop btc` — BTC markets\n\n"
    "Chains: `ethereum` `arbitrum` `base` `bnb` `optimism` `mantle` `sonic`\n"
    "Assets: `stable` `eth` `btc`"
)

HELP_REPORTS = (
    "*📊 Reports:*\n"
    "• `/status` — instant report\n"
    "• Silent scan every 10 min (no auto-report)"
)

HELP_ALERTS = (
    "*🔔 Alerts — notified when theo yield > threshold:*\n"
    "`/alert [asset] [chain] [yield%]`\n"
    "• `/alert stable 15%` — alert if a stable exceeds 15%\n"
    "• `/alert eth 20%` — alert if an ETH market exceeds 20%\n"
    "• `/alert 25%` — all assets > 25%\n"
    "• `/alert stable arbitrum 10%` — stables on Arbitrum > 10%\n"
    "• `/alerts` — view active alerts\n"
    "• `/delalert <id>` — delete an alert"
)

HELP_SPIKE = (
    "*⚡ Spike detection — detects sudden yield increases:*\n"
    "Compares current yield to the average of the last N scans.\n"
    "Alerts if yield > average × multiplier.\n\n"
    "• `/spike` — view current config\n"
    "• `/spike window 10` — average over 10 scans (default: 30)\n"
    "• `/spike multiplier 2.0` — alert if ×2.0 (default: ×1.5)\n"
    "• `/spike min 0.10` — ignore yields < 10% (default: 5%)"
)

HELP_DATABASE = (
    "*🗄️ Database:*\n"
    "• `/export` — view database summary\n"
    "• `/resetdb` — reset database (use `/resetdb confirm`)"
)

HELP_CHAT = (
    "*🧹 Chat:*\n"
    "• `/clear` — clear bot messages from chat (use `/clear confirm`)"
)

HELP_READING = (
    "*📐 How to read results:*\n"
    "• *Implied APY* — fixed rate of the PT\n"
    "• *Underlying APY* — yield of the underlying asset\n"
    "• *Spread* — implied - underlying (margin)\n"
    "• *Borrow cost* — real borrow rate on the money market\n"
    "• *Yield theo* — max estimated yield with leverage\n"
    "• *Score* — composite /100 (spread, TVL, expiry, MM count)"
)

SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━"

# Spike config aliases
SPIKE_KEY_MAP = {
    "window": ("spike_window", int),
    "w": ("spike_window", int),
    "multiplier": ("spike_multiplier", float),
    "mult": ("spike_multiplier", float),
    "x": ("spike_multiplier", float),
    "min": ("spike_min_yield", float),
    "min_yield": ("spike_min_yield", float),
}

MSG_MAX_LENGTH = 4096


def _get_agent() -> LoopScoutAgent:
    """Get or create the singleton agent."""
    global _agent
    if _agent is None:
        _agent = LoopScoutAgent()
    return _agent


async def _send_chunks(bot: Bot, chat_id: int, text: str):
    """Send text in chunks to respect Telegram's message length limit."""
    while text:
        chunk, text = text[:MSG_MAX_LENGTH], text[MSG_MAX_LENGTH:]
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")


def _is_authorized(chat_id: int) -> bool:
    """Check if the chat is authorized to use the bot."""
    return not ALLOWED_CHAT_IDS or chat_id in ALLOWED_CHAT_IDS


def _parse_alert_args(args: str) -> tuple:
    """Parse alert command arguments. Returns (asset_filter, chain, min_yield)."""
    low = args.lower().strip()

    # Parse yield percentage
    min_yield = 0.10  # default
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", low)
    if m:
        min_yield = float(m.group(1)) / 100
    else:
        m = re.search(r"(\d+\.\d+)", low)
        if m and float(m.group(1)) < 1:
            min_yield = float(m.group(1))

    asset_filter = next((kw for kw in ["stable", "eth", "btc"] if kw in low), None)
    chain = next((kw for kw in CHAINS if kw in low), None)

    return asset_filter, chain, min_yield


def _format_alert_message(now: str, matches: list) -> str:
    """Format alert message for Telegram."""
    lines = [f"🔔 *Alert* — _{now}_\n"]
    for i, c in enumerate(matches[:5], 1):
        theo = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
        lines.append(f"*{i}. {c.get('name', '?')}* — theo yield: {fmt_pct(theo)}")
    if len(matches) > 5:
        lines.append(f"_+{len(matches) - 5} more_")
    return "\n".join(lines)


def _format_spike_entry(index: int, spike: dict) -> str:
    """Format a single spike entry for Telegram."""
    mms = spike.get("money_markets", [])
    if isinstance(mms, str):
        mms = [mms] if mms else []

    vault_name = spike.get("vault_name", "")
    leverage = spike.get("leverage", 0)
    implied = spike.get("implied_apy", 0)
    borrow_detail = spike.get("borrow_detail", "")

    entry = f"*{index}. {spike.get('name', '?')}*\n"

    if vault_name:
        lev_str = f" ({leverage}x)" if leverage > 0 else ""
        entry += f"   🔁 Vault: {vault_name}{lev_str}\n"

    if borrow_detail and borrow_detail != "Automated loop":
        entry += f"   💵 {borrow_detail}\n"

    entry += (
        f"   📊 Implied: {fmt_pct(implied)} → Theo: {fmt_pct(spike['current_yield'])}\n"
        f"   ⚡ ×{spike['spike_ratio']:.1f} vs avg {fmt_pct(spike['sma_yield'])}\n"
        f"   🏦 {', '.join(mms) or 'N/A'}"
    )
    return entry


def _format_spike_message(now: str, spikes: list) -> str:
    """Format spike alert message for Telegram."""
    lines = [
        f"🚨 *SPIKE* — _{now}_\n",
        f"_{len(spikes)} market(s) surging:_\n"
    ]
    for i, s in enumerate(spikes[:5], 1):
        lines.append(_format_spike_entry(i, s))
    if len(spikes) > 5:
        lines.append(f"_+{len(spikes) - 5} more_")
    return "\n".join(lines)


# -- Command Handlers --

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not _is_authorized(update.effective_chat.id):
        return
    await update.message.reply_text(
        "🔄 *Pendle Loop Scout*\n\n"
        "Telegram bot that detects the best *loop* opportunities on Pendle.\n"
        "Scans PT markets, cross-references with AAVE/Morpho/Euler borrow rates, "
        "and calculates max theoretical yield with leverage.\n\n"
        "📖 `/help` for all commands.",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not _is_authorized(update.effective_chat.id):
        return

    scans = get_scan_count()
    sections = [
        HELP_INTRO, SEPARATOR, HELP_LOOP, SEPARATOR,
        HELP_REPORTS, SEPARATOR, HELP_ALERTS, SEPARATOR,
        HELP_SPIKE, SEPARATOR, HELP_DATABASE, SEPARATOR,
        HELP_CHAT, SEPARATOR, HELP_READING,
        f"_{scans} scans in database._"
    ]
    await update.message.reply_text("\n\n".join(sections), parse_mode="Markdown")


async def loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /loop command."""
    if not _is_authorized(update.effective_chat.id):
        return
    query = " ".join(context.args) if context.args else ""
    await _run_query(update, query)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - shows cached results from last scan."""
    if not _is_authorized(update.effective_chat.id):
        return
    
    candidates = get_last_scan_candidates()
    if not candidates:
        await update.message.reply_text(
            "📊 *Status Report*\n\n"
            "No cached data. Run `/loop` to trigger a scan first.",
            parse_mode="Markdown",
        )
        return
    
    # Sort by theoretical yield and take top 10
    candidates.sort(key=lambda c: c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0, reverse=True)
    top = candidates[:10]
    
    # Get last scan info
    from utils.database import export_db_summary
    summary = export_db_summary()
    last_scan = summary.get("last_scan", {})
    ts = last_scan.get("ts", "?")
    query = last_scan.get("query", "?")
    
    lines = [f"📊 *Status Report* — _cached from {ts}_\n"]
    lines.append(f"_Query: `{query}`_\n")
    lines.append(f"_Showing top {len(top)} of {len(candidates)} candidates:_\n")
    
    for i, c in enumerate(top, 1):
        lines.append(format_candidate(i, c))
    
    lines.append("\n⚠️ *Disclaimer* — Rendements théoriques estimés. Vérifiez LTV/borrow réels. Bot read-only. DYOR.")
    
    msg = "\n".join(lines)
    if len(msg) <= MSG_MAX_LENGTH:
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await _send_chunks(context.bot, update.effective_chat.id, msg)


async def alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alert command."""
    if not _is_authorized(update.effective_chat.id):
        return

    args = " ".join(context.args) if context.args else ""
    if not args:
        await update.message.reply_text(
            "⚙️ `/alert [asset] [chain] [yield%]`\n\n"
            "Ex: `/alert stable 15%`, `/alert eth 20%`, `/alert 25%`",
            parse_mode="Markdown",
        )
        return

    asset_filter, chain, min_yield = _parse_alert_args(args)
    alert_id = add_alert(
        chat_id=update.effective_chat.id,
        asset_filter=asset_filter,
        chain=chain,
        min_yield=min_yield,
    )

    await update.message.reply_text(
        f"✅ *Alert #{alert_id}*\n"
        f"Asset: {asset_filter or 'all'} | Chain: {chain or 'all'}\n"
        f"Min theo yield: {fmt_pct(min_yield)}",
        parse_mode="Markdown",
    )


async def alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts command."""
    if not _is_authorized(update.effective_chat.id):
        return

    alerts = get_alerts(chat_id=update.effective_chat.id)
    if not alerts:
        await update.message.reply_text(
            "No alerts. `/alert stable 15%` to create one.",
            parse_mode="Markdown",
        )
        return

    lines = ["🔔 *Active alerts:*\n"]
    for a in alerts:
        asset = a.get("asset_filter") or "all"
        chain = a.get("chain") or "all"
        lines.append(
            f"• *#{a['id']}* — {asset} / {chain} / yield > {fmt_pct(a.get('min_yield', 0))}"
        )
    lines.append("\n`/delalert <id>` to delete.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def spike_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /spike command."""
    if not _is_authorized(update.effective_chat.id):
        return

    args = context.args or []
    cfg = get_spike_config()

    if not args:
        await update.message.reply_text(
            "⚡ *Spike Detection Config*\n\n"
            f"• Window: `{cfg['window']}` scans\n"
            f"• Multiplier: `×{cfg['multiplier']}`\n"
            f"• Min yield: `{fmt_pct(cfg['min_yield'])}`\n\n"
            "Change: `/spike window 10`, `/spike multiplier 2.0`, `/spike min 0.08`",
            parse_mode="Markdown",
        )
        return

    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/spike <window|multiplier|min> <value>`",
            parse_mode="Markdown",
        )
        return

    key = args[0].lower()
    if key not in SPIKE_KEY_MAP:
        await update.message.reply_text(
            f"Unknown key: `{key}`. Use `window`, `multiplier`, or `min`.",
            parse_mode="Markdown",
        )
        return

    try:
        val = float(args[1])
    except ValueError:
        await update.message.reply_text("Invalid value.")
        return

    db_key, type_fn = SPIKE_KEY_MAP[key]
    set_setting(db_key, type_fn(val))
    cfg = get_spike_config()

    await update.message.reply_text(
        f"✅ *Spike config updated*\n\n"
        f"• Window: `{cfg['window']}` scans\n"
        f"• Multiplier: `×{cfg['multiplier']}`\n"
        f"• Min yield: `{fmt_pct(cfg['min_yield'])}`",
        parse_mode="Markdown",
    )


async def delalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /delalert command."""
    if not _is_authorized(update.effective_chat.id):
        return

    if not context.args:
        await update.message.reply_text("`/delalert <id>`", parse_mode="Markdown")
        return

    try:
        aid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID.")
        return

    if delete_alert(aid, update.effective_chat.id):
        await update.message.reply_text(f"✅ Alert #{aid} deleted.")
    else:
        await update.message.reply_text(f"❌ Alert #{aid} not found.")


async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /export command."""
    if not _is_authorized(update.effective_chat.id):
        return

    summary = export_db_summary()
    lines = [
        "📊 *Database Export*\n",
        f"• Total scans: `{summary.get('total_scans', 0)}`",
        f"• Total candidates: `{summary.get('total_candidates', 0)}`",
        f"• Active alerts: `{summary.get('active_alerts', 0)}`",
    ]

    last_scan = summary.get("last_scan")
    if last_scan:
        lines.append(f"\n🕒 *Last scan:* _{last_scan.get('ts', '?')}_")
        lines.append(f"   Query: `{last_scan.get('query', '?')}`")
        lines.append(f"   Candidates: `{last_scan.get('total_candidates', 0)}`")

    top = summary.get("top_candidates", [])
    if top:
        lines.append("\n🏆 *Top candidates:*")
        for i, c in enumerate(top, 1):
            vault = c.get("vault_name", "")
            vault_info = f" ({vault})" if vault else ""
            lines.append(
                f"   {i}. {c.get('name', '?')}{vault_info} — {fmt_pct(c.get('theoretical_yield', 0))}"
            )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def resetdb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resetdb command."""
    if not _is_authorized(update.effective_chat.id):
        return

    args = context.args or []
    if "confirm" not in args:
        await update.message.reply_text(
            "⚠️ *Reset Database*\n\n"
            "This will delete ALL data (scans, alerts, settings).\n"
            "Type `/resetdb confirm` to proceed.",
            parse_mode="Markdown",
        )
        return

    reset_db()
    await update.message.reply_text(
        "✅ *Database reset complete*\n\n"
        "The database has been recreated with the latest schema.\n"
        "Run `/status` to trigger a new scan.",
        parse_mode="Markdown",
    )


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    if not _is_authorized(update.effective_chat.id):
        return

    args = context.args or []
    if "confirm" not in args:
        await update.message.reply_text(
            "🧹 *Clear Chat*\n\n"
            "This will delete all bot messages from this chat.\n"
            "Note: Only messages < 48h old can be deleted in groups.\n"
            "Type `/clear confirm` to proceed.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("🧹 Clearing chat...")
    try:
        await msg.delete()
    except Exception:
        pass

    await update.message.reply_text(
        "✅ *Chat cleared*\n\n"
        "Bot messages have been deleted. Some messages older than 48h may remain.",
        parse_mode="Markdown",
    )


# -- Core Query Execution --

async def _run_query(update: Update, query: str, header: str = ""):
    """Run a query against the agent and send the response."""
    agent = _get_agent()
    thinking = await update.message.reply_text("⏳ Scanning…", parse_mode="Markdown")

    try:
        resp = await agent.run(query)
        if header:
            resp = header + resp

        if len(resp) <= MSG_MAX_LENGTH:
            await thinking.edit_text(resp, parse_mode="Markdown")
        else:
            await thinking.edit_text(resp[:MSG_MAX_LENGTH], parse_mode="Markdown")
            for i in range(MSG_MAX_LENGTH, len(resp), MSG_MAX_LENGTH):
                await update.message.reply_text(
                    resp[i:i + MSG_MAX_LENGTH], parse_mode="Markdown"
                )
    except Exception as e:
        log.exception("Query failed")
        await thinking.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")


# -- Scheduled Scan --

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    """Silent scan every N minutes: scan + save DB + check alerts/spikes."""
    agent = _get_agent()
    log.info("Scheduled scan")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        await agent.run(DEFAULT_REPORT_QUERY)
    except Exception as e:
        log.exception("Scan failed")
        return

    bot: Bot = context.bot

    try:
        candidates = get_last_scan_candidates()
        if not candidates:
            return

        # Check alerts
        for cid, matches in check_alerts_for_candidates(candidates).items():
            if matches:
                msg = _format_alert_message(now, matches)
                try:
                    await _send_chunks(bot, cid, msg)
                except Exception as e:
                    log.error("Alert to %d: %s", cid, e)

        # Check spikes
        spikes = detect_yield_spikes(candidates)
        if spikes:
            msg = _format_spike_message(now, spikes)
            for cid in ALLOWED_CHAT_IDS:
                try:
                    await _send_chunks(bot, cid, msg)
                except Exception as e:
                    log.error("Spike to %d: %s", cid, e)

    except Exception as e:
        log.warning("Alert/spike check: %s", e)