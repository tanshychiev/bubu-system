import json
import mimetypes
import uuid
import urllib.parse
import urllib.request

from django.conf import settings


def _get_bot_info(chat_id=None, bot_token=None):
    bot_token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")

    bot_token = str(bot_token).strip()
    chat_id = str(chat_id).strip()

    return bot_token, chat_id


def send_telegram_message(text, chat_id=None, bot_token=None, message_thread_id=None):
    bot_token, chat_id = _get_bot_info(chat_id=chat_id, bot_token=bot_token)

    if not bot_token or not chat_id:
        print("Telegram not sent: missing bot token or chat id.")
        print("BOT TOKEN:", bot_token)
        print("CHAT ID:", chat_id)
        return False

    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
        }

        if message_thread_id:
            payload["message_thread_id"] = str(message_thread_id)

        data = urllib.parse.urlencode(payload).encode("utf-8")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        request = urllib.request.Request(url, data=data, method="POST")
        response = urllib.request.urlopen(request, timeout=10)

        print("Telegram message sent successfully.")
        print(response.read().decode("utf-8"))

        return True

    except Exception as e:
        print("Telegram message send error:", e)
        return False


def send_telegram_photo(photo_path, caption="", chat_id=None, bot_token=None, message_thread_id=None):
    bot_token, chat_id = _get_bot_info(chat_id=chat_id, bot_token=bot_token)

    if not bot_token or not chat_id:
        print("Telegram photo not sent: missing bot token or chat id.")
        print("BOT TOKEN:", bot_token)
        print("CHAT ID:", chat_id)
        return False

    if not photo_path:
        print("Telegram photo not sent: missing photo path.")
        return False

    try:
        boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

        mime_type = mimetypes.guess_type(photo_path)[0] or "application/octet-stream"
        filename = photo_path.split("\\")[-1].split("/")[-1]

        body = bytearray()

        def add_field(name, value):
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        def add_file(name, file_path):
            with open(file_path, "rb") as f:
                file_data = f.read()

            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8")
            )
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
            body.extend(file_data)
            body.extend(b"\r\n")

        add_field("chat_id", chat_id)

        if message_thread_id:
            add_field("message_thread_id", message_thread_id)

        if caption:
            add_field("caption", caption[:1000])

        add_file("photo", photo_path)

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        request = urllib.request.Request(
            url,
            data=bytes(body),
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

        response = urllib.request.urlopen(request, timeout=20)

        print("Telegram photo sent successfully.")
        print(response.read().decode("utf-8"))

        return True

    except Exception as e:
        print("Telegram photo send error:", e)
        return False


def send_telegram_photo_album(photo_paths, caption="", chat_id=None, bot_token=None, message_thread_id=None):
    """
    Send many photos as one Telegram album.
    Caption shows under the first photo only.
    Telegram supports max 10 media per album.
    """
    bot_token, chat_id = _get_bot_info(chat_id=chat_id, bot_token=bot_token)

    if not bot_token or not chat_id:
        print("Telegram album not sent: missing bot token or chat id.")
        print("BOT TOKEN:", bot_token)
        print("CHAT ID:", chat_id)
        return False

    clean_paths = []

    for path in photo_paths:
        if path:
            clean_paths.append(path)

    clean_paths = clean_paths[:10]

    if not clean_paths:
        print("Telegram album not sent: no photos.")
        return False

    # Telegram sendMediaGroup needs at least 2 photos.
    # If only 1 photo, send normal photo.
    if len(clean_paths) == 1:
        return send_telegram_photo(
            photo_path=clean_paths[0],
            caption=caption,
            chat_id=chat_id,
            bot_token=bot_token,
            message_thread_id=message_thread_id,
        )

    try:
        boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
        url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"

        body = bytearray()
        media = []

        def add_field(name, value):
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        def add_file(field_name, file_path):
            mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            filename = file_path.split("\\")[-1].split("/")[-1]

            with open(file_path, "rb") as f:
                file_data = f.read()

            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
            )
            body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
            body.extend(file_data)
            body.extend(b"\r\n")

        add_field("chat_id", chat_id)

        if message_thread_id:
            add_field("message_thread_id", message_thread_id)

        for index, photo_path in enumerate(clean_paths):
            field_name = f"photo{index}"

            media_item = {
                "type": "photo",
                "media": f"attach://{field_name}",
            }

            if index == 0 and caption:
                media_item["caption"] = caption[:1000]

            media.append(media_item)

        add_field("media", json.dumps(media))

        for index, photo_path in enumerate(clean_paths):
            add_file(f"photo{index}", photo_path)

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        request = urllib.request.Request(
            url,
            data=bytes(body),
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

        response = urllib.request.urlopen(request, timeout=30)

        print("Telegram album sent successfully.")
        print(response.read().decode("utf-8"))

        return True

    except Exception as e:
        print("Telegram album send error:", e)
        return False


def send_telegram_photos(photo_paths, caption="", chat_id=None, bot_token=None, message_thread_id=None):
    """
    Old function name kept for compatibility.
    Now it sends as album instead of one by one.
    """
    return send_telegram_photo_album(
        photo_paths=photo_paths,
        caption=caption,
        chat_id=chat_id,
        bot_token=bot_token,
        message_thread_id=message_thread_id,
    )