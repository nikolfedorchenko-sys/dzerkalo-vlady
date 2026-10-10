"""Автопостинг «Дзеркало влади»: збір → відбір → написання → перевірка → сайт, Telegram, Facebook.

Режими (змінна DV_MODE):
  dry  – нічого не публікує: пише чернетки й картки в autopost/out/ (для перевірки на компʼютері);
  test – пости йдуть тільки в пробний Telegram-канал, сайт і Facebook не чіпаються;
  live – повна публікація: сайт, основний Telegram-канал, Facebook.
"""
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
import publish  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
STATE = HERE / "state" / "state.json"
OUT = HERE / "out"
log = logging.getLogger("dv")


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
    allowed = {t["url"] for t in texts} | {l for t in texts for l in t.get("links", [])}
    a["sources"] = [s for s in a["sources"] if s.get("url") in allowed] or [
        {"title": t["source"], "url": t["url"]} for t in texts[:2]]
    problems = []
    if len(a["title"]) > 100:
        problems.append("заголовок задовгий")
    if not a["facts"] or not a["telegram"] or not a["facebook"]:
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
    if os.environ.get("DV_ACTION") == "facebook-check":
        return facebook_check(cfg)
    log.info("Режим: %s, моделі: %s (тексти) / %s (відбір, перевірка), доступ: %s",
             mode, brain.MODEL, brain.MODEL_FAST, brain.engine())
    if not brain.engine():
        log.warning("Немає CLAUDE_CODE_OAUTH_TOKEN (чи ANTHROPIC_API_KEY) – автопостинг ще не налаштовано")
        return

    tg_token = os.environ.get("TG_BOT_TOKEN", "")
    admin_chat = os.environ.get("TG_ADMIN_CHAT_ID", "")
    tg_chat = os.environ.get("TG_CHANNEL_ID" if mode == "live" else "TG_TEST_CHANNEL_ID", "")
    fb_page, fb_token = os.environ.get("FB_PAGE_ID", ""), os.environ.get("FB_PAGE_TOKEN", "")

    state = load_state()
    keep_after = (now - timedelta(days=14)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v > keep_after}
    state["published"] = [p for p in state["published"] if p["at"] > keep_after]

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
    published, rejected = [], []
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    day_left = lim["max_posts_per_day"] - sum(1 for p in state["published"] if p["at"] > day_start)

    def allowed(story):
        """Денний ліміт; дуже важливе й термінове проходить і понад нього."""
        if len(published) >= lim["max_posts_per_run"]:
            return False
        return len(published) < day_left or story["urgent"] or story["importance"] >= lim["bypass_importance"]

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
            log.info("  сюжет %2d/10%s: %s (%s)", s["importance"], " ТЕРМІНОВО" if s["urgent"] else "",
                     s["topic"], s["rubric"])
        stories = [s for s in stories if s["importance"] >= lim["min_importance"] and s["items"]]
        stories.sort(key=lambda s: (-s["urgent"], -s["importance"]))
        log.info("Сюжетів для публікації: %d", len(stories))

        # 3. Написання і перевірка
        for story in stories:
            if not allowed(story):
                continue
            picked = [fresh[i] for i in story["items"] if 0 <= i < len(fresh)][:4]
            if not picked:
                continue
            # Офіційні джерела – першими
            picked.sort(key=lambda it: it["kind"] != "official")
            texts = [{**it, "text": collect.full_text(it)} for it in picked]
            try:
                draft = fix_dashes(brain.write(story, texts))
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
                draft["_story"] = story
                published.append(draft)
                log.info("ГОТОВО: %s", draft["title"])
            else:
                rejected.append((draft.get("title", story["topic"]), verdict["problems"]))
                log.info("ВІДХИЛЕНО: %s – %s", draft.get("title"), "; ".join(verdict["problems"]))

    # 4. Публікація
    data = publish.load_news()
    date = now_local.strftime("%Y-%m-%dT%H:%M")
    for a in published:
        a["id"] = publish.unique_id(data["news"], a["id"])
        data["news"].insert(0, publish.site_entry(a, a["id"], date))

    OUT.mkdir(exist_ok=True)
    if mode == "live":
        changed = publish.expire_urgent(data, now_local, lim["urgent_hours"])
        if publish.update_number_of_day(data, published, now_local):
            log.info("Цифра дня: %s – %s", data["numberOfDay"]["value"], data["numberOfDay"]["text"])
        if published or changed:
            publish.save_news(data)
            msg = ("Автопостинг: " + "; ".join(a["title"] for a in published)) if published else \
                "Автопостинг: зняти «Терміново» зі старих новин"
            if publish.git_push(msg) and published:
                publish.wait_for_site([a["id"] for a in published])
    elif published:
        drafts = [publish.site_entry(a, a["id"], date) for a in published]
        (OUT / "drafts.json").write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")

    for a in published:
        url = publish.article_url(a["id"])
        label = brain.RUBRICS.get(a["rubric"], "")
        src_title = a["sources"][0]["title"] if a["sources"] else ""
        card_path = card.render(OUT / f"{a['id']}.png", label, a["card_title"] or a["title"], src_title,
                                urgent=a.get("urgent", False))
        text = publish.telegram_text(a, label, url, cfg.get("submit_url"))
        where = []
        if mode == "dry":
            (OUT / f"{a['id']}.telegram.html").write_text(text, encoding="utf-8")
            (OUT / f"{a['id']}.facebook.txt").write_text(a["facebook"], encoding="utf-8")
            (OUT / f"{a['id']}.site.json").write_text(json.dumps(publish.site_entry(a, a["id"], date),
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
            where.append("чернетка в autopost/out")
        else:
            if tg_token and tg_chat:
                try:
                    publish.send_telegram(tg_token, tg_chat, text, card_path)
                    where.append("Telegram" + (" (пробний)" if mode == "test" else ""))
                except Exception as e:  # noqa: BLE001
                    report.append(f"Telegram не прийняв пост: {escape(str(e))}")
            if mode == "live":
                where.append("сайт")
                if fb_page and fb_token:
                    try:
                        publish.send_facebook(fb_page, fb_token, a, url, card_path)
                        where.append("Facebook")
                    except Exception as e:  # noqa: BLE001
                        report.append(f"Facebook не прийняв пост: {escape(str(e))}")
        state["published"].append({"at": now.isoformat(), "id": a["id"], "title": a["title"], "mode": mode})
        report.append(f"<b>Опубліковано</b> ({', '.join(where) or 'нікуди'}): "
                      f"<a href=\"{escape(url)}\">{escape(a['title'])}</a>")

    for title, problems in rejected:
        report.append(f"<b>Відхилено</b>: {escape(title)}\n– " + "\n– ".join(escape(p) for p in problems))
    if src_errors and now_local.hour == 8:  # про збої джерел – раз на день, у першому запуску
        report.append("Джерела, що не відповідали:\n" + "\n".join(escape(e) for e in src_errors))

    save_state(state)

    if report and mode != "dry":
        head = f"Дзеркало влади · автопостинг ({mode}) · {now_local:%d.%m %H:%M}\n\n"
        publish.notify(tg_token, admin_chat, head + "\n\n".join(report))
    log.info("Підсумок: опубліковано %d, відхилено %d", len(published), len(rejected))


if __name__ == "__main__":
    main()
