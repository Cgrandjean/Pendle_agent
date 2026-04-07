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
)
from utils.formatting import fmt_pct

log = logging.getLogger(__name__)

agent = None


async def _send_chunks(bot, chat_id, text):
    """Send text in 4096-char chunks."""
    while text:
        chunk, text = text[:4096], text[4096:]
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")


# -- Commands --

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
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
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return
    scans = get_scan_count()
    await update.message.reply_text(
        "📖 *Help — Pendle Loop Scout*\n\n"
        "*What is a loop?*\n"
        "Buy a discounted PT on Pendle, deposit it as collateral on a money market "
        "(AAVE, Morpho, Euler…), borrow the underlying asset, and buy more PT. "
        "Repeat = leverage.\n"
        "Max theoretical yield = implied APY × estimated leverage.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🔍 Loop search:*\n"
        "`/loop [count] [asset] [chain]`\n"
        "• `/loop` — top 5 all assets, all chains\n"
        "• `/loop stable` — stablecoins only\n"
        "• `/loop top 10 eth arbitrum` — top 10 ETH on Arbitrum\n"
        "• `/loop btc` — BTC markets\n\n"
        "Chains: `ethereum` `arbitrum` `base` `bnb` `optimism` `mantle` `sonic`\n"
        "Assets: `stable` `eth` `btc`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📊 Reports:*\n"
        "• `/status` — instant report\n"
        "• Silent scan every 10 min (no auto-report)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🔔 Alerts — notified when theo yield > threshold:*\n"
        "`/alert [asset] [chain] [yield%]`\n"
        "• `/alert stable 15%` — alert if a stable exceeds 15%\n"
        "• `/alert eth 20%` — alert if an ETH market exceeds 20%\n"
        "• `/alert 25%` — all assets > 25%\n"
        "• `/alert stable arbitrum 10%` — stables on Arbitrum > 10%\n"
        "• `/alerts` — view active alerts\n"
        "• `/delalert <id>` — delete an alert\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*⚡ Spike detection — detects sudden yield increases:*\n"
        "Compares current yield to the average of the last N scans.\n"
        "Alerts if yield > average × multiplier.\n\n"
        "• `/spike` — view current config\n"
        "• `/spike window 10` — average over 10 scans (default: 30)\n"
        "• `/spike multiplier 2.0` — alert if ×2.0 (default: ×1.5)\n"
        "• `/spike min 0.10` — ignore yields < 10% (default: 5%)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📐 How to read results:*\n"
        "• *Implied APY* — fixed rate of the PT\n"
        "• *Underlying APY* — yield of the underlying asset\n"
        "• *Spread* — implied - underlying (margin)\n"
        "• *Borrow cost* — real borrow rate on the money market\n"
        "• *Yield theo* — max estimated yield with leverage\n"
        "• *Score* — composite /100 (spread, TVL, expiry, MM count)\n\n"
        f"_{scans} scans in database._",
        parse_mode="Markdown",
    )


async def loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return
    query = " ".join(context.args) if context.args else ""
    await _run_query(update, query)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return
    query = " ".join(context.args) if context.args else DEFAULT_REPORT_QUERY
    await _run_query(update, query, header="📊 *Status Report*\n")


async def alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    chat_id = update.effective_chat.id
    args = " ".join(context.args) if context.args else ""

    if not args:
        await update.message.reply_text(
            "⚙️ `/alert [asset] [chain] [yield%]`\n\n"
            "Ex: `/alert stable 15%`, `/alert eth 20%`, `/alert 25%`",
            parse_mode="Markdown",
        )
        return

    low = args.lower().strip()

    # Parse yield %
    min_yield = 0.10
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", low)
    if m:
        min_yield = float(m.group(1)) / 100
    else:
        m = re.search(r"(\d+\.\d+)", low)
        if m and float(m.group(1)) < 1:
            min_yield = float(m.group(1))

    asset_filter = next((kw for kw in ["stable", "eth", "btc"] if kw in low), None)
    chain = next((kw for kw in CHAINS if kw in low), None)

    alert_id = add_alert(chat_id=chat_id, asset_filter=asset_filter, chain=chain, min_yield=min_yield)

    await update.message.reply_text(
        f"✅ *Alert #{alert_id}*\n"
        f"Asset: {asset_filter or 'all'} | Chain: {chain or 'all'}\n"
        f"Min theo yield: {fmt_pct(min_yield)}",
        parse_mode="Markdown",
    )


