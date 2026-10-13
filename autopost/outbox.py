"""Відправка: надсилає в Telegram пости, підготовлені запуском, у свій час (з інтервалом 10–20 хвилин).
Окремий крок GitHub після запуску (.github/workflows/autopost.yml, job «outbox»): чекає до часу кожного поста
й надсилає його. Наступні запуски на нього не чекають."""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import publish  # noqa: E402

OUTBOX = HERE / "outbox"
log = logging.getLogger("dv")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    items = sorted((json.loads(f.read_text(encoding="utf-8")) for f in OUTBOX.glob("*.json")),
                   key=lambda q: q["due"]) if OUTBOX.exists() else []
    if not items:
        log.info("Відправляти нічого")
        return
    mode = os.environ.get("DV_MODE", "test").lower()
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat = os.environ.get("TG_CHANNEL_ID" if mode == "live" else "TG_TEST_CHANNEL_ID", "")
    errors = []
    for q in items:
        wait = (datetime.fromisoformat(q["due"]) - datetime.now(timezone.utc)).total_seconds()
        if wait > 0:
            log.info("Чекаю %d хв до поста «%s»", wait // 60, q["title"])
            time.sleep(wait)
        card = OUTBOX / q["card"] if q.get("card") else None
        try:
            publish.send_telegram(token, chat, q["text"], card if card and card.exists() else None)
            log.info("Telegram: %s", q["title"])
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram не прийняв «%s»: %s", q["title"], e)
            errors.append(f"Telegram не прийняв пост «{escape(q['title'])}»: {escape(str(e))}")
    if errors:
        publish.notify(token, os.environ.get("TG_ADMIN_CHAT_ID", ""),
                       "Дзеркало влади · відправка в Telegram\n\n" + "\n\n".join(errors))


if __name__ == "__main__":
    main()
