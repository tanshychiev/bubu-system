"""Telegram attendance alerts. No tokens are stored in source code."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from django.conf import settings

logger = logging.getLogger(__name__)
# Small shared pool: prevent Telegram network requests from blocking check-in.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bubu-telegram")


def send_staff_telegram_message(text):
    token = getattr(settings, "STAFF_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = str(getattr(settings, "STAFF_TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        logger.error("BUBU Telegram not configured: set STAFF_TELEGRAM_BOT_TOKEN and STAFF_TELEGRAM_CHAT_ID")
        return False
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    thread_id = str(getattr(settings, "STAFF_TELEGRAM_THREAD_ID", "")).strip()
    if thread_id:
        data["message_thread_id"] = thread_id
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.load(resp)
        if result.get("ok"):
            return True
        logger.error("BUBU Telegram API refused message: %s", result.get("description", "Unknown error"))
    except urllib.error.HTTPError as err:
        # Do not log the bot token or a URL containing the token.
        try:
            detail = json.loads(err.read().decode("utf-8")).get("description", "")
        except (ValueError, UnicodeDecodeError):
            detail = "Unable to decode Telegram error"
        logger.error("BUBU Telegram send failed (%s): %s", err.code, detail)
    except Exception as err:
        logger.error("BUBU Telegram network error: %s", type(err).__name__)
    return False


def send_staff_telegram_async(text):
    """Best-effort nonblocking notification. Production reliability requires a durable outbox/worker."""
    try:
        _executor.submit(send_staff_telegram_message, text)
        return True
    except RuntimeError:
        logger.exception("BUBU Telegram worker unavailable")
        return False
