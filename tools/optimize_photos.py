"""Полегшені версії фото для сайту: для кожного site/assets/photos/*.jpg|png
створює поруч NAME-640.webp (телефони) і NAME-1280.webp (комп'ютери).
Оригінал лишається – сайт бере його, якщо полегшеної версії немає.

Запуск з папки проєкту:  python tools/optimize_photos.py
Уже готові версії не перероблює (додайте --force, щоб перезібрати все)."""
import sys
from pathlib import Path
from PIL import Image

PHOTOS = Path(__file__).resolve().parent.parent / "site" / "assets" / "photos"
SIZES = (640, 1280)
QUALITY = 76
force = "--force" in sys.argv

made = 0
for src in sorted(PHOTOS.iterdir()):
    if src.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        continue
    im = None
    for w in SIZES:
        out = src.with_name(f"{src.stem}-{w}.webp")
        if out.exists() and not force:
            continue
        if im is None:
            im = Image.open(src)
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        copy = im.copy()
        if copy.width > w:
            copy = copy.resize((w, round(copy.height * w / copy.width)), Image.LANCZOS)
        copy.save(out, "WEBP", quality=QUALITY, method=6)
        made += 1
        print(f"{out.name}: {out.stat().st_size // 1024} КБ (оригінал {src.stat().st_size // 1024} КБ)")
print(f"Готово, нових файлів: {made}")
