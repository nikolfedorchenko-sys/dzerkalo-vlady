"""Робота з Claude: відбір новин, написання матеріалу, редакторська перевірка."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import anthropic
import yaml

import photos

log = logging.getLogger("dv")

# Opus пише тексти; відбір і перевірку робить Sonnet – він значно менше витрачає ліміт підписки.
MODEL = os.environ.get("DV_MODEL") or "claude-opus-5-5"
MODEL_FAST = os.environ.get("DV_MODEL_FAST") or "claude-sonnet-5-5"

RUBRICS = {
    "kyivrada": "КИЇВРАДА",
    "verkhovna-rada": "ВЕРХОВНА РАДА",
    "uriad": "УРЯД",
    "ofis-prezydenta": "ОФІС ПРЕЗИДЕНТА",
    "rozsliduvannia": "РОЗСЛІДУВАННЯ",
    "hroshi": "ГРОШІ",
    "misto": "МІСТО",
    "perevirka-faktiv": "ПЕРЕВІРКА ФАКТІВ",
    "dumka": "ДУМКА",
}
# Автопостинг не пише розслідувань, перевірок фактів і колонок – це робота редакції.
AUTO_RUBRICS = ["kyivrada", "verkhovna-rada", "uriad", "ofis-prezydenta", "hroshi", "misto"]

# Правила редакції – прості текстові файли в autopost/правила/, їх можна правити без програміста.
RULES = Path(__file__).resolve().parent / "правила"


def rule(name):
    return (RULES / f"{name}.md").read_text(encoding="utf-8").strip()


BRAND = rule("голос")
# Хештеги для Telegram – список у config.yaml (рядок hashtags)
HASHTAGS = yaml.safe_load((Path(__file__).resolve().parent / "config.yaml").read_text(encoding="utf-8"))["hashtags"]
TG_TAGS = "Список хештегів: " + ", ".join(HASHTAGS) + "."
PHOTO_THEMES = ("- photo_query: запит англійською (2–5 слів) для пошуку фото на Wikimedia Commons, яке прямо показує предмет новини: "
                "конкретне місце, будівлю, об'єкт чи подію (напр. «Kyiv Metro train», «Verkhovna Rada session hall», "
                "«Kyiv thermal power plant», «Kyiv apartment block damaged»). Не абстракції й не імена людей. "
                "Завжди з «Kyiv» чи «Ukraine» – фото має бути з України. Запит описує те, що буквально видно на фото "
                "(будівлю, залу, об'єкт), а не подію чи людину.\n"
                "- photo_query_alt: запасний запит, ширший (напр. «Kyiv metro», «Ukraine power line»).\n"
                "- photo_theme: тема фото на випадок, якщо пошук нічого не дасть, одна з: "
                + "; ".join(f"{k} ({v})" for k, v in photos.THEMES.items()) + ".")
TRIAGE_TASK = rule("відбір")
PHOTO_TASK = rule("фото")
REVIEW_TASK = rule("перевірка")
WRITE_TASK = f"""Напиши матеріал ДВ про сюжет нижче, спираючись тільки на тексти джерел. Один сюжет – три тексти: сайт, Telegram, Facebook.

Службові поля:
- id: коротка адреса латиницею через дефіс (транслітерація заголовка), 3–6 слів, без дат.
- rubric: одна з: {{rubrics}}.
- card_title: заголовок для картинки-картки, до 70 знаків.
- sources: тільки офіційні джерела влади з наданого списку (сайти й канали органів влади, позначені official) – назва органу й посилання. Медіа сюди не включай ніколи. Якщо офіційного джерела немає – порожній список.
- urgent: true тільки якщо рішення вже ухвалено або подія відбувається зараз.
{PHOTO_THEMES}

САЙТ
{rule("сайт")}

TELEGRAM
{rule("telegram")}
{TG_TAGS}

FACEBOOK
{rule("facebook")}"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "topic": {"type": "string"},
                    "rubric": {"type": "string", "enum": AUTO_RUBRICS},
                    "importance": {"type": "integer"},
                    "urgent": {"type": "boolean"},
                    "scope": {"type": "string", "enum": ["national", "kyiv", "regional"]},
                },
                "required": ["items", "topic", "rubric", "importance", "urgent", "scope"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stories"],
    "additionalProperties": False,
}