async def alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    alerts = get_alerts(chat_id=update.effective_chat.id)
    if not alerts:
        await update.message.reply_text("No alerts. `/alert stable 15%` to create one.", parse_mode="Markdown")
        return

    lines = ["🔔 *Active alerts:*\n"]
    for a in alerts:
        asset = a.get("asset_filter") or "all"
        chain = a.get("chain") or "all"
        lines.append(f"• *#{a['id']}* — {asset} / {chain} / yield > {fmt_pct(a.get('min_yield', 0))}")
    lines.append("\n`/delalert <id>` to delete.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def spike_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
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

    key = args[0].lower()
    if len(args) < 2:
        await update.message.reply_text("Usage: `/spike <window|multiplier|min> <value>`", parse_mode="Markdown")
        return

    try:
        val = float(args[1])
    except ValueError:
        await update.message.reply_text("Invalid value.")
        return

    key_map = {
        "window": ("spike_window", int(val)),
        "w": ("spike_window", int(val)),
        "multiplier": ("spike_multiplier", val),
        "mult": ("spike_multiplier", val),
        "x": ("spike_multiplier", val),
        "min": ("spike_min_yield", val),
        "min_yield": ("spike_min_yield", val),
    }

    if key not in key_map:
        await update.message.reply_text(f"Unknown key: `{key}`. Use `window`, `multiplier`, or `min`.", parse_mode="Markdown")
        return

    db_key, db_val = key_map[key]
    set_setting(db_key, db_val)
    cfg = get_spike_config()

    await update.message.reply_text(
        f"✅ *Spike config updated*\n\n"
        f"• Window: `{cfg['window']}` scans\n"
        f"• Multiplier: `×{cfg['multiplier']}`\n"
        f"• Min yield: `{fmt_pct(cfg['min_yield'])}`",
        parse_mode="Markdown",
    )


async def delalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
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


# -- Core --

async def _run_query(update, query, header=""):
    global agent
    if not agent:
        agent = LoopScoutAgent()

    thinking = await update.message.reply_text("⏳ Scanning…", parse_mode="Markdown")
    try:
        resp = await agent.run(query)
        if header:
            resp = header + resp
        if len(resp) <= 4096:
            await thinking.edit_text(resp, parse_mode="Markdown")
        else:
            await thinking.edit_text(resp[:4096], parse_mode="Markdown")
            for i in range(4096, len(resp), 4096):
                await update.message.reply_text(resp[i:i+4096], parse_mode="Markdown")
    except Exception as e:
        log.exception("Query failed")
        await thinking.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    """Silent scan every N minutes: scan + save DB + check alerts/spikes. No report."""
    global agent
    if not agent:
        agent = LoopScoutAgent()

    log.info("Scheduled scan")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Run scan silently
    try:
        await agent.run(DEFAULT_REPORT_QUERY)
    except Exception as e:
        log.exception("Scan failed")
        return

    bot: Bot = context.bot

    # Alerts + spikes
    try:
        candidates = get_last_scan_candidates()
        if not candidates:
            return

        for cid, matches in check_alerts_for_candidates(candidates).items():
            if matches:
                lines = [f"🔔 *Alert* — _{now}_\n"]
                for i, c in enumerate(matches[:5], 1):
                    theo = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
                    lines.append(f"*{i}. {c.get('name','?')}* — theo yield: {fmt_pct(theo)}")
                if len(matches) > 5:
                    lines.append(f"_+{len(matches)-5} more_")
                try:
                    await _send_chunks(bot, cid, "\n".join(lines))
                except Exception as e:
                    log.error("Alert to %d: %s", cid, e)

        spikes = detect_yield_spikes(candidates)
        if spikes:
            lines = [f"🚨 *SPIKE* — _{now}_\n", f"_{len(spikes)} market(s) surging:_\n"]
            for i, s in enumerate(spikes[:5], 1):
                mms = s.get('money_markets', [])
                if isinstance(mms, str):
                    mms = [mms] if mms else []
                lines.append(
                    f"*{i}. {s.get('name','?')}*\n"
                    f"   {fmt_pct(s['current_yield'])} (×{s['spike_ratio']:.1f} vs avg {fmt_pct(s['sma_yield'])})\n"
                    f"   🏦 {', '.join(mms) or 'N/A'}"
                )
            if len(spikes) > 5:
                lines.append(f"_+{len(spikes)-5} more_")
            msg = "\n".join(lines)
            for cid in ALLOWED_CHAT_IDS:
                try:
                    await _send_chunks(bot, cid, msg)
                except Exception as e:
                    log.error("Spike to %d: %s", cid, e)
    except Exception as e:
        log.warning("Alert/spike check: %s", e)