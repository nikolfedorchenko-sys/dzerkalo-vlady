"""Публікація: сайт (site/data/news.json + git push), Telegram, Facebook."""
import html
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import requests

log = logging.getLogger("dv")

ROOT = Path(__file__).resolve().parent.parent
NEWS = ROOT / "site" / "data" / "news.json"
SITE_URL = os.environ.get("DV_SITE_URL", "https://dzerkalo-vlady.pages.dev").rstrip("/")
FB_API = "https://graph.facebook.com/v23.0"


def article_url(news_id):
    return f"{SITE_URL}/article?id={news_id}"


# ---------- Сайт ----------

def load_news():
    return json.loads(NEWS.read_text(encoding="utf-8"))


def save_news(data):
    NEWS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique_id(news, wanted):
    base = re.sub(r"[^a-z0-9-]+", "-", wanted.lower()).strip("-")[:60] or "novyna"
    taken = {n["id"] for n in news}
    nid, i = base, 2
    while nid in taken:
        nid, i = f"{base}-{i}", i + 1
    return nid


def site_entry(a, nid, date):
    entry = {
        "id": nid,
        "rubric": a["rubric"],
        "title": a["title"],
        "lead": a["lead"],
        "date": date,
        "impact": {"text": a["impact"]},
        "body": a["body"],
        "sources": a["sources"],
        "auto": True,  # позначка: матеріал зробив автопостинг
    }
    if a.get("opinion"):
        entry["opinion"] = a["opinion"]
    if a.get("urgent"):
        entry["urgent"] = True
    return entry


def expire_urgent(data, now_local, hours):
    """Знімає «Терміново» з автоматичних новин, старших за N годин, щоб червоний рядок не висів вічно."""
    changed = False
    for n in data["news"]:
        if n.get("auto") and n.get("urgent"):
            age = now_local.replace(tzinfo=None) - _parse_local(n["date"])
            if age.total_seconds() > hours * 3600:
                n.pop("urgent")
                changed = True
    return changed


def _parse_local(s):
    from datetime import datetime
    return datetime.fromisoformat(s if "T" in s else s + "T00:00")


def git_push(message):
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)

    git("add", str(NEWS.relative_to(ROOT)))
    if not git("status", "--porcelain", str(NEWS.relative_to(ROOT))).stdout.strip():
        return False
    git("commit", "-m", message)
    for attempt in range(3):
        try:
            git("push")
            return True
        except subprocess.CalledProcessError:
            log.warning("git push не пройшов, підтягую свіжу версію (спроба %d)", attempt + 1)
            git("pull", "--rebase")
    raise RuntimeError("Не вдалося надіслати зміни на GitHub")


def wait_for_site(ids, timeout=420):
    """Чекає, поки Cloudflare Pages викладе нові новини, щоб посилання в постах уже працювали."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            live = requests.get(f"{SITE_URL}/data/news.json", params={"t": int(time.time())}, timeout=20).json()
            if set(ids) <= {n["id"] for n in live.get("news", [])}:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(20)
    log.warning("Сайт не оновився за %d с – публікую в соцмережі все одно", timeout)
    return False


# ---------- Telegram ----------

def _tg(method, token, **kw):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", timeout=60, **kw)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    return data["result"]


def telegram_text(a, rubric_label, url, submit_url):
    """Будова поста за brand/BRAND.md, розділ 9."""
    e = html.escape
    label = "ТЕРМІНОВО" if a.get("urgent") else rubric_label
    src = a["sources"][0] if a["sources"] else None
    parts = [e(label), f"<b>{e(a['title'])}</b>", *[e(p) for p in a["telegram"]]]
    if src:
        parts.append(f'Джерело: <a href="{e(src["url"])}">{e(src["title"])}</a>' if src.get("url")
                     else f"Джерело: {e(src['title'])}")
    sign = f'<a href="{e(url)}">Дзеркало влади</a>'
    if submit_url:
        sign += f' | <a href="{e(submit_url)}">Надіслати новину</a>'
    parts.append(sign)
    return "\n\n".join(parts)


def send_telegram(token, chat_id, text, card_path=None):
    if card_path and len(text) <= 1024:
        with open(card_path, "rb") as f:
            return _tg("sendPhoto", token, data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                       files={"photo": f})
    if card_path:
        with open(card_path, "rb") as f:
            _tg("sendPhoto", token, data={"chat_id": chat_id}, files={"photo": f})
    return _tg("sendMessage", token, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                           "link_preview_options": {"is_disabled": True}})


def notify(token, chat_id, text):
    """Службове повідомлення власнику (звіт про запуск)."""
    if not (token and chat_id):
        return
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
        _tg("sendMessage", token, json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                                        "link_preview_options": {"is_disabled": True}})


# ---------- Facebook ----------

def send_facebook(page_id, token, a, url, card_path):
    message = f"{a['title']}\n\n{a['facebook']}\n\nДетальніше: {url}"
    with open(card_path, "rb") as f:
        r = requests.post(f"{FB_API}/{page_id}/photos", timeout=120,
                          data={"message": message, "access_token": token}, files={"source": f})
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Facebook: {data['error'].get('message')}")
    return data
