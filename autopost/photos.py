"""Фото до новини. Порядок:
1) офіційне фото з джерела новини (пресслужба Ради, КМДА, ОП…) – найсвіжіше і точно про подію;
2) пошук на Wikimedia Commons за запитом, який Claude складає під конкретну новину (лише вільні ліцензії);
3) фотобанк за темою – тільки якщо перші два нічого не дали.
Кожне фото використовується лише один раз: використані запам'ятовуються в state["photo_used"].
"""
import html
import logging
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests
import yaml
from PIL import Image

import collect

log = logging.getLogger("dv")

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BANK = yaml.safe_load((Path(__file__).resolve().parent / "photobank.yaml").read_text(encoding="utf-8"))
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "DVPhotobank/1.0 (https://dzerkalo-vlady.com; editorial photo search)"}
FREE = re.compile(r"^(CC0|CC BY(-SA)? [0-9.]+|Public domain|PD.*)$", re.I)
# Схеми, карти, герби, логотипи, документи – не фото події
NOT_PHOTO = re.compile(r"map|logo|coat of arms|flag|diagram|chart|scheme|svg|seal|emblem|герб|прапор|карта|схема"
                       r"|banknote|coin|stamp|poster|document|plaque", re.I)

# Жодних фото з Росії чи Білорусі: прапори, вивіски, вибори РФ тощо. Перевіряємо назву, опис і категорії файлу.
FOREIGN = re.compile(r"russia|russian|moscow|st\.? petersburg|saint petersburg|soviet|ussr|kremlin|belarus|minsk"
                     r"|росси|россия|москв|петербург|кремл|ссср|белорус|беларус|білорус|росі[яї]|московськ"
                     r"|[ыэъё]", re.I)
WAR = re.compile(r"russian (invasion|attack|strike|aggression|missile|drone|shelling)s?( of| on)?|russo-ukrainian"
                 r"|російськ\w* (вторгнен|атак|агресі|обстріл|удар)\w*", re.I)
# Фото має бути саме з України: про це має йтися в назві, описі чи категоріях
UKRAINE = re.compile(r"ukrain|kyiv|kiev|україн|київ|kharkiv|lviv|odesa|odessa|dnipro|zaporizh|verkhovna rada"
                     r"|zelensk|зеленськ|chernihiv|poltava|vinnytsia|mykolaiv|kherson|sumy|zhytomyr|rivne|lutsk"
                     r"|uzhhorod|ternopil|ivano-frankivsk|chernivtsi|cherkasy|kropyvnytskyi", re.I)

# Довгі офіційні підписи авторів на Commons → коротко українською
AUTHORS = {
    "PRESIDENT OF UKRAINE": "Офіс Президента України",
    "President Of Ukraine": "Офіс Президента України",
    "State Emergency Service": "ДСНС України",
    "Kyiv City State Administration": "КМДА",
    "Verkhovna Rada": "Верховна Рада України",
    "Cabinet of Ministers": "Кабінет Міністрів України",
}

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


def _mark_used(state, key):
    state.setdefault("photo_used", {})[key] = datetime.now(timezone.utc).isoformat()


def _ok(verify, path, what):
    """Перевірка фото очима Claude (verify). Помилка перевірки – фото не беремо, краще фото з фотобанку."""
    if not verify:
        return True
    try:
        v = verify(path)
    except Exception as e:  # noqa: BLE001
        log.info("Фото не перевірено (%s) – пропускаю: %s", what, e)
        return False
    log.info("Фото %s: %s – %s (%s)", "ПІДХОДИТЬ" if v["ok"] else "НЕ ПІДХОДИТЬ", what, v["seen"], v["reason"])
    return v["ok"]


def _official(texts, out_path, state, verify=None):
    """Фото з офіційного джерела новини (сайт чи Telegram-канал органу влади)."""
    for t in texts:
        url = (t.get("image") or "").strip()
        if t.get("kind") != "official" or not url or url in state.get("photo_used", {}):
            continue
        url = url.replace("/uploads/logos_middle/", "/uploads/logos/")  # сайт Ради: більша версія
        if collect.download_photo(url, out_path):
            _mark_used(state, url)
            if not _ok(verify, out_path, f"з джерела {t['source']}"):
                continue
            return {"path": out_path, "author": t["source"], "license": "", "official": True}
    return None