STR = {"type": "string"}
PARAS = {"type": "array", "items": STR}
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": STR,
        "rubric": {"type": "string", "enum": AUTO_RUBRICS},
        "title": STR,
        "card_title": STR,
        "lead": STR,
        "facts": PARAS,
        "quote": {
            "type": "object",
            "properties": {"text": STR, "who": STR},
            "required": ["text", "who"],
            "additionalProperties": False,
        },
        "context": PARAS,
        "number": {
            "type": "object",
            "properties": {"value": STR, "text": STR},
            "required": ["value", "text"],
            "additionalProperties": False,
        },
        "impact": STR,
        "next": PARAS,
        "opinion": STR,
        "tg_title": STR,
        "telegram": PARAS,
        "hashtags": {"type": "array", "items": {"type": "string", "enum": HASHTAGS}},
        "facebook": STR,
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": STR, "url": STR},
                "required": ["title", "url"],
                "additionalProperties": False,
            },
        },
        "urgent": {"type": "boolean"},
        "photo_theme": {"type": "string", "enum": list(photos.THEMES)},
        "photo_query": STR,
        "photo_query_alt": STR,
    },
    "required": ["id", "rubric", "title", "card_title", "photo_theme", "photo_query", "photo_query_alt", "lead", "facts", "quote", "context", "number", "impact",
                 "next", "opinion", "tg_title", "telegram", "hashtags", "facebook", "sources", "urgent"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "problems"],
    "additionalProperties": False,
}


class Refused(Exception):
    pass


class LimitReached(Exception):
    """Вичерпано ліміт підписки Max – спробуємо в наступному запуску."""


def engine():
    """Через що звертаємося до Claude: підписка Max (Claude Code) або ключ API."""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "max"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    return None


def _ask(task, content, schema, effort, model, image=None):
    return (_ask_max if engine() == "max" else _ask_api)(task, content, schema, effort, model, image)


def _ask_max(task, content, schema, effort, model, image=None):
    """Запит через Claude Code на підписці Max → JSON за схемою. Без інструментів; якщо є image –
    лише інструмент Read, щоб Claude подивився на фото (копія лежить у тимчасовій папці)."""
    exe = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not exe:
        raise RuntimeError("Не знайдено Claude Code (claude) – його ставить робочий процес GitHub")
    if exe.lower().endswith(".cmd"):  # Windows: обгортка npm ламає лапки в JSON, кличемо claude.exe напряму
        native = os.path.join(os.path.dirname(exe), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        exe = native if os.path.exists(native) else exe
    tools = ["--tools", "Read", "--allowedTools", "Read"] if image else ["--tools", ""]
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", BRAND, "--model", model, "--effort", effort,
           *tools, "--strict-mcp-config", "--no-session-persistence"]
    # Порожня тимчасова папка – щоб Claude Code не підхопив CLAUDE.md і налаштування з репозиторію
    with tempfile.TemporaryDirectory() as cwd:
        if image:
            shutil.copy(image, Path(cwd) / "photo.jpg")
            content = "Спершу відкрий інструментом Read файл photo.jpg у поточній папці і уважно роздивись фото.\n\n" + content
        proc = subprocess.run(cmd, input=f"{task}\n\n{content}", capture_output=True, text=True,
                              encoding="utf-8", cwd=cwd, timeout=900)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude Code: {(proc.stderr or proc.stdout)[-500:]}") from None
    if out.get("is_error"):
        msg = str(out.get("result", ""))
        if re.search(r"limit|usage|quota|rate", msg, re.I):
            raise LimitReached(msg)
        raise RuntimeError(f"Claude Code: {msg}")
    if out.get("stop_reason") == "refusal":
        raise Refused("модель відмовилася обробляти цей матеріал")
    u = out.get("usage") or {}
    log.info("Claude (%s): вх. %s (+кеш %s/%s), вих. %s токенів, %.0f с",
             model, u.get("input_tokens"), u.get("cache_creation_input_tokens"), u.get("cache_read_input_tokens"),
             u.get("output_tokens"), (out.get("duration_ms") or 0) / 1000)
    if isinstance(out.get("structured_output"), dict):
        return out["structured_output"]
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(out.get("result", "")).strip())
    return json.loads(text)


_client = None


