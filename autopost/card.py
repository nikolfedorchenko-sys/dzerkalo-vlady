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


def render_photo(path, photo_path, rubric_label, title, source, credit, urgent=False):
    """Картка з фото: фото на весь кадр, знизу суцільне затемнення ink 70% (SOCIAL.md), на ньому текст."""
    from PIL import ImageOps
    pad = 72
    img = ImageOps.fit(Image.open(photo_path).convert("RGB"), (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.4))
    d0 = ImageDraw.Draw(img)
    width = SIZE - 2 * pad
    for size in (66, 60, 54, 48, 44):
        font = _font("Literata-ExtraBold.ttf", size)
        lines = _wrap(d0, title, font, width)
        if len(lines) <= 4:
            break
    line_h = int(size * 1.14)
    footer_top = SIZE - pad - 84            # джерело, автор фото і знак ДВ
    title_top = footer_top - 36 - len(lines) * line_h
    label_top = title_top - 28 - 44
    top = label_top - 56

    shade = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle([0, top, SIZE, SIZE], fill=(18, 20, 24, int(255 * 0.7)))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(img)

    label_font = _font("Onest-Bold.ttf", 28)
    if urgent:
        w = sum(d.textlength(c, font=label_font) + 2.2 for c in "ТЕРМІНОВО")
        d.rectangle([pad, label_top - 8, pad + w + 32, label_top + 44], fill=URGENT)
        _spaced(d, (pad + 16, label_top), "ТЕРМІНОВО", label_font, ON_URGENT, 2.2)
    else:
        _spaced(d, (pad, label_top), rubric_label, label_font, "#9FD3CF", 2.2)
    for i, line in enumerate(lines):
        d.text((pad, title_top + i * line_h), line, font=font, fill=PAPER)

    mark = Image.open(LOGOS / "dv-mark-inverse.png").convert("RGBA")
    mark.thumbnail((240, 84), Image.LANCZOS)
    mx = SIZE - pad - mark.width
    img.paste(mark, (mx, SIZE - pad - mark.height), mark)

    def fit(text, font, max_w):
        while d.textlength(text, font=font) > max_w and len(text) > 12:
            text = text[:-2].rstrip() + "…"
        return text
    small, tiny = _font("Onest-Regular.ttf", 24), _font("Onest-Regular.ttf", 20)
    if source:
        d.text((pad, footer_top + 16), fit(f"Джерело: {source}", small, mx - pad - 24), font=small, fill="#D8DADF")
    d.text((pad, footer_top + 52), fit(f"Фото: {credit}", tiny, mx - pad - 24), font=tiny, fill=INK_MUTED_DARK)
    img.save(path, "JPEG", quality=88, optimize=True)
    return path


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
