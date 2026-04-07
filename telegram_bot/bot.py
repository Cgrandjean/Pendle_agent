"""Pendle Loop Scout — Telegram bot entry point."""

from __future__ import annotations

import logging
import sys

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
)

from agents.config import TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS, SCAN_INTERVAL_MINUTES
from telegram_bot.handlers import (
    start_handler,
    help_handler,
    loop_handler,
    status_handler,
    alert_handler,
    alerts_handler,
    delalert_handler,
    spike_handler,
    scheduled_scan,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the Telegram bot with long-polling and scheduled reports."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Copy .env.example to .env and fill in your token from @BotFather."
        )
        sys.exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("loop", loop_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("alert", alert_handler))
    app.add_handler(CommandHandler("alerts", alerts_handler))
    app.add_handler(CommandHandler("delalert", delalert_handler))
    app.add_handler(CommandHandler("report", status_handler))
    app.add_handler(CommandHandler("spike", spike_handler))

    # Silent scan every N minutes
    if ALLOWED_CHAT_IDS and SCAN_INTERVAL_MINUTES > 0:
        job_queue = app.job_queue
        job_queue.run_repeating(
            scheduled_scan,
            interval=SCAN_INTERVAL_MINUTES * 60,
            first=30,  # First scan 30 seconds after startup
            name="scheduled_loop_scan",
        )
        logger.info(
            "🔍 Scheduled scan enabled: every %d min to %d chat(s)",
            SCAN_INTERVAL_MINUTES,
            len(ALLOWED_CHAT_IDS),
        )
    else:
        if not ALLOWED_CHAT_IDS:
            logger.warning(
                "⚠️ No ALLOWED_CHAT_IDS set — scheduled scans disabled. "
                "Set ALLOWED_CHAT_IDS in .env to enable."
            )
        if SCAN_INTERVAL_MINUTES <= 0:
            logger.info("Scheduled scans disabled (SCAN_INTERVAL_MINUTES=0)")

    logger.info("🚀 Pendle Loop Scout bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()