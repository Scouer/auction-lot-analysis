#!/usr/bin/env python3
"""Кроп нативного разрешения из оригинала — то, что подаётся в модель зрения.

Оригинал целиком в зрение не подаётся: он даунскейлится на входе, и 100 px/знак
превращаются в 26. Читается кроп.

  python3 crop.py <файл> <ячейки>            ячейки сетки 3x3: 0..8 через запятую, или all
  python3 crop.py <файл> box <x0> <y0> <x1> <y1>    нормированные 0..1

Опции окружения:
  CROP_OUT   каталог для кропов (по умолчанию рядом с файлом, папка crops/)
  CROP_MAX   максимальная длинная сторона кропа, px (по умолчанию 1600)

Печатает размер оригинала и путь каждого кропа с его размером.
"""
import os
import sys

from PIL import Image

MAX = int(os.environ.get("CROP_MAX", "1600"))
PAD = 0.12


def save(im, box, out):
    W, H = im.size
    x0, y0, x1, y1 = box
    pw, ph = (x1 - x0) * PAD, (y1 - y0) * PAD
    box = (max(0, x0 - pw), max(0, y0 - ph), min(W, x1 + pw), min(H, y1 + ph))
    c = im.crop(tuple(int(v) for v in box))
    if max(c.size) > MAX:
        f = MAX / max(c.size)
        c = c.resize((max(1, int(c.size[0] * f)), max(1, int(c.size[1] * f))), Image.LANCZOS)
    c.save(out, quality=94)
    return c.size


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    src = os.path.expanduser(sys.argv[1])
    im = Image.open(src).convert("RGB")
    W, H = im.size
    stem = os.path.splitext(os.path.basename(src))[0]
    out_dir = os.environ.get("CROP_OUT") or os.path.join(os.path.dirname(src), "crops")
    os.makedirs(out_dir, exist_ok=True)
    print(f"original {W}x{H}")

    if sys.argv[2] == "box":
        x0, y0, x1, y1 = (float(v) for v in sys.argv[3:7])
        out = os.path.join(out_dir, f"{stem}_box.jpg")
        s = save(im, (x0 * W, y0 * H, x1 * W, y1 * H), out)
        print(f"{out} {s[0]}x{s[1]}")
        return

    cells = range(9) if sys.argv[2] == "all" else (int(c) for c in sys.argv[2].split(","))
    for c in cells:
        r, col = divmod(c, 3)
        out = os.path.join(out_dir, f"{stem}_c{c}.jpg")
        s = save(im, (col * W / 3, r * H / 3, (col + 1) * W / 3, (r + 1) * H / 3), out)
        print(f"{out} {s[0]}x{s[1]}")


if __name__ == "__main__":
    main()
