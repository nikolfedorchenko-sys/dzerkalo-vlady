"""Робота з Claude: відбір новин, написання матеріалу, редакторська перевірка."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import anthropic

log = logging.getLogger("dv")

MODEL = os.environ.get("DV_MODEL") or "claude-opus-5-5"

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

BRAND = """Ти – редактор незалежного медіа «Дзеркало влади» (ДВ) про владу в Україні: від Київради до Верховної Ради.
Слоган: «Показуємо, що вирішують нагорі – і як це зачепить тебе.»
Аудиторія: кияни й усі, кому важливо, що ухвалюють Київрада, КМДА, Верховна Рада, уряд, Офіс Президента, і як це вплине на гаманець, дім і місто.

Голос ДВ – гострий, з авторським коментарем, але гострота тримається на фактах:
- Факт окремо, думка окремо. Спершу що сталося, з джерелом. Потім наша оцінка. Межу видно завжди.
- Б'ємо по рішеннях, а не по людях. Іронія – над тарифом, забудовою, порушеною обіцянкою. Без образ, прізвиськ, натяків на особисте.
- Кожне звинувачення – з доказом. Немає доказу – формулюємо як питання до влади.
- Без брехні заради гостроти. Однакова мірка для всіх політичних сил.
- Людською мовою: «Метро знову дорожчає», а не «ухвалено рішення щодо коригування тарифів».
- Заголовок – одна думка, до 80 знаків, реченням, не капсом. Без «ШОК», капсу в тексті, знаків оклику, емодзі.
- Тільки українська мова. Тире – тільки коротке (–), ніколи довге (—). Лапки – «ялинки».

Залізні правила для автоматичної публікації:
- Пиши ТІЛЬКИ те, що є в наданих текстах джерел. Не додавай цифр, дат, імен, цитат чи подробиць з власної пам'яті.
- Не копіюй речення джерел дослівно – переказуй своїми словами. Пряма цитата – коротка, в «ялинках», з тим, хто сказав.
- Якщо джерело – заява чи допис посадовця, пиши «заявив», «повідомив», а не подавай це як встановлений факт.
- Не вигадуй наслідків, яких не видно з фактів. Невідоме – так і пиши: «поки невідомо», або став питання до влади."""

TRIAGE_TASK = """Нижче – свіжі матеріали з джерел (офіційні сайти й канали влади, медіа). Відбери сюжети для ДВ.

Підходять: рішення й дії Київради, КМДА, міських служб Києва; закони й голосування Верховної Ради; рішення уряду, міністерств, НБУ, що зачіпають гроші й життя людей; рішення й заяви Офісу Президента про внутрішню політику; бюджет, тарифи, податки, ціни, забудова, транспорт, енергетика, корупція посадовців.
Не підходять: фронтові зведення, кримінальна хроніка без зв'язку з владою, спорт, культура, реклама, привітання, протокольні зустрічі без рішень, повтор того, що ми вже опублікували (список нижче).

Кілька матеріалів про одну подію – це один сюжет: збери їхні номери разом.
Оціни importance від 1 до 10: наскільки рішення зачіпає людей і наскільки воно нове. 8–10 – ухвалене рішення з прямим впливом на киян чи всю країну; 5–7 – помітна, але не термінова новина; 1–4 – дрібниця.
urgent = true тільки якщо рішення вже ухвалено або подія відбувається зараз і людям треба знати негайно.
Поверни до 6 найкращих сюжетів, найважливіші першими. Якщо нічого вартого немає – порожній список."""

WRITE_TASK = """Напиши матеріал ДВ про сюжет нижче, спираючись тільки на тексти джерел.