def _ask_api(task, content, schema, effort, model, image=None):
    """Запасний шлях: Claude API за ключем (платно окремо від підписки)."""
    global _client
    _client = _client or anthropic.Anthropic()
    parts = [{"type": "text", "text": f"{task}\n\n{content}"}]
    if image:
        import base64
        parts.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                      "data": base64.b64encode(Path(image).read_bytes()).decode()}})
    resp = _client.messages.create(
        model=model,
        max_tokens=16000,
        system=BRAND,
        messages=[{"role": "user", "content": parts}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        # Якщо фільтри безпеки моделі помилково відмовлять, запит сам повториться на іншій моделі.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        raise Refused("модель відмовилася обробляти цей матеріал")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("відповідь обрізано (max_tokens)")
    text = "".join(b.text for b in resp.content if b.type == "text")
    u = resp.usage
    log.info("Claude: %s вх. / %s вих. токенів", u.input_tokens, u.output_tokens)
    return json.loads(text)


def triage(items, recent_titles):
    lines = [f"[{i}] {it['source']} ({it['kind']}) · {it['published'][:16]}\n{it['title']}\n{it['summary'][:200]}"
             for i, it in enumerate(items)]
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- (поки нічого)"
    content = f"Ми вже опублікували за останні дні:\n{recent}\n\nСвіжі матеріали:\n\n" + "\n\n".join(lines)
    return _ask(TRIAGE_TASK, content, TRIAGE_SCHEMA, "medium", MODEL_FAST)["stories"]


def _sources_block(texts):
    return "\n\n".join(
        f"=== Джерело {i + 1}: {t['source']} ({t['kind']})\nПосилання: {t['url']}\n"
        + (f"Посилання з допису: {', '.join(t['links'])}\n" if t.get("links") else "")
        + f"Опубліковано: {t['published'][:16]}\n\n{t['text']}"
        for i, t in enumerate(texts))


def write(story, texts):
    task = WRITE_TASK.format(rubrics=", ".join(f"{k} ({RUBRICS[k]})" for k in AUTO_RUBRICS))
    content = f"Сюжет: {story['topic']}\nЗапропонована рубрика: {story['rubric']}\n\n{_sources_block(texts)}"
    return _ask(task, content, ARTICLE_SCHEMA, "high", MODEL)


SHORT_TASK = f"""Напиши коротку новину ДВ про сюжет нижче, спираючись тільки на тексти джерел: замітку для сайту, пост для Telegram і Facebook.

Поля:
- id: коротка адреса латиницею через дефіс, 3–6 слів.
- rubric: одна з: {{rubrics}}.
- title: заголовок до 80 знаків, одна думка.
- card_title: заголовок для картинки-картки, до 70 знаків.
- sources: тільки офіційні джерела влади з наданого списку (сайти й канали органів влади, позначені official) – назва органу й посилання. Медіа сюди не включай ніколи. Якщо офіційного джерела немає – порожній список.
- urgent: true тільки якщо рішення вже ухвалено або подія відбувається зараз.
{PHOTO_THEMES}

САЙТ (коротка замітка)
- lead: 1–2 речення – головне: хто, що вирішив чи заявив, коли.
- facts: 2–3 короткі абзаци фактів з джерел (цифри, дати, хто сказав). Без думки ДВ.
- impact: одне-два речення «Що це означає для тебе» – прямий наслідок для людей, тільки з того, що є в джерелах; невідомо – так і напиши.

TELEGRAM
{rule("telegram")}
{TG_TAGS}

FACEBOOK
{rule("facebook")}
Для цього поста facebook коротший: 500–900 знаків, за тими ж правилами."""

SHORT_SCHEMA = {
    "type": "object",
    "properties": {k: ARTICLE_SCHEMA["properties"][k]
                   for k in ("id", "rubric", "title", "card_title", "photo_theme", "photo_query", "photo_query_alt",
                             "lead", "facts", "impact",
                             "tg_title", "telegram", "hashtags", "facebook", "sources", "urgent")},
    "required": ["id", "rubric", "title", "card_title", "photo_theme", "photo_query", "photo_query_alt",
                 "lead", "facts", "impact",
                 "tg_title", "telegram", "hashtags", "facebook", "sources", "urgent"],
    "additionalProperties": False,
}


def write_short(story, texts):
    """Короткий пост тільки для Telegram – пише Sonnet, це дешево."""
    task = SHORT_TASK.format(rubrics=", ".join(f"{k} ({RUBRICS[k]})" for k in AUTO_RUBRICS))
    content = f"Сюжет: {story['topic']}\nЗапропонована рубрика: {story['rubric']}\n\n{_sources_block(texts)}"
    return _ask(task, content, SHORT_SCHEMA, "medium", MODEL_FAST)


def review(draft, texts):
    content = ("ЧЕРНЕТКА:\n" + json.dumps(draft, ensure_ascii=False, indent=1)
               + "\n\nТЕКСТИ ДЖЕРЕЛ:\n\n" + _sources_block(texts))
    return _ask(REVIEW_TASK, content, REVIEW_SCHEMA, "medium", MODEL_FAST)


PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "seen": STR,
        "ok": {"type": "boolean"},
        "reason": STR,
    },
    "required": ["seen", "ok", "reason"],
    "additionalProperties": False,
}


def check_photo(image, draft):
    """Claude дивиться на фото й вирішує, чи воно підходить до новини (правила – правила/фото.md).
    Повертає {seen: що на фото, ok, reason}."""
    news = "\n".join(x for x in [draft.get("title", ""), draft.get("lead", ""), " ".join(draft.get("telegram", []))] if x)
    content = (f"НОВИНА:\n{news}\n\nОпиши одним реченням, що на фото (seen), і виріши, чи воно підходить до новини (ok). "
               "У reason – коротко чому.")
    return _ask(PHOTO_TASK, content, PHOTO_SCHEMA, "low", MODEL_FAST, image=image)
