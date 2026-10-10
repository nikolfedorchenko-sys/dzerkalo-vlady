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
TRIAGE_TASK = rule("відбір")
REVIEW_TASK = rule("перевірка")
WRITE_TASK = f"""Напиши матеріал ДВ про сюжет нижче, спираючись тільки на тексти джерел. Один сюжет – три тексти: сайт, Telegram, Facebook.

Службові поля:
- id: коротка адреса латиницею через дефіс (транслітерація заголовка), 3–6 слів, без дат.
- rubric: одна з: {{rubrics}}.
- card_title: заголовок для картинки-картки, до 70 знаків.
- sources: джерела, на які спирається текст: назва органу чи медіа (наприклад «Верховна Рада», «Суспільне») і посилання – тільки з наданого списку. Першоджерело влади – першим.
- urgent: true тільки якщо рішення вже ухвалено або подія відбувається зараз.

САЙТ
{rule("сайт")}

TELEGRAM
{rule("telegram")}

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
                },
                "required": ["items", "topic", "rubric", "importance", "urgent"],
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
        "impact": STR,
        "next": PARAS,
        "opinion": STR,
        "telegram": PARAS,
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
    },
    "required": ["id", "rubric", "title", "card_title", "lead", "facts", "quote", "context", "impact",
                 "next", "opinion", "telegram", "facebook", "sources", "urgent"],
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


def _ask(task, content, schema, effort, model):
    return (_ask_max if engine() == "max" else _ask_api)(task, content, schema, effort, model)


def _ask_max(task, content, schema, effort, model):
    """Запит через Claude Code на підписці Max: без інструментів, тільки текст → JSON за схемою."""
    exe = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not exe:
        raise RuntimeError("Не знайдено Claude Code (claude) – його ставить робочий процес GitHub")
    if exe.lower().endswith(".cmd"):  # Windows: обгортка npm ламає лапки в JSON, кличемо claude.exe напряму
        native = os.path.join(os.path.dirname(exe), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        exe = native if os.path.exists(native) else exe
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", BRAND, "--model", model, "--effort", effort,
           "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    # Порожня тимчасова папка – щоб Claude Code не підхопив CLAUDE.md і налаштування з репозиторію
    with tempfile.TemporaryDirectory() as cwd:
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


def _ask_api(task, content, schema, effort, model):
    """Запасний шлях: Claude API за ключем (платно окремо від підписки)."""
    global _client
    _client = _client or anthropic.Anthropic()
    resp = _client.messages.create(
        model=model,
        max_tokens=16000,
        system=BRAND,
        messages=[{"role": "user", "content": f"{task}\n\n{content}"}],
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


def review(draft, texts):
    content = ("ЧЕРНЕТКА:\n" + json.dumps(draft, ensure_ascii=False, indent=1)
               + "\n\nТЕКСТИ ДЖЕРЕЛ:\n\n" + _sources_block(texts))
    return _ask(REVIEW_TASK, content, REVIEW_SCHEMA, "medium", MODEL_FAST)
