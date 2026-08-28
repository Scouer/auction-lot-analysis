#!/usr/bin/env python3
"""Скачивание оригиналов изображений листинга (правило v2.0.1) без транзита через контекст.

Вход — JSON-манифест: {"<лот>": {"i": ["<id файла>", ...], ...}, ...}
Такой манифест снимается со страниц лотов и выносится из браузера на диск
(см. references/platforms.md, «Вынос данных»).

  python3 fetch_originals.py <манифест.json> <каталог назначения> [--preview] [--base URL]

  --preview   качать превью, а не оригиналы (для триажа; ~10x легче)
  --base      шаблон URL с {} на месте id файла; по умолчанию — Invaluable:
              https://image.invaluable.com/housePhotos/<Дом>/<xx>/<catalogId>/H<id>-L{}.jpg
              (задавать через --base целиком, включая суффикс .jpg)

Печатает только сводку: сколько скачано, пропущено, ошибок.
"""
import argparse
import concurrent.futures as cf
import json
import os
import urllib.request

HDRS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://www.invaluable.com/",
}
MIN_BYTES = 2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("dest")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--base", required=True,
                    help="шаблон URL с {} на месте id файла, включая .jpg")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    man = json.load(open(os.path.expanduser(a.manifest)))
    root = os.path.expanduser(a.dest)
    jobs = [(lot, iid) for lot, v in man.items() for iid in v.get("i", [])]

    def get(job):
        lot, iid = job
        d = os.path.join(root, str(lot))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, iid + ".jpg")
        if os.path.exists(p) and os.path.getsize(p) > MIN_BYTES:
            return "skip"
        url = a.base.format(iid)
        if not a.preview:
            url = url.replace(".jpg", "_original.jpg")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=60) as r:
                data = r.read()
        except Exception:
            return "err"
        if len(data) < MIN_BYTES:
            return "small"
        with open(p, "wb") as f:
            f.write(data)
        return "ok"

    res = {}
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(get, jobs):
            res[r] = res.get(r, 0) + 1
    print(f"файлов: {len(jobs)}  {res}")
    print("режим:", "превью" if a.preview else "оригиналы")


if __name__ == "__main__":
    main()
