import json
import urllib.parse
import urllib.request
import urllib.error

from django.conf import settings


def send_staff_telegram_message(text):
    bot_token = getattr(settings, "STAFF_TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "STAFF_TELEGRAM_CHAT_ID", "")

    print("STAFF BOT TOKEN EXISTS:", bool(bot_token))
    print("STAFF CHAT ID:", chat_id)

    if not bot_token:
        print("❌ STAFF_TELEGRAM_BOT_TOKEN is empty")
        return False

    if not chat_id:
        print("❌ STAFF_TELEGRAM_CHAT_ID is empty")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    data = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "false",
    }

    try:
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=encoded_data,
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)

            print("✅ TELEGRAM RESULT:", result)
            return bool(result.get("ok"))

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print("❌ TELEGRAM HTTP ERROR:", e.code, error_body)
        return False

    except Exception as e:
        print("❌ TELEGRAM ERROR:", str(e))
        return False