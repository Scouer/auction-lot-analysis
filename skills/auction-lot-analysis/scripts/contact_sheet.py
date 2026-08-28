#!/usr/bin/env python3
"""Контакт-лист лота: все кадры в одной сетке с подписями индексов.

Позволяет найти кадр с нужной зоной, не открывая каждый файл по отдельности —
один снимок вместо десятка. Индексы на листе совпадают с порядком файлов.

  python3 contact_sheet.py <каталог с изображениями> [выходной файл.jpg]

Опции окружения:
  SHEET_COLS   колонок (по умолчанию 4)
  SHEET_TILE   ширина ячейки, px (по умолчанию 620)
  SHEET_MAX_W  максимальная ширина листа, px (по умолчанию 2200)
"""
import os
import sys

from PIL import Image, ImageDraw

COLS = int(os.environ.get("SHEET_COLS", "4"))
TILE = int(os.environ.get("SHEET_TILE", "620"))
MAX_W = int(os.environ.get("SHEET_MAX_W", "2200"))
EXT = (".jpg", ".jpeg", ".png", ".webp")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    src = os.path.expanduser(sys.argv[1])
    files = sorted(f for f in os.listdir(src) if f.lower().endswith(EXT))
    if not files:
        print("нет изображений в", src)
        sys.exit(1)

    scaled, cell_h = [], 0
    for f in files:
        try:
            im = Image.open(os.path.join(src, f)).convert("RGB")
        except Exception as e:
            print("пропуск", f, e)
            continue
        w, h = im.size
        nh = int(h * (TILE / w))
        scaled.append((f, im.resize((TILE, nh), Image.LANCZOS)))
        cell_h = max(cell_h, nh)
    cell_h = min(cell_h, 1100)

    rows = (len(scaled) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TILE, rows * (cell_h + 26)), "white")
    d = ImageDraw.Draw(sheet)
    for k, (name, im) in enumerate(scaled):
        r, c = divmod(k, COLS)
        if im.size[1] > cell_h:
            nw = int(im.size[0] * cell_h / im.size[1])
            im = im.resize((nw, cell_h), Image.LANCZOS)
        sheet.paste(im, (c * TILE + (TILE - im.size[0]) // 2, r * (cell_h + 26) + 26))
        d.text((c * TILE + 6, r * (cell_h + 26) + 6), f"[{k}] {name}", fill="black")

    if sheet.size[0] > MAX_W:
        f = MAX_W / sheet.size[0]
        sheet = sheet.resize((MAX_W, int(sheet.size[1] * f)), Image.LANCZOS)

    out = os.path.expanduser(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(src, "_contact_sheet.jpg")
    sheet.save(out, quality=88)
    print(out, f"{sheet.size[0]}x{sheet.size[1]}", f"кадров: {len(scaled)}")
    for k, (name, _) in enumerate(scaled):
        print(f"  [{k}] {name}")


if __name__ == "__main__":
    main()
