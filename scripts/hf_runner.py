"""Hugging Face Spaces runner: DB reset + Telegram bot."""

import logging
import socket
import ssl

log = logging.getLogger(__name__)


def diagnose_network() -> None:
    """Diagnose outbound connectivity to identify the root cause of Telegram failures."""
    targets = [
        ("api.telegram.org", 443),
        ("www.google.com", 443),
    ]
    for host, port in targets:
        step = "?"
        try:
            # DNS
            step = f"DNS {host}"
            ip = socket.gethostbyname(host)
            log.info("✅ %s → %s", step, ip)

            # TCP
            step = f"TCP {host}:{port}"
            sock = socket.create_connection((host, port), timeout=15)
            log.info("✅ %s OK", step)

            # TLS
            step = f"TLS {host}:{port}"
            ctx = ssl.create_default_context()
            ssock = ctx.wrap_socket(sock, server_hostname=host)
            cipher = ssock.cipher()
            log.info("✅ %s OK (cipher=%s, TLSv%s)", step, cipher[0], ssock.version())
            ssock.close()
        except Exception as e:
            log.error("❌ %s FAILED: %s: %s", step, type(e).__name__, e)


def main():
    log.info("Network diagnostic...")
    diagnose_network()

    # Reset DB to ensure schema is up-to-date on each deployment
    from utils.database import reset_db
    reset_db()
    log.info("Database reset on startup")

    # Start the Telegram bot (blocks)
    from telegram_bot.bot import main as bot_main
    bot_main()


if __name__ == "__main__":
    main()
