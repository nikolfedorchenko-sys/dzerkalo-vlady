"""Автопостинг «Дзеркало влади»: збір → відбір → написання → перевірка → сайт, Telegram, Facebook.

Режими (змінна DV_MODE):
  dry  – нічого не публікує: пише чернетки й картки в autopost/out/ (для перевірки на компʼютері);
  test – пости йдуть тільки в пробний Telegram-канал, сайт і Facebook не чіпаються;
  live – повна публікація: сайт, основний Telegram-канал, Facebook.
"""
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import brain  # noqa: E402
import card  # noqa: E402
import collect  # noqa: E402
import photos  # noqa: E402
import publish  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
STATE = HERE / "state" / "state.json"
OUT = HERE / "out"
DRAFTS = HERE / "state" / "drafts"  # фото й картки чернеток «на розсуд» – зберігаються між запусками добу
log = logging.getLogger("dv")
CFG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))


def load_env():
    """Локально секрети лежать в autopost/.env; у GitHub Actions вони приходять як змінні середовища."""
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"seen": {}, "published": []}


def save_state(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def fix_dashes(obj):
    if isinstance(obj, str):
        return obj.replace("—", "–")
    if isinstance(obj, list):
        return [fix_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: fix_dashes(v) for k, v in obj.items()}
    return obj


def check_draft(a, texts):
    """Механічні перевірки, які не варто довіряти моделі."""
    # Джерела – тільки офіційні (органи влади); медіа-конкурентів не згадуємо й не посилаємося
    official = [t for t in texts if t.get("kind") == "official"]
    allowed = {t["url"] for t in official} | {l for t in official for l in t.get("links", [])}
    a["sources"] = [s for s in a.get("sources", []) if s.get("url") in allowed] or [
        {"title": t["source"], "url": t["url"]} for t in official[:2]]
    problems = []
    if len(a["title"]) > 100:
        problems.append("заголовок задовгий")
    if not a["telegram"] or ("facts" in a and (not a["facts"] or not a["facebook"])):
        problems.append("порожній текст")
    if any(ch in a["title"] for ch in "!") or a["title"].isupper():
        problems.append("знак оклику чи капс у заголовку")
    if len(" ".join(a["telegram"])) > 700:
        problems.append("пост для Telegram задовгий")
    return problems


def skip_obvious(items, words):
    """Відсіює очевидно не наше (спорт, погода, гороскопи…) ще до Claude – це безкоштовно."""
    words = [w.casefold() for w in words]
    keep = [it for it in items if not any(w in (it["title"] + " " + it["summary"]).casefold() for w in words)]
    log.info("Відсіяно словами-фільтрами: %d", len(items) - len(keep))
    return keep


def facebook_check(cfg):
    """Кнопка «Перевірити Facebook»: публікує на сторінці останню автоматичну новину з сайту."""
    page, token = os.environ.get("FB_PAGE_ID", ""), os.environ.get("FB_PAGE_TOKEN", "")
    if not (page and token):
        sys.exit("Немає FB_PAGE_ID або FB_PAGE_TOKEN")
    n = next((x for x in publish.load_news()["news"] if x.get("auto")), None)
    if not n:
        sys.exit("На сайті ще немає автоматичних новин – нічого перевіряти")
    OUT.mkdir(exist_ok=True)
    src = n["sources"][0]["title"] if n.get("sources") else ""
    card_path = card.render(OUT / f"{n['id']}.png", brain.RUBRICS.get(n["rubric"], ""), n["title"], src,
                            urgent=n.get("urgent", False))
    a = {"title": n["title"], "facebook": n["lead"] + "\n\n" + n["impact"]["text"]}
    res = publish.send_facebook(page, token, a, publish.article_url(n["id"]), card_path)
    log.info("Facebook: опубліковано «%s» (%s)", n["title"], res.get("post_id") or res.get("id"))


def slim_texts(texts):
    """Що з джерел треба зберегти для чернетки «на розсуд»: фото й посилання, без повних текстів."""
    return [{k: t.get(k) for k in ("source", "kind", "url", "image", "links")} for t in texts]


def photo_check(a):
    """Перевірка фото очима Claude для новини a (вимикається в config.yaml: check_photos: false)."""
    if not CFG.get("check_photos", True) or not brain.engine():
        return None
    return lambda path: brain.check_photo(path, a)


def draft_card(key, draft, texts, state):
    """Фото й картка для чернетки: ті самі підуть у пост, якщо власник натисне «Опублікувати»."""
    DRAFTS.mkdir(parents=True, exist_ok=True)
    photo = photos.pick({**draft, "id": key}, texts, state, DRAFTS, photo_check(draft))
    label = brain.RUBRICS.get(draft.get("rubric"), "")
    card_path = card.render_photo(DRAFTS / f"{key}.jpg", photo["path"], label,
                                  draft.get("card_title") or draft["title"], "", photos.credit(photo))
    return {**photo, "path": str(photo["path"])}, card_path


def offer_draft(state, draft, kind, story, texts, problems, now):
    """Відхилену чернетку зберігаємо на добу; повертає (ключ, текст, картка) для повідомлення власнику з кнопками."""
    key = hashlib.sha1(f"{draft['id']}{now.isoformat()}".encode()).hexdigest()[:10]
    tg = story.get("scope") != "regional"
    try:
        photo, card_path = draft_card(key, draft, texts, state)
    except Exception as e:  # noqa: BLE001
        log.warning("Картка для чернетки не вийшла: %s", e)
        photo, card_path = None, None
    state.setdefault("pending", {})[key] = {
        "at": now.isoformat(), "kind": kind, "tg": tg, "story": story, "problems": problems, "photo": photo,
        "draft": {k: v for k, v in draft.items() if not k.startswith("_")}, "texts": slim_texts(texts)}
    where = ("сайт + Facebook" if kind == "full" else "Facebook") + (" + Telegram" if tg else "")
    preview = publish.telegram_text(draft, "", "", "")
    head = f"<b>На ваш розсуд</b> ({where}, оцінка {story['importance']}/10)"
    if kind == "full":
        head += f"\nНа сайті: {escape(draft['title'])}"
    why = "\n".join("– " + escape(p) for p in problems)
    text = f"{head}\n\n{preview}\n\n<i>Редактор відхилив:</i>\n{why}"
    return key, (text[:3990] + "…") if len(text) > 4000 else text, card_path


def release(published, cfg, state, mode, now, report):
    """Публікація готових матеріалів: повні – на сайт, далі Telegram і Facebook, у звіт – що й куди вийшло."""
    lim = cfg["limits"]
    now_local = now.astimezone(KYIV)
    tg_token = os.environ.get("TG_BOT_TOKEN", "")
    tg_chat = os.environ.get("TG_CHANNEL_ID" if mode == "live" else "TG_TEST_CHANNEL_ID", "")
    fb_page, fb_token = os.environ.get("FB_PAGE_ID", ""), os.environ.get("FB_PAGE_TOKEN", "")

    # Повні матеріали – на сайт
    full = [a for a in published if a["_full"]]
    data = publish.load_news()
    date = now_local.strftime("%Y-%m-%dT%H:%M")
    OUT.mkdir(exist_ok=True)
    for a in published:
        a["id"] = publish.unique_id(data["news"], a["id"])
        a["_photo"] = a.get("_photo") or photos.pick(a, a["_texts"], state, OUT, photo_check(a))
    for a in full:
        a["_site_photo"] = photos.for_site(a, a["_photo"]) if mode == "live" else None
        data["news"].insert(0, publish.site_entry(a, a["id"], date, a["_site_photo"]))

    if mode == "live":
        changed = publish.expire_urgent(data, now_local, lim["urgent_hours"])
        changed = publish.update_home(data, full, now_local, lim) or changed
        if publish.update_number_of_day(data, full, now_local):
            log.info("Цифра дня: %s – %s", data["numberOfDay"]["value"], data["numberOfDay"]["text"])
        if full or changed:
            publish.save_news(data)
            msg = ("Автопостинг: " + "; ".join(a["title"] for a in full)) if full else \
                "Автопостинг: оновити головну й зняти «Терміново» зі старих новин"
            if publish.git_push(msg) and full:
                publish.wait_for_site([a["id"] for a in full])
    elif full:
        drafts = [publish.site_entry(a, a["id"], date) for a in full]
        (OUT / "drafts.json").write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")

    fb_n = 0
    for a in published:
        url = publish.article_url(a["id"]) if a["_full"] else ""
        label = brain.RUBRICS.get(a["rubric"], "")
        src_title = ""  # рядок «Джерело» на картці не друкуємо
        # На картці – рубрика, без червоної плашки «ТЕРМІНОВО» (рішення власника 12.10.2026)
        card_path = card.render_photo(OUT / f"{a['id']}.jpg", a["_photo"]["path"], label,
                                      a["card_title"] or a["title"], src_title, photos.credit(a["_photo"]))
        text = publish.telegram_text(a, url, cfg.get("channel_url"), cfg.get("submit_url"))
        where = []
        if mode == "dry":
            (OUT / f"{a['id']}.telegram.html").write_text(text, encoding="utf-8")
            if a["_full"]:
                (OUT / f"{a['id']}.facebook.txt").write_text(a["facebook"], encoding="utf-8")
                (OUT / f"{a['id']}.site.json").write_text(json.dumps(publish.site_entry(a, a["id"], date),
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
            where.append("чернетка в autopost/out")
        else:
            # Регіональні новини в Telegram не йдуть – тільки на сайт і у Facebook
            if tg_token and tg_chat and a["_tg"]:
                try:
                    publish.send_telegram(tg_token, tg_chat, text, card_path)
                    where.append("Telegram" + (" (пробний)" if mode == "test" else ""))
                except Exception as e:  # noqa: BLE001
                    report.append(f"Telegram не прийняв пост: {escape(str(e))}")
            if mode == "live" and a["_full"]:
                where.append("сайт")
            if mode == "live" and a.get("facebook"):
                if fb_page and fb_token:
                    try:
                        # Facebook: перший пост одразу, наступні – з кроком fb_interval_minutes (розклад Facebook)
                        at = None if not fb_n else now.timestamp() + fb_n * lim["fb_interval_minutes"] * 60
                        publish.send_facebook(fb_page, fb_token, a, url, card_path, cfg.get("channel_url"), at)
                        where.append("Facebook" + (f" о {datetime.fromtimestamp(at, KYIV):%H:%M}" if at else ""))
                        fb_n += 1
                    except Exception as e:  # noqa: BLE001
                        report.append(f"Facebook не прийняв пост: {escape(str(e))}")
        state["published"].append({"at": now.isoformat(), "id": a["id"], "title": a["title"], "mode": mode,
                                   "full": a["_full"], "tg": a["_tg"]})
        title = escape(a["title"])
        report.append(f"<b>Опубліковано</b> ({', '.join(where) or 'нікуди'}): "
                      + (f"<a href=\"{escape(url)}\">{title}</a>" if url else title))


def publish_approved(cfg, state, mode, now, keys):
    """Кнопка «Опублікувати» під чернеткою в боті: публікуємо схвалені власником матеріали."""
    done = state.setdefault("approved_done", {})
    pending = state.setdefault("pending", {})
    ready, report = [], []
    for key in keys:
        if key in done:
            continue  # бот щоразу передає всі схвалення за добу – вже опубліковані пропускаємо
        if key.startswith("test"):
            report.append("Тест: кнопка «Опублікувати» працює – бот запустив робота. Нічого не опубліковано.")
            done[key] = now.isoformat()
            continue
        p = pending.pop(key, None)
        if not p:
            report.append(f"Чернетка {escape(key)} застаріла (старша за добу) – не публікую.")
            done[key] = now.isoformat()
            continue
        a = fix_dashes(p["draft"])
        a.update({"_story": p["story"], "_full": p["kind"] == "full", "_texts": p["texts"], "_tg": p["tg"]})
        ph = p.get("photo")
        if ph and Path(ph["path"]).exists():  # те саме фото, що було в чернетці
            a["_photo"] = {**ph, "path": Path(ph["path"])}
        ready.append(a)
        done[key] = now.isoformat()
    if ready:
        release(ready, cfg, state, mode, now, report)
    save_state(state)
    if report and mode != "dry":
        head = f"Дзеркало влади · за вашим рішенням · {now.astimezone(KYIV):%d.%m %H:%M}\n\n"
        publish.notify(os.environ.get("TG_BOT_TOKEN", ""), os.environ.get("TG_ADMIN_CHAT_ID", ""),
                       head + "\n\n".join(report))
    log.info("Опубліковано за рішенням власника: %d", len(ready))


def test_buttons(now):
    """Дія «Тест кнопок»: власнику приходить пробна чернетка з кнопками; натискання нічого не публікує."""
    key = "test" + hashlib.sha1(now.isoformat().encode()).hexdigest()[:6]
    draft = {"tg_title": "Тестова чернетка", "telegram": [
        "Це перевірка кнопок. Натисніть «Опублікувати» – за 2–5 хвилин прийде звіт, що кнопка працює.",
        "Нічого не буде опубліковано ні в каналі, ні на сайті, ні у Facebook."], "hashtags": []}
    text = ("<b>На ваш розсуд</b> (ТЕСТ)\n\n" + publish.telegram_text(draft, "", "", "")
            + "\n\n<i>Редактор відхилив:</i>\n– це тест, причин немає")
    OUT.mkdir(exist_ok=True)
    photo = photos.pick({"id": key, "photo_theme": "rada"}, [], {}, OUT)
    card_path = card.render_photo(OUT / f"{key}.jpg", photo["path"], "ВЕРХОВНА РАДА", "Тестова чернетка з картинкою",
                                  "", photos.credit(photo))
    publish.ask_owner(os.environ.get("TG_BOT_TOKEN", ""), os.environ.get("TG_ADMIN_CHAT_ID", ""), text, key, card_path)
    log.info("Тестову чернетку надіслано власнику (%s)", key)


def test_photos():
    """Дія «Перевірити фото»: Claude дивиться на фото трьох останніх новин сайту й пише в журнал, чи підходять."""
    site = HERE.parent / "site"
    for n in [x for x in publish.load_news()["news"] if (x.get("photo") or {}).get("file")][:3]:
        v = brain.check_photo(site / n["photo"]["file"], {"title": n["title"], "lead": n.get("lead", "")})
        log.info("%s | %s | %s – %s", "ПІДХОДИТЬ" if v["ok"] else "НЕ ПІДХОДИТЬ", n["title"], v["seen"], v["reason"])


def delete_post(mode):
    """Дія «Видалити пост з Telegram»: прибирає пост з каналу за номером (Telegram дозволяє протягом 48 годин)."""
    msg_id = os.environ.get("DV_POST", "").strip().rsplit("/", 1)[-1]
    chat = os.environ.get("TG_CHANNEL_ID" if mode == "live" else "TG_TEST_CHANNEL_ID", "")
    if not msg_id.isdigit():
        sys.exit("Вкажіть номер поста (з посилання t.me/dzerkalo_vlady/НОМЕР)")
    publish.delete_telegram(os.environ.get("TG_BOT_TOKEN", ""), chat, int(msg_id))
    log.info("Пост %s видалено з %s", msg_id, chat)


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    mode = os.environ.get("DV_MODE", "test").lower()
    if mode not in ("dry", "test", "live"):
        sys.exit(f"Невідомий DV_MODE={mode}")
    lim = cfg["limits"]
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(KYIV)
    action = os.environ.get("DV_ACTION", "")
    if action == "facebook-check":
        return facebook_check(cfg)
    if action == "delete-post":
        return delete_post(mode)
    if action == "test-buttons":
        return test_buttons(now)
    if action == "test-photos":
        return test_photos()

    state = load_state()
    keep_after = (now - timedelta(days=14)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v > keep_after}
    state["published"] = [p for p in state["published"] if p["at"] > keep_after]
    day_ago = (now - timedelta(hours=24)).isoformat()
    state["pending"] = {k: v for k, v in state.get("pending", {}).items() if v["at"] > day_ago}
    if DRAFTS.exists():  # фото й картки застарілих чернеток – прибираємо
        for f in DRAFTS.iterdir():
            if f.name[:10] not in state["pending"]:
                f.unlink()
    state["approved_done"] = {k: v for k, v in state.get("approved_done", {}).items() if v > keep_after}
    if action == "publish-draft":
        keys = [k for k in os.environ.get("DV_DRAFTS", "").replace(" ", "").split(",") if k]
        return publish_approved(cfg, state, mode, now, keys)

    log.info("Режим: %s, моделі: %s (тексти) / %s (відбір, перевірка), доступ: %s",
             mode, brain.MODEL, brain.MODEL_FAST, brain.engine())
    if not brain.engine():
        log.warning("Немає CLAUDE_CODE_OAUTH_TOKEN (чи ANTHROPIC_API_KEY) – автопостинг ще не налаштовано")
        return

    tg_token = os.environ.get("TG_BOT_TOKEN", "")
    admin_chat = os.environ.get("TG_ADMIN_CHAT_ID", "")

    # 1. Збір
    items, src_errors = collect.collect(cfg["sources"], lim["window_hours"])
    fresh = [it for it in items if it["key"] not in state["seen"]]
    # Один матеріал може прийти з кількох стрічок – лишаємо перший
    uniq = {}
    for it in fresh:
        uniq.setdefault(it["url"], it)
    fresh = sorted(uniq.values(), key=lambda x: x["published"], reverse=True)
    filtered = skip_obvious(fresh, cfg.get("skip_words", []))
    for it in fresh:  # що відсіяли – теж «бачили», щоб не перевіряти вдруге
        if it not in filtered:
            state["seen"][it["key"]] = now.isoformat()
    fresh = filtered[: lim["max_items_for_triage"]]
    log.info("Нових матеріалів: %d (усього свіжих %d)", len(fresh), len(items))

    report = []
    published, rejected, offers = [], [], []
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    today = [p for p in state["published"] if p["at"] > day_start]
    tg_left = lim["max_posts_per_day"] - sum(1 for p in today if p.get("tg", True))
    full_left = lim["site_max_per_day"] - sum(1 for p in today if p.get("full", True))

    def important(story):
        return story["urgent"] or story["importance"] >= lim["bypass_importance"]

    def plan(story):
        """None – пропустити; "full" – сайт + Facebook (+ Telegram); "short" – Telegram і Facebook.
        Регіональні сюжети в Telegram не йдуть: тільки сайт і Facebook, якщо дотягують до оцінки сайту."""
        if len(published) >= lim["max_posts_per_run"]:
            return None
        fulls = sum(1 for a in published if a["_full"])
        can_full = story["importance"] >= lim["site_min_importance"] and (fulls < full_left or important(story))
        if story.get("scope") == "regional":
            return "full" if can_full else None
        if sum(1 for a in published if a["_tg"]) >= tg_left and not important(story):
            return None
        return "full" if can_full else "short"

    if fresh:
        # 2. Відбір сюжетів
        recent = [p["title"] for p in state["published"] if p["at"] > (now - timedelta(hours=72)).isoformat()]
        try:
            stories = brain.triage(fresh, recent)
        except brain.LimitReached as e:
            # Матеріали не позначаємо як переглянуті – їх розберемо, коли ліміт оновиться
            log.warning("Ліміт підписки Max вичерпано, пропускаю запуск: %s", e)
            save_state(state)
            return
        for it in fresh:
            state["seen"][it["key"]] = now.isoformat()
        for s in stories:
            log.info("  сюжет %2d/10%s [%s]: %s (%s)", s["importance"], " ТЕРМІНОВО" if s["urgent"] else "",
                     s.get("scope"), s["topic"], s["rubric"])
        stories = [s for s in stories if s["importance"] >= lim["min_importance"] and s["items"]]
        stories.sort(key=lambda s: (-s["urgent"], -s["importance"]))
        log.info("Сюжетів для публікації: %d", len(stories))

        # 3. Написання і перевірка
        for story in stories:
            kind = plan(story)
            if not kind:
                continue
            picked = [fresh[i] for i in story["items"] if 0 <= i < len(fresh)][:4]
            if not picked:
                continue
            # Офіційні джерела – першими
            picked.sort(key=lambda it: it["kind"] != "official")
            texts = [{**it, "text": collect.full_text(it)} for it in picked]
            try:
                draft = fix_dashes((brain.write if kind == "full" else brain.write_short)(story, texts))
                problems = check_draft(draft, texts)
                verdict = brain.review(draft, texts) if not problems else {"ok": False, "problems": problems}
            except brain.LimitReached as e:
                log.warning("Ліміт підписки Max вичерпано, решту сюжетів пропускаю: %s", e)
                break
            except brain.Refused as e:
                verdict, draft = {"ok": False, "problems": [str(e)]}, {"title": story["topic"]}
            except Exception as e:  # noqa: BLE001
                log.exception("Помилка при написанні")
                verdict, draft = {"ok": False, "problems": [f"помилка: {e}"]}, {"title": story["topic"]}
            if verdict["ok"]:
                draft["_story"], draft["_full"], draft["_texts"] = story, kind == "full", texts
                draft["_tg"] = story.get("scope") != "regional"
                published.append(draft)
                log.info("ГОТОВО (%s): %s", "сайт+FB" + ("+TG" if draft["_tg"] else "") if kind == "full"
                         else "TG+FB", draft["title"])
            else:
                log.info("ВІДХИЛЕНО: %s – %s", draft.get("title"), "; ".join(verdict["problems"]))
                if draft.get("telegram"):  # чернетка є – власник може опублікувати її кнопкою в боті
                    offers.append(offer_draft(state, draft, kind, story, texts, verdict["problems"], now))
                else:
                    rejected.append((draft.get("title", story["topic"]), verdict["problems"]))

    # 4. Публікація
    release(published, cfg, state, mode, now, report)

    for title, problems in rejected:
        report.append(f"<b>Відхилено</b>: {escape(title)}\n– " + "\n– ".join(escape(p) for p in problems))
    if src_errors and now_local.hour == 8:  # про збої джерел – раз на день, у першому запуску
        report.append("Джерела, що не відповідали:\n" + "\n".join(escape(e) for e in src_errors))

    save_state(state)

    if report and mode != "dry":
        head = f"Дзеркало влади · автопостинг ({mode}) · {now_local:%d.%m %H:%M}\n\n"
        publish.notify(tg_token, admin_chat, head + "\n\n".join(report))
    if mode != "dry" and tg_token and admin_chat:
        for key, text, card_path in offers:  # відхилені чернетки – власнику з карткою і кнопками
            try:
                publish.ask_owner(tg_token, admin_chat, text, key, card_path)
            except Exception as e:  # noqa: BLE001
                log.warning("Не вдалося надіслати чернетку на розсуд: %s", e)
    log.info("Підсумок: опубліковано %d, відхилено %d, на розсуд власника %d", len(published), len(rejected),
             len(offers))


if __name__ == "__main__":
    main()