Поля:
- id: коротка адреса латиницею через дефіс (транслітерація заголовка), 3–6 слів, без дат.
- rubric: одна з: {rubrics}.
- title: заголовок до 80 знаків, одна думка.
- card_title: заголовок для картинки-картки, до 70 знаків.
- lead: два речення – що сталося і що це означає для тебе.
- impact: «Що це означає для тебе» – 1–3 речення про конкретний наслідок для читача. Тільки з фактів.
- body: 3–6 абзаців статті для сайту. Факти, контекст із джерел, хто ухвалив, коли, що далі.
- opinion: думка редакції – 1–2 речення, гостро, але без образ і без нових фактів. Якщо коментувати нічого – порожній рядок.
- telegram: 2–3 короткі абзаци для Telegram (разом до 650 знаків): факт → що це означає → наша думка. Без заголовка, рубрики й джерела – їх додасть система.
- facebook: текст для Facebook (до 900 знаків): перше речення чіпляє, далі факт, наслідок, думка. Без хештегів і емодзі.
- sources: джерела, на які спирається текст: назва органу чи медіа (наприклад «Рішення Київради», «Суспільне») і посилання – тільки з наданого списку. Першоджерело влади – першим.
- urgent: true тільки якщо рішення вже ухвалено або подія відбувається зараз."""

REVIEW_TASK = """Ти – випусковий редактор ДВ. Перевір чернетку перед автоматичною публікацією, порівнявши її з текстами джерел.
Відхили (ok = false), якщо є хоч одне:
1. Факт, цифра, дата, ім'я чи цитата, яких немає в джерелах або які перекручено.
2. Думку подано як факт, або заяву посадовця – як встановлений факт.
3. Образи, прізвиська, натяки на особисте; звинувачення без доказу.
4. Текст не про владу і її рішення, або сюжет надто дрібний для ДВ.
5. Довге тире (—), капс у тексті, знаки оклику, емодзі, не українська мова.
Дрібні стилістичні шорсткості – не причина відхиляти. У problems коротко перелічи, що не так (порожній список, якщо все добре)."""

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

ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "rubric": {"type": "string", "enum": AUTO_RUBRICS},
        "title": {"type": "string"},
        "card_title": {"type": "string"},
        "lead": {"type": "string"},
        "impact": {"type": "string"},
        "body": {"type": "array", "items": {"type": "string"}},
        "opinion": {"type": "string"},
        "telegram": {"type": "array", "items": {"type": "string"}},
        "facebook": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
                "required": ["title", "url"],
                "additionalProperties": False,
            },
        },
        "urgent": {"type": "boolean"},
    },
    "required": ["id", "rubric", "title", "card_title", "lead", "impact", "body",
                 "opinion", "telegram", "facebook", "sources", "urgent"],
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


def _ask(task, content, schema, effort):
    return (_ask_max if engine() == "max" else _ask_api)(task, content, schema, effort)


def _ask_max(task, content, schema, effort):
    """Запит через Claude Code на підписці Max: без інструментів, тільки текст → JSON за схемою."""
    exe = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not exe:
        raise RuntimeError("Не знайдено Claude Code (claude) – його ставить робочий процес GitHub")
    if exe.lower().endswith(".cmd"):  # Windows: обгортка npm ламає лапки в JSON, кличемо claude.exe напряму
        native = os.path.join(os.path.dirname(exe), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        exe = native if os.path.exists(native) else exe
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", BRAND, "--model", MODEL, "--effort", effort,
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
    log.info("Claude (Max): %s", {k: v for k, v in (out.get("usage") or {}).items()
                                  if k in ("input_tokens", "output_tokens")})
    if isinstance(out.get("structured_output"), dict):
        return out["structured_output"]
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(out.get("result", "")).strip())
    return json.loads(text)


_client = None


def _ask_api(task, content, schema, effort):
    """Запасний шлях: Claude API за ключем (платно окремо від підписки)."""
    global _client
    _client = _client or anthropic.Anthropic()
    resp = _client.messages.create(
        model=MODEL,
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
    lines = [f"[{i}] {it['source']} ({it['kind']}) · {it['published'][:16]}\n{it['title']}\n{it['summary'][:300]}"
             for i, it in enumerate(items)]
    recent = "\n".join(f"- {t}" for t in recent_titles) or "- (поки нічого)"
    content = f"Ми вже опублікували за останні дні:\n{recent}\n\nСвіжі матеріали:\n\n" + "\n\n".join(lines)
    return _ask(TRIAGE_TASK, content, TRIAGE_SCHEMA, "low")["stories"]


def _sources_block(texts):
    return "\n\n".join(
        f"=== Джерело {i + 1}: {t['source']} ({t['kind']})\nПосилання: {t['url']}\n"
        + (f"Посилання з допису: {', '.join(t['links'])}\n" if t.get("links") else "")
        + f"Опубліковано: {t['published'][:16]}\n\n{t['text']}"
        for i, t in enumerate(texts))


def write(story, texts):
    task = WRITE_TASK.format(rubrics=", ".join(f"{k} ({RUBRICS[k]})" for k in AUTO_RUBRICS))
    content = f"Сюжет: {story['topic']}\nЗапропонована рубрика: {story['rubric']}\n\n{_sources_block(texts)}"
    return _ask(task, content, ARTICLE_SCHEMA, "high")


def review(draft, texts):
    content = ("ЧЕРНЕТКА:\n" + json.dumps(draft, ensure_ascii=False, indent=1)
               + "\n\nТЕКСТИ ДЖЕРЕЛ:\n\n" + _sources_block(texts))
    return _ask(REVIEW_TASK, content, REVIEW_SCHEMA, "medium")
