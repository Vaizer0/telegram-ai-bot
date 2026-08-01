# Telegram AI Bot

A simple, production-ready Telegram bot that forwards every message you send
it to an OpenAI-compatible chat-completions API and replies with the model's
answer.

## Features

- Replies to every normal text message
- `/start` and `/help` commands
- Typing indicator while the AI is thinking
- Graceful error handling (friendly message in Telegram, real error in console)
- Long answers are split to respect Telegram's 4096-character limit
- Secrets loaded from a `.env` file, never hardcoded
- Runs in **polling** mode by default (easiest setup), webhook mode optional

## Project structure

```
telegram-ai-bot/
├── bot.py                    # the whole bot
├── requirements.txt          # Python dependencies
├── .env.example              # template for your secrets
├── .gitignore
├── railway.json              # Railway deployment config
├── render.yaml               # Render deployment blueprint (fallback)
└── .github/workflows/ci.yml  # GitHub Actions CI (syntax + import check)
```

## Requirements

- Python 3.10 or newer

## Setup & run

### Android (Termux)

```bash
# 1. Update Termux and install Python
pkg update && pkg upgrade
pkg install python

# 2. Go to the project folder
cd telegram-ai-bot

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create your .env from the template
cp .env.example .env

# 5. (Optional) edit .env to change your token / model / system prompt
nano .env

# 6. Run the bot (keep this terminal open; Ctrl+C to stop)
python bot.py
```

### Windows

```powershell
# 1. Install Python 3.10+ from https://www.python.org/downloads/
#    Tick "Add Python to PATH" during installation.

# 2. Open a terminal (cmd or PowerShell) in the project folder
cd telegram-ai-bot

# 3. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Create your .env from the template
copy .env.example .env

# 5. (Optional) edit .env to change your token / model / system prompt
notepad .env

# 6. Run the bot (keep this window open; Ctrl+C to stop)
python bot.py
```

## Configuration

| Variable             | Required | Description                                      | Default                        |
| -------------------- | -------- | ------------------------------------------------ | ------------------------------ |
| `TELEGRAM_BOT_TOKEN` | yes      | Bot token from @BotFather                        | —                              |
| `AI_BASE_URL`        | no       | OpenAI-compatible API base URL                   | `https://opencode.ai/zen/v1`   |
| `AI_API_KEY`         | no       | API key (may be `public` for some providers)     | `public`                       |
| `AI_MODEL`           | no       | Model name                                       | `big-pickle`                   |
| `AI_SYSTEM_PROMPT`   | no       | AI personality/instructions                      | concise + polite assistant     |
| `BOT_MODE`           | no       | `polling` (default) or `webhook`                 | `polling`                      |

Webhook-only variables: `WEBHOOK_URL`, `WEBHOOK_SECRET`, `WEBHOOK_PORT`.

## How it works

1. The user sends a message to the bot in Telegram.
2. The bot shows a typing indicator and sends the message to
   `POST {AI_BASE_URL}/chat/completions` (OpenAI-compatible format) together
   with the system prompt. With `AI_BASE_URL=https://opencode.ai/zen/v1` the
   request goes to `https://opencode.ai/zen/v1/chat/completions`.
3. The reply text is sent back to the chat. Long replies are split into
   multiple messages.

> **Security:** the real token and any other secrets must only ever live in
> `.env` (local) or in your hosting provider's environment variables — never
> in code, commits, or logs. `.env` is ignored by Git.

## Deploy to the cloud (runs 24/7, no phone needed)

The bot uses polling, so it does not need a public URL. Any platform that can
run a long-running Python process works. **Railway is recommended** because its
free tier keeps services running.

### Railway (recommended)

1. Push this repository to GitHub (see below).
2. Sign up at https://railway.app and create a new project.
3. Choose **Deploy from GitHub repo** and select this repository
   (Railway auto-deploys on every push to `main`).
4. Add the environment variables in the **Variables** tab:
   `TELEGRAM_BOT_TOKEN`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` (same values
   as in `.env`).
5. The included `railway.json` starts `python bot.py`, disables the HTTP
   healthcheck (the bot exposes no web server), and restarts on failure.

### Render (fallback)

1. Push the repository to GitHub.
2. New **Background Worker** service, connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Add the same environment variables.
6. Use the included `render.yaml` as a blueprint for reproducibility.

> Note: Render free instances may pause after inactivity; Railway keeps
> always-on services and is the better fit for a 24/7 bot.

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR: it installs the dependencies,
compiles the code, and smoke-tests that the bot module imports cleanly.

## Deploying from your machine

```bash
git init                                # if not already a repo
git add .
git commit -m "Add Telegram AI bot"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

Then follow the Railway/Render steps above. The bot keeps working even if your
phone is off, because it runs on the cloud host.

## Switching to webhook mode

Polling is recommended for the easiest setup. If you later want webhooks:

- Set `BOT_MODE=webhook` in `.env`.
- Set `WEBHOOK_URL` to a public HTTPS URL that points to your bot server
  (you will also need a TLS proxy such as nginx or a tunnel).
- Set a long random `WEBHOOK_SECRET`.
- Restart the bot.

## Troubleshooting

- **`TELEGRAM_BOT_TOKEN is not set`** — copy `.env.example` to `.env`.
- **Bot does not reply** — check the console output; real errors are logged
  there. Also make sure the bot token is valid and the AI endpoint is reachable.
- **401/403 errors from the AI API** — wrong `AI_API_KEY` or the provider
  requires a different key.
