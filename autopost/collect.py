"""Збір новин: RSS-стрічки сайтів і публічні Telegram-канали (сторінка t.me/s/<канал>)."""
import calendar
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import trafilatura
from bs4 import BeautifulSoup

log = logging.getLogger("dv")

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "uk,en;q=0.8",
}
TIMEOUT = 25


def _key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _clean(html_or_text, limit=None):
    text = BeautifulSoup(html_or_text or "", "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:limit] if limit else text


def fetch_rss(src, since):
    r = requests.get(src["url"], headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        when = datetime.fromtimestamp(calendar.timegm(t), timezone.utc) if t else None
        if when and when < since:
            continue
        link = e.get("link", "")
        title = _clean(e.get("title", ""))
        if not title or not link:
            continue
        items.append({
            "key": _key(link),
            "source": src["name"],
            "kind": src.get("kind", "media"),
            "title": title,
            "summary": _clean(e.get("summary", ""), 500),
            "url": link,
            "published": (when or datetime.now(timezone.utc)).isoformat(),
        })
    return items


def fetch_telegram(src, since):
    channel = src["channel"]
    r = requests.get(f"https://t.me/s/{channel}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for msg in soup.select(".tgme_widget_message[data-post]"):
        post = msg["data-post"]  # "канал/123"
        tm = msg.select_one("time[datetime]")
        when = datetime.fromisoformat(tm["datetime"]) if tm else None
        if when and when < since:
            continue
        body = msg.select_one(".tgme_widget_message_text")
        if not body:
            continue
        text = body.get_text("\n", strip=True)
        if len(text) < 60:  # голі репости й підписи до фото без змісту
            continue
        links = [a["href"] for a in body.select("a[href]") if a["href"].startswith("http")]
        # Фото з допису (Telegram віддає його як фон-картинку)
        photo = msg.select_one(".tgme_widget_message_photo_wrap[style]")
        m = re.search(r"url\('([^']+)'\)", photo["style"]) if photo else None
        first_line = text.split("\n", 1)[0]
        items.append({
            "key": _key("tg:" + post),
            "source": src["name"],
            "kind": src.get("kind", "official"),
            "title": first_line[:200],
            "summary": re.sub(r"\s+", " ", text)[:500],
            "full_text": text[:6000],
            "links": links[:5],
            "image": m.group(1) if m else "",
            "url": f"https://t.me/{post}",
            "published": (when or datetime.now(timezone.utc)).isoformat(),
        })
    return items


def collect(sources, hours):
    """Усі свіжі матеріали з усіх джерел. Збій одного джерела не зупиняє решту."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, errors = [], []
    for src in sources:
        try:
            got = fetch_telegram(src, since) if "channel" in src else fetch_rss(src, since)
            log.info("%-28s %3d свіжих", src["name"], len(got))
            items.extend(got)
        except Exception as e:  # noqa: BLE001 – одне джерело не має валити весь запуск
            log.warning("Джерело «%s» не відповіло: %s", src["name"], e)
            errors.append(f"{src['name']}: {e}")
    return items, errors


def download_photo(url, path, min_w=900):
    """Завантажує фото з офіційного джерела; відкидає дрібні картинки й логотипи. Повертає True, якщо годиться."""
    from io import BytesIO
    from PIL import Image
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.info("Фото з джерела не підійшло (%s): %s", url, e)
        return False
    w, h = img.size
    if w < min_w or not 1.2 <= w / h <= 2.4:  # логотипи й квадратні заглушки – не фото події
        log.info("Фото з джерела не підійшло: %dx%d", w, h)
        return False
    img.thumbnail((1600, 1600))
    img.save(path, "JPEG", quality=85, optimize=True)
    return True


def full_text(item):
    """Повний текст матеріалу, щоб Claude писав пост з першоджерела, а не з заголовка."""
    if item.get("full_text"):
        return item["full_text"]
    try:
        r = requests.get(item["url"], headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        text = trafilatura.extract(r.text, url=item["url"], include_comments=False) or ""
        if item.get("kind") == "official" and not item.get("image"):
            og = BeautifulSoup(r.text, "html.parser").select_one('meta[property="og:image"][content]')
            if og:
                item["image"] = requests.compat.urljoin(item["url"], og["content"])
    except Exception as e:  # noqa: BLE001
        log.warning("Не вдалося відкрити %s: %s", item["url"], e)
        text = ""
    return (text or item.get("summary", ""))[:8000]