def _commons(query, out_path, state, verify=None, tries=3):
    """Найрелевантніше нове фото з Wikimedia Commons з вільною ліцензією; кожне перевіряє Claude (verify),
    до tries фото на запит."""
    used = state.get("photo_used", {})
    try:
        r = requests.get(COMMONS, headers=UA, timeout=40, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 25,
            "prop": "imageinfo|categories", "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
            "cllimit": "max"})
        pages = r.json().get("query", {}).get("pages", {}).values()
    except Exception as e:  # noqa: BLE001
        log.info("Wikimedia не відповіла (%s): %s", query, e)
        return None
    for p in sorted(pages, key=lambda x: x.get("index", 99)):
        title = p.get("title", "")
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "").strip()
        w, h = ii.get("width", 0), ii.get("height", 0)
        about = " ".join([title, meta.get("ImageDescription", {}).get("value", ""),
                          meta.get("ObjectName", {}).get("value", ""), meta.get("Categories", {}).get("value", ""),
                          *[c.get("title", "") for c in p.get("categories", [])]])
        about = WAR.sub("", about)  # «Russian invasion of Ukraine» – це про Україну, не про Росію
        if FOREIGN.search(about) or not UKRAINE.search(about):
            continue
        if (title in used or not FREE.match(lic) or NOT_PHOTO.search(title)
                or w < 1200 or not 1.2 <= w / max(h, 1) <= 2.4 or not ii.get("thumburl")):
            continue
        try:
            img = requests.get(ii["thumburl"], headers=UA, timeout=60)
            img.raise_for_status()
            Image.open(BytesIO(img.content)).convert("RGB").save(out_path, "JPEG", quality=85, optimize=True)
        except Exception as e:  # noqa: BLE001
            log.info("Не вдалося завантажити %s: %s", title, e)
            continue
        artist = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).strip()
        artist = re.sub(r"\s+", " ", re.sub(r"(from|http).*$", "", artist)).strip(" ,") or "автор невідомий"
        for long, short in AUTHORS.items():
            if long.lower() in artist.lower():
                artist = short
        _mark_used(state, title)
        tries -= 1
        if not _ok(verify, out_path, f"Wikimedia «{title[5:60]}»"):
            if tries <= 0:
                return None
            continue
        return {"path": out_path, "author": f"{artist[:60]} / Wikimedia Commons",
                "license": lic.replace("Public domain", "суспільне надбання"), "official": False,
                "source": ii.get("descriptionurl", "")}
    return None


def _from_bank(theme, state):
    used = state.get("photo_used", {})
    pool = [p for p in BANK if p["theme"] == theme] or [p for p in BANK if p["theme"] == "city"]
    fresh = [p for p in pool if p["file"] not in used]
    p = (fresh or sorted(pool, key=lambda x: used.get(x["file"], "")))[0]
    _mark_used(state, p["file"])
    return {"path": SITE / p["file"], "file": p["file"], "author": p["author"], "license": p["license"],
            "official": False}


def pick(a, texts, state, out_dir, verify=None):
    """Повертає фото для новини a: path (локальний файл), author, license, official.
    verify(path) -> {seen, ok, reason}: Claude дивиться на фото (правила – правила/фото.md).
    Фотобанк не перевіряємо – там лише відібрані вручну нейтральні фото за темами."""
    photo = _official(texts, out_dir / f"{a['id']}-src.jpg", state, verify)
    if photo:
        log.info("Фото: з джерела (%s)", photo["author"])
        return photo
    for q in [a.get("photo_query"), a.get("photo_query_alt")]:
        if not q:
            continue
        photo = _commons(q, out_dir / f"{a['id']}-wm.jpg", state, verify)
        time.sleep(1)
        if photo:
            log.info("Фото: Wikimedia за запитом «%s» (%s)", q, photo["author"])
            return photo
    photo = _from_bank(a.get("photo_theme", "city"), state)
    log.info("Фото: з фотобанку (%s)", photo["file"])
    return photo


def credit(photo):
    if photo["official"]:
        return f"{photo['author']} (пресслужба)"
    return ", ".join(x for x in (photo["author"], photo["license"]) if x)


def webp_versions(path, img):
    """Полегшені NAME-640.webp і NAME-1280.webp поруч із фото – сайт бере їх першими
    (як tools/optimize_photos.py), інакше браузер спершу отримує 404 і лише тоді вантажить JPEG."""
    for w in (640, 1280):
        copy = img.copy()
        if copy.width > w:
            copy = copy.resize((w, round(copy.height * w / copy.width)), Image.LANCZOS)
        copy.save(path.with_name(f"{path.stem}-{w}.webp"), "WEBP", quality=76, method=6)


def for_site(a, photo):
    """Блок photo для статті на сайті; нові фото копіюються в site/assets/photos/auto/."""
    if photo.get("file"):
        rel = photo["file"]
    else:
        rel = f"assets/photos/auto/{a['id']}.jpg"
        (SITE / rel).parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(photo["path"]).convert("RGB")
        img.thumbnail((1280, 1280))
        img.save(SITE / rel, "JPEG", quality=82, optimize=True)
        webp_versions(SITE / rel, img)
    entry = {"file": rel, "alt": a["title"], "author": photo["author"], "license": photo["license"]}
    if photo["official"]:
        entry["author"], entry["license"] = f"{photo['author']} (пресслужба)", ""
    return entry
