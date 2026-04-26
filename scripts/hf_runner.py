"""Hugging Face Spaces runner: DB reset + Telegram bot (webhook mode)."""

import logging

log = logging.getLogger(__name__)


def main():
    # Reset DB to ensure schema is up-to-date on each deployment
    from utils.database import reset_db
    reset_db()
    log.info("Database reset on startup")

    # Start the Telegram bot in webhook mode (blocks)
    from telegram_bot.bot import main as bot_main
    bot_main()


if __name__ == "__main__":
    main()
