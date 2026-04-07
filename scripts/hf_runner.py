"""Hugging Face Spaces runner: health server on 7860 + Telegram bot."""

import asyncio
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Dummy HTTP server to satisfy HF Spaces port requirement."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Pendle Loop Scout running")

    def log_message(self, format, *args):
        pass  # Suppress logs


def run_health_server(port=7860):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info("Health server on port %d", port)
    server.serve_forever()


def main():
    # Start health server in background thread
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()

    # Start the Telegram bot (blocks)
    from telegram_bot.bot import main as bot_main
    bot_main()


if __name__ == "__main__":
    main()