#!/usr/bin/env python3
"""Send a short Telegram message to Prem (used for ACTIVE_HANDOFF glances).

Secrets come ONLY from the environment — never hardcode the token anywhere:
  TELEGRAM_BOT_TOKEN   the bot token from BotFather
  TELEGRAM_CHAT_ID     the chat id to send to (see --get-chat-id below)

Usage:
  python scripts/notify_telegram.py "Handoff updated: finished harness eval; next: run sim campaign."
  python scripts/notify_telegram.py --get-chat-id   # after you message the bot once

Stdlib only (urllib) so it can run anywhere without installs. Never raises fatally
into a caller — a missing token or a network hiccup logs to stderr and exits 0,
because a broken notifier must never stop the run.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def get_chat_id() -> int:
    """Print the chat id of the most recent message sent TO the bot.
    Message your bot once (e.g. send it 'hi'), then run this."""
    token = _token()
    if not token:
        print("TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        return 1
    url = API.format(token=token, method="getUpdates")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    results = data.get("result") or []
    if not results:
        print("No updates yet — send your bot a message first, then rerun.",
              file=sys.stderr)
        return 1
    for upd in reversed(results):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            print(chat["id"])
            return 0
    print("No chat id found in updates.", file=sys.stderr)
    return 1


def send(text: str) -> int:
    token = _token()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping notify",
              file=sys.stderr)
        return 0  # never fatal
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(
            API.format(token=token, method="sendMessage"), data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.load(r).get("ok", False)
        print("sent" if ok else "telegram returned not-ok", file=sys.stderr)
    except Exception as exc:  # a notifier failure must not stop the run
        print(f"telegram notify failed (non-fatal): {exc}", file=sys.stderr)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--get-chat-id":
        return get_chat_id()
    if not args:
        print(__doc__)
        return 0
    return send(" ".join(args))


if __name__ == "__main__":
    raise SystemExit(main())
