"""Показує chat id людей і каналів, які писали ботові або де бот став адміном.

Як користуватися: впишіть TG_BOT_TOKEN в autopost/.env, напишіть ботові будь-що в особисті
і додайте бота адміном у канали, потім запустіть:  python autopost/tg_ids.py
"""
import os
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
env = Path(__file__).resolve().parent / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

token = os.environ.get("TG_BOT_TOKEN")
if not token:
    sys.exit("Немає TG_BOT_TOKEN в autopost/.env")

updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
seen = {}
for u in updates.get("result", []):
    for key in ("message", "channel_post", "my_chat_member", "edited_message"):
        chat = (u.get(key) or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat
for cid, chat in seen.items():
    name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
    user = f"@{chat['username']}" if chat.get("username") else ""
    print(f"{chat['type']:<10} {cid:<16} {name} {user}")
if not seen:
    print("Порожньо: напишіть ботові в особисті або додайте його адміном у канал і запустіть ще раз.")
