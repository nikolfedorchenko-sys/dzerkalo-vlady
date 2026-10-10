"""Фото до новини: спершу офіційне фото з джерела (пресслужба), інакше – з фотобанку за темою."""
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

import collect

log = logging.getLogger("dv")

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BANK = yaml.safe_load((Path(__file__).resolve().parent / "photobank.yaml").read_text(encoding="utf-8"))

THEMES = {
    "rada": "Верховна Рада",
    "uriad": "уряд, міністерства",
    "kmda": "Київрада, КМДА, мер",
    "ofis": "Офіс Президента, Президент",
    "energy": "енергетика, світло, відключення, ТЕЦ",
    "transport": "транспорт, метро, дороги",
    "money": "гроші, бюджет, податки, ціни, банки",
    "justice": "суди, НАБУ, корупція, правоохоронці",
    "city": "Київ загалом, міське життя",
    "construction": "забудова, будівництво",
    "housing": "житло, комунальні послуги, квартали",
    "bezpeka": "удари, тривоги, безпека, оборона",
}


def _official(texts, out_path):
    """Фото з офіційного джерела новини (сайт чи Telegram-канал органу влади)."""
    for t in texts:
        url = t.get("image")
        if t.get("kind") != "official" or not url:
            continue
        url = url.strip().replace("/uploads/logos_middle/", "/uploads/logos/")  # сайт Ради: більша версія
        if collect.download_photo(url, out_path):
            return {"path": out_path, "author": t["source"], "license": "", "official": True}
    return None


def _from_bank(theme, state):
    used = state.setdefault("photo_used", {})
    pool = [p for p in BANK if p["theme"] == theme] or [p for p in BANK if p["theme"] == "city"]
    # Найдавніше використане – щоб фото не повторювалися підряд
    p = min(pool, key=lambda x: used.get(x["file"], ""))
    used[p["file"]] = datetime.now(timezone.utc).isoformat()
    return {"path": SITE / p["file"], "file": p["file"], "author": p["author"], "license": p["license"],
            "official": False}


def pick(a, texts, state, out_dir):
    """Повертає фото для новини a: path (локальний файл), author, license, official."""
    photo = _official(texts, out_dir / f"{a['id']}-src.jpg")
    if photo:
        log.info("Фото: з джерела (%s)", photo["author"])
        return photo
    photo = _from_bank(a.get("photo_theme", "city"), state)
    log.info("Фото: з фотобанку (%s)", photo["file"])
    return photo


def credit(photo):
    if photo["official"]:
        return f"{photo['author']} (пресслужба)"
    return ", ".join(x for x in (photo["author"], photo["license"]) if x)


def for_site(a, photo):
    """Блок photo для статті на сайті; офіційне фото копіюється в site/assets/photos/auto/."""
    if photo["official"]:
        rel = f"assets/photos/auto/{a['id']}.jpg"
        (SITE / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(photo["path"], SITE / rel)
    else:
        rel = photo["file"]
    entry = {"file": rel, "alt": a["title"], "author": photo["author"], "license": photo["license"]}
    if photo["official"]:
        entry["author"], entry["license"] = f"{photo['author']} (пресслужба)", ""
    return entry
