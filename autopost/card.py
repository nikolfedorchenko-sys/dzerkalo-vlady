"""Картка новини 1080×1080 за brand/SOCIAL.md: рубрика, заголовок Literata, джерело, знак ДВ у правому нижньому куті."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "brand" / "fonts"
LOGOS = ROOT / "brand" / "logos"

PAPER, INK, MUTED = "#F4F2ED", "#121418", "#5A5F68"
GLASS, URGENT, ON_URGENT = "#0E6A70", "#C2412D", "#FFFFFF"
INK_MUTED_DARK = "#A7ABB3"

SIZE, PAD, MARK = 1080, 80, 92


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        probe = f"{line} {word}".strip()
        if draw.textlength(probe, font=font) <= width:
            line = probe
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _spaced(draw, xy, text, font, fill, spacing):
    """Рубрика великими з розрядкою 0,08 em."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x


def render(path, rubric_label, title, source, urgent=False):
    bg, fg, meta = (INK, PAPER, INK_MUTED_DARK) if urgent else (PAPER, INK, MUTED)
    img = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)

    # Рубрика або плашка «Терміново»
    label_font = _font("Onest-Bold.ttf", 30)
    y = PAD
    if urgent:
        w = sum(d.textlength(c, font=label_font) + 2.4 for c in "ТЕРМІНОВО")
        d.rectangle([PAD, y, PAD + w + 36, y + 56], fill=URGENT)
        _spaced(d, (PAD + 18, y + 10), "ТЕРМІНОВО", label_font, ON_URGENT, 2.4)
    else:
        _spaced(d, (PAD, y + 10), rubric_label, label_font, GLASS, 2.4)

    # Заголовок: найбільший кегль, що вміщується в 5 рядків
    width = SIZE - 2 * PAD
    for size in (84, 76, 68, 60, 54, 48):
        font = _font("Literata-ExtraBold.ttf", size)
        lines = _wrap(d, title, font, width)
        if len(lines) <= 5:
            break
    line_h = int(size * 1.12)
    top = PAD + 140
    for i, line in enumerate(lines):
        d.text((PAD, top + i * line_h), line, font=font, fill=fg)

    # Знак ДВ і джерело внизу
    mark = Image.open(LOGOS / ("dv-mark-inverse.png" if urgent else "dv-mark.png")).convert("RGBA")
    mark.thumbnail((MARK * 3, MARK), Image.LANCZOS)
    mx, my = SIZE - PAD - mark.width, SIZE - PAD - mark.height
    img.paste(mark, (mx, my), mark)

    src_font = _font("Onest-Regular.ttf", 28)
    src = f"Джерело: {source}"
    while d.textlength(src, font=src_font) > mx - PAD - 32 and len(src) > 12:
        src = src[:-2].rstrip() + "…"
    d.text((PAD, SIZE - PAD - 34), src, font=src_font, fill=meta)

    img.save(path, "PNG", optimize=True)
    return path
