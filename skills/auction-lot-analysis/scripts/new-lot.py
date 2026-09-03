#!/usr/bin/env python3
"""
new-lot.py — создаёт досье аукционного лота в локальном архиве.

Пример:
    python3 new-lot.py --root . --date 2026-08-23 --house HOTSPOT --lot 64 \
        --title "Gilt Copper Filigree Enamel Nine Dragon Winged Crown" \
        --url "https://www.invaluable.com/auction-lot/..." \
        --estimate-low 5000 --estimate-high 8000

Создаёт lots/2026-08-23-HOTSPOT-064/ со структурой папок,
README.md с YAML-шапкой и добавляет строку в _index.csv.

Зависимостей нет, только стандартная библиотека.
"""

import argparse
import csv
import re
import sys
from datetime import date as _date
from pathlib import Path

SUBDIRS = [
    "source/house-photos",
    "research/refs",
    "photos/raw",
    "photos/web",
    "marks",
    "condition",
    "docs",
]

INDEX_FIELDS = [
    "id", "date", "house", "lot", "title", "url",
    "estimate_low", "estimate_high", "status", "result", "hammer", "total",
]

README = """---
id: {id}
title: "{title}"
url: {url}
house: {house}
lot_number: {lot}
auction_date: {date}
platform: ""
category: ""
region: ""

house_attribution: ""
house_period: ""
attribution_level: ""        # полное имя | Attributed to | Circle of | Follower of | Manner of | After | в стиле | нет
authenticity_warranty: ""    # есть | нет | не указано
estimate_low: {elow}
estimate_high: {ehigh}
currency: USD
buyers_premium_pct: null

status: в очереди            # в очереди | разбор | готово | отказ
my_hypothesis: ""
confidence: ""               # исключено | возможно | вероятно | нужна экспертиза
red_flags: []
provenance: ""               # полный | частичный | отсутствует
cites_risk: ""               # нет | возможен | подтверждён

pessimistic_value: null
max_bid: null
my_bid: null
hammer: null
total_cost: null
result: ""                   # не участвовал | перебили | купил | passed | снят

notion_url: ""
---

# {title}

**Лот {lot}, {house}, {date}**

## Что заявил дом

Дословное описание — в source/listing.md. Условия продажи на момент торгов — в
source/terms.md. Копия страницы — source/listing.pdf.

## Наш разбор

Полный разбор по скиллу — в research/analysis.md.

### Резюме

_Одним абзацем: что это по нашей версии, с каким уровнем уверенности._

### Что признаки исключают

### Круг кандидатов

### Что осталось проверить

| Проверка | Стоимость | Срок | Статус |
|---|---|---|---|

## Состояние

## Провенанс и юридическое

## Деньги

| | Сумма |
|---|---|
| Пессимистичная стоимость | |
| Потолок ставки | |
| Молоток | |
| Премия | |
| Налоги | |
| Логистика | |
| **Итого** | |

## Фотографии

Соглашение об именах: {id}_тип_NN.jpg
Типы: overall, detail, mark, base, uv, raking, damage, before, after.

- photos/raw/ — оригиналы, не редактировать
- photos/web/ — JPEG для просмотра и Notion
- marks/ — клейма: макро, косой свет, УФ
- condition/ — дефекты и реставрация

## Журнал

| Дата | Событие |
|---|---|
| {today} | Досье создано |
"""


def make_id(d: str, house: str, lot: str) -> str:
    house = re.sub(r"[^A-Za-z0-9]+", "", house).upper()[:12] or "UNKNOWN"
    lot = re.sub(r"[^A-Za-z0-9]+", "", str(lot)).upper()
    lot = lot.zfill(3) if lot.isdigit() else (lot or "000")
    return f"{d}-{house}-{lot}"


def valid_date(s: str) -> str:
    try:
        return _date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"дата должна быть в формате ГГГГ-ММ-ДД, получено: {s}")


def main() -> int:
    p = argparse.ArgumentParser(description="Создать досье аукционного лота")
    p.add_argument("--date", required=True, type=valid_date, help="дата торгов, ГГГГ-ММ-ДД")
    p.add_argument("--house", required=True, help="код дома, например HOTSPOT")
    p.add_argument("--lot", required=True, help="номер лота")
    p.add_argument("--title", required=True, help="название лота")
    p.add_argument("--url", default="", help="ссылка на лот")
    p.add_argument("--estimate-low", default="", help="нижний эстимейт")
    p.add_argument("--estimate-high", default="", help="верхний эстимейт")
    p.add_argument("--root", default=".", help="корень архива (папка antique)")
    args = p.parse_args()

    root = Path(args.root).expanduser()
    lot_id = make_id(args.date, args.house, args.lot)
    folder = root / "lots" / lot_id

    if folder.exists():
        print(f"Папка уже существует: {folder}", file=sys.stderr)
        return 1

    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)

    (folder / "README.md").write_text(
        README.format(
            id=lot_id,
            title=args.title.replace('"', "'"),
            url=args.url,
            house=args.house,
            lot=args.lot,
            date=args.date,
            elow=args.estimate_low or "null",
            ehigh=args.estimate_high or "null",
            today=_date.today().isoformat(),
        ),
        encoding="utf-8",
    )

    for stub, header in (
        ("source/listing.md", "# Описание дома дословно\n\n<!-- вставить без правок -->\n"),
        ("source/terms.md", f"# Условия продажи на {args.date}\n\n"),
        ("research/analysis.md", f"# Разбор: {args.title}\n\n"),
    ):
        (folder / stub).write_text(header, encoding="utf-8")

    with (folder / "research" / "comparables.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            ["date", "house", "lot", "hammer", "total", "condition", "url", "notes"]
        )

    index = root / "_index.csv"
    new_index = not index.exists()
    with index.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if new_index:
            w.writeheader()
        w.writerow({
            "id": lot_id, "date": args.date, "house": args.house, "lot": args.lot,
            "title": args.title, "url": args.url,
            "estimate_low": args.estimate_low, "estimate_high": args.estimate_high,
            "status": "в очереди", "result": "", "hammer": "", "total": "",
        })

    print(f"Досье создано: {folder}")
    print(f"ID: {lot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
