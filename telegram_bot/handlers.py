"""Telegram bot handlers."""

import logging
import re
from datetime import datetime, timezone

from telegram import Update, Bot
from telegram.ext import ContextTypes

from const import CHAINS, HELP, SPIKE_KEY_MAP, MSG_MAX_LENGTH
from agents.loop_scout_agent import LoopScoutAgent
from agents.config import ALLOWED_CHAT_IDS
from utils.database import (
    add_alert, get_alerts, delete_alert,
    check_alerts_for_candidates, get_scan_count,
    get_last_scan_candidates, detect_yield_spikes,
    get_spike_config, set_setting,
    reset_db, export_db_summary,
)
from utils.formatting import fmt_pct, format_candidate

log = logging.getLogger(__name__)

_agent = None


def _get_agent() -> LoopScoutAgent:
    global _agent
    if _agent is None:
        _agent = LoopScoutAgent()
    return _agent


async def _send_chunks(bot: Bot, chat_id: int, text: str):
    while text:
        chunk, text = text[:MSG_MAX_LENGTH], text[MSG_MAX_LENGTH:]
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")


def _is_authorized(chat_id: int) -> bool:
    return not ALLOWED_CHAT_IDS or chat_id in ALLOWED_CHAT_IDS


def _parse_loop_args(args: list[str]) -> tuple[int, str | None, str | None]:
    """Parse /loop command args. Returns (count, asset, chain)."""
    count = 5
    asset = None
    chain = None

    args_low = [a.lower() for a in args]
    for a in args:
        if a.isdigit():
            count = min(int(a), 20)
            break

    for a in args_low:
        if a in ("stable", "eth", "btc"):
            asset = a
            break

    for a in args_low:
        if a in CHAINS:
            chain = a
            break

    return count, asset, chain


def _parse_alert_args(args: str) -> tuple:
    """Parse alert command arguments. Returns (asset_filter, chain, min_yield)."""
    low = args.lower().strip()

    min_yield = 0.15
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
    lines = [f"🔔 *Alert* — _{now}_\n"]
    for i, c in enumerate(matches[:5], 1):
        theo = c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0
        lines.append(f"*{i}. {c.get('name', '?')}* — theo yield: {fmt_pct(theo)}")
    if len(matches) > 5:
        lines.append(f"_+{len(matches) - 5} more_")
    return "\n".join(lines)


def _format_spike_entry(index: int, spike: dict) -> str:
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
    lines = [f"🚨 *SPIKE* — _{now}_\n", f"_{len(spikes)} market(s) surging:_\n"]
    for i, s in enumerate(spikes[:5], 1):
        lines.append(_format_spike_entry(i, s))
    if len(spikes) > 5:
        lines.append(f"_+{len(spikes) - 5} more_")
    return "\n".join(lines)


# -- Command Handlers --

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if not _is_authorized(update.effective_chat.id):
        return
    scans = get_scan_count()
    await update.message.reply_text(f"{HELP}\n\n_{scans} scans in database._", parse_mode="Markdown")


async def loop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update.effective_chat.id):
        return

    args = list(context.args) if context.args else []
    count, asset, chain = _parse_loop_args(args)

    thinking = await update.message.reply_text("⏳ Scanning…", parse_mode="Markdown")
    agent = _get_agent()

    try:
        resp = await agent.run(count=count, asset=asset, chain=chain)
        if len(resp) <= MSG_MAX_LENGTH:
            await thinking.edit_text(resp, parse_mode="Markdown")
        else:
            await thinking.edit_text(resp[:MSG_MAX_LENGTH], parse_mode="Markdown")
            for i in range(MSG_MAX_LENGTH, len(resp), MSG_MAX_LENGTH):
                await update.message.reply_text(resp[i:i + MSG_MAX_LENGTH], parse_mode="Markdown")
    except Exception as e:
        log.exception("Query failed")
        await thinking.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    candidates.sort(key=lambda c: c.get("theoretical_max_yield") or c.get("theoretical_yield") or 0, reverse=True)
    top = candidates[:10]

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
    if not _is_authorized(update.effective_chat.id):
        return

    alerts = get_alerts(chat_id=update.effective_chat.id)
    if not alerts:
        await update.message.reply_text("No alerts. `/alert stable 15%` to create one.", parse_mode="Markdown")
        return

    lines = ["🔔 *Active alerts:*\n"]
    for a in alerts:
        lines.append(f"• *#{a['id']}* — {a.get('asset_filter') or 'all'} / {a.get('chain') or 'all'} / "
                     f"yield > {fmt_pct(a.get('min_yield', 0))}")
    lines.append("\n`/delalert <id>` to delete.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def spike_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Usage: `/spike <window|multiplier|min> <value>`", parse_mode="Markdown")
        return

    key = args[0].lower()
    if key not in SPIKE_KEY_MAP:
        await update.message.reply_text(f"Unknown key: `{key}`. Use `window`, `multiplier`, or `min`.", parse_mode="Markdown")
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
            lines.append(f"   {i}. {c.get('name', '?')}{vault_info} — {fmt_pct(c.get('theoretical_yield', 0))}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def resetdb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


# -- Scheduled Scan --

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    """Silent scan every N minutes: scan + save DB + check alerts/spikes."""
    agent = _get_agent()
    log.info("Scheduled scan")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        await agent.run(count=5, asset="stable")
    except Exception as e:
        log.exception("Scan failed")
        return

    bot: Bot = context.bot

    try:
        candidates = get_last_scan_candidates()
        if not candidates:
            return

        for cid, matches in check_alerts_for_candidates(candidates).items():
            if matches:
                msg = _format_alert_message(now, matches)
                try:
                    await _send_chunks(bot, cid, msg)
                except Exception as e:
                    log.error("Alert to %d: %s", cid, e)

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
