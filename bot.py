"""
Telegram AI Bot
===============

A small, production-ready Telegram bot that:

1. Receives messages from Telegram.
2. Sends the latest user message to an OpenAI-compatible chat-completions API.
3. Replies to Telegram with the AI's answer.

Two run modes are supported:

* ``polling`` (default, easiest): the bot pulls new updates from Telegram
  itself. No public URL or HTTPS certificate is required.
* ``webhook``: Telegram pushes updates to your server. Requires a public,
  HTTPS-reachable URL.

All secrets are read from environment variables (optionally loaded from a
``.env`` file). See ``.env.example`` for the full list.

Requires Python 3.10+.
"""

import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# 1. Configuration (all secrets come from environment variables, never code)
# ---------------------------------------------------------------------------

# Load variables from the local `.env` file (if present) so secrets never
# have to live in the source code.
load_dotenv()

# Telegram bot token from @BotFather.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# OpenAI-compatible API settings (override in .env if needed).
# NOTE: the base URL must be the OpenAI-compatible API root. For the
# opencode.ai provider, `https://opencode.ai/zen` needs the `/v1` prefix
# because the actual endpoint is `https://opencode.ai/zen/v1/chat/completions`
# (verified against the live API).
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://opencode.ai/zen/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "public")
AI_MODEL = os.getenv("AI_MODEL", "big-pickle")

# "Personality" of the AI: concise, helpful, polite.
AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "You are a helpful, polite assistant. Keep your answers concise and clear.",
)

# Run mode: "polling" (recommended, easiest) or "webhook".
BOT_MODE = os.getenv("BOT_MODE", "polling")

# Webhook settings - only needed when BOT_MODE="webhook".
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")        # public HTTPS URL, e.g. https://bot.example.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # random string guarding the webhook
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))

# Telegram refuses to send single messages longer than 4096 characters.
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

if not TELEGRAM_BOT_TOKEN:
    raise SystemExit(
        "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
    )

# ---------------------------------------------------------------------------
# 2. Logging - real errors go to the console, users only see friendly text
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 3. AI request (direct HTTP call to an OpenAI-compatible API)
# ---------------------------------------------------------------------------
# OpenAI-compatible servers expose `POST {base_url}/chat/completions`.
# We use httpx (already a dependency of python-telegram-bot) so no extra SDK
# is required. If you prefer the official `openai` package instead, replace
# the body of `ask_ai` with something like:
#
#     from openai import AsyncOpenAI
#     client = AsyncOpenAI(base_url=AI_BASE_URL, api_key=AI_API_KEY)
#     response = await client.chat.completions.create(
#         model=AI_MODEL,
#         messages=[
#             {"role": "system", "content": AI_SYSTEM_PROMPT},
#             {"role": "user", "content": user_text},
#         ],
#         temperature=0.7,
#         max_tokens=1024,
#     )
#     content = response.choices[0].message.content


async def ask_ai(user_text: str) -> str:
    """Send the latest user message to the AI and return its text reply."""
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

    # Timeout covers the whole request. `raise_for_status()` turns HTTP errors
    # (401, 429, 500, ...) into exceptions we can log on the console.
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{AI_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    # Parse the standard OpenAI response shape.
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"No choices in AI response: {data}")
    content = (choices[0].get("message") or {}).get("content") or ""
    content = content.strip()
    if not content:
        raise RuntimeError("AI returned an empty reply.")

    return content


# ---------------------------------------------------------------------------
# 4. Telegram handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start - short welcome message."""
    await update.message.reply_text(
        "Hello! I am an AI-powered bot.\n\n"
        "Send me any message and I will reply using an AI model. "
        "Type /help to see what I can do."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help - explain what the bot does."""
    await update.message.reply_text(
        "How I work:\n"
        "1. You send me a message\n"
        "2. I forward it to the AI model\n"
        "3. I reply with the model's answer\n\n"
        f"Active model: {AI_MODEL}\n\n"
        "Commands:\n"
        "/start - welcome message\n"
        "/help  - this help"
    )


async def reply_to_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to every normal (non-command) text message."""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    if not user_text:
        return

    # Show a typing indicator while the AI is thinking.
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        answer = await ask_ai(user_text)
    except Exception as exc:  # intentionally catch everything
        # Log the real error on the console...
        logger.exception(
            "AI request failed (chat_id=%s): %s", update.effective_chat.id, exc
        )
        # ...but only show a friendly message to the user.
        await update.message.reply_text(
            "Sorry, I could not get a reply from the AI right now. "
            "Please try again in a moment."
        )
        return

    # Telegram hard-limits messages to 4096 chars, so split long answers.
    limit = TELEGRAM_MAX_MESSAGE_LENGTH - 100
    for chunk in _split_text(answer, limit):
        await update.message.reply_text(chunk)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any command we do not recognise."""
    await update.message.reply_text(
        "Sorry, I don't know that command. Type /help to see what I can do."
    )


def _split_text(text: str, limit: int) -> list[str]:
    """Split text into chunks of at most `limit` characters."""
    return [text[i : i + limit] for i in range(0, len(text), limit)]


# ---------------------------------------------------------------------------
# 5. Application setup and entry point
# ---------------------------------------------------------------------------

def _keepalive_handler(logger: logging.Logger):
    """Build a minimal HTTP handler that answers every request with 200 OK."""
    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            logger.debug("keepalive: %s", args)
    return _HealthHandler


def start_keepalive_server() -> None:
    """Serve a tiny HTTP endpoint on $PORT to keep free hosts awake.

    Free tiers (e.g. Render) spin services down after minutes of inactivity.
    A polling bot never receives inbound requests, so it would go to sleep.
    This endpoint answers with 200 OK so a free uptime monitor (e.g.
    UptimeRobot) pinging `/ping` every few minutes keeps the service alive.
    Only activated when the host injects a $PORT (i.e. in the cloud).
    """
    port = int(os.getenv("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), _keepalive_handler(logger))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Keep-alive HTTP server listening on port %s", port)

def build_application() -> Application:
    """Create the Telegram application and register every handler."""
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Order matters: command handlers are checked before message handlers.
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    # Every plain text message goes to the AI (commands are excluded).
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, reply_to_message)
    )
    # Anything that looks like a command but isn't handled above:
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    return application


def run_webhook(application: Application) -> None:
    """Start the bot in webhook mode (needs a public HTTPS URL)."""
    # Register the webhook with Telegram. `Bot.set_webhook` is a coroutine.
    asyncio.run(
        application.bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
        )
    )
    # Depending on the python-telegram-bot version, `Application.run_webhook()`
    # is either a coroutine or a blocking method - handle both cases.
    result = application.run_webhook(
        listen="0.0.0.0",
        port=WEBHOOK_PORT,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
    )
    if asyncio.iscoroutine(result):
        asyncio.run(result)


def main() -> None:
    """Entry point: pick the run mode from the BOT_MODE variable."""
    # On cloud hosts a $PORT is injected; expose a keep-alive endpoint so the
    # free tier does not put the polling bot to sleep.
    if os.getenv("PORT"):
        start_keepalive_server()

    application = build_application()

    if BOT_MODE == "webhook":
        if not WEBHOOK_URL or not WEBHOOK_SECRET:
            raise SystemExit(
                "BOT_MODE=webhook requires WEBHOOK_URL and WEBHOOK_SECRET to be set."
            )
        run_webhook(application)
    else:
        # Polling = easiest setup. No server, no public URL, no certificate.
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
