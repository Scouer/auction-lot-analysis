#!/usr/bin/env python3
"""Калибровщик навыка auction-lot-analysis.

Собирает YAML-хвосты боевых разборов, сшивает их с фактическими исходами из
_index.csv и считает, насколько прогнозы навыка совпали с реальностью.

Метрики прогноза считаются ТОЛЬКО по лотам с предрегистрацией (`code/prereg.py`):
прогноз, вписанный в хвост после известного молотка, — не прогноз. Разборы
постфактум показываются отдельно, как материал «вердикт против поведения рынка».

Выход:
  calibration/ledger.csv  — одна строка на лот (прогноз + факт)
  stdout                  — отчёт калибровки + пробелы в захвате

Запуск:  python3 code/calibrate.py
"""
import csv
import json
import math
import os
import re
import sys

import yaml

ROOT = os.environ.get("ANTIQUE_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
LOTS = os.path.join(ROOT, "lots")
INDEX = os.path.join(ROOT, "_index.csv")
OUT_DIR = os.path.join(ROOT, "calibration")
LEDGER = os.path.join(OUT_DIR, "ledger.csv")
PREREG = os.path.join(OUT_DIR, "prereg.jsonl")

YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)```", re.S)


def read_index():
    """id -> строка _index.csv"""
    rows = {}
    if not os.path.exists(INDEX):
        return rows
    with open(INDEX, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows[row["id"]] = row
    return rows


def read_prereg():
    """lot_id -> последняя запись предрегистрации."""
    latest = {}
    if not os.path.exists(PREREG):
        return latest
    with open(PREREG, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                latest[rec["lot_id"]] = rec
    return latest


def extract_tail(path):
    """Последний ```yaml-блок файла = YAML-хвост разбора."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for block in reversed(YAML_BLOCK.findall(text)):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "lot_id" in data:
            return data
    return None


def num(value):
    """Число или None. Терпит строки, пустоту, мусор."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def pair(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = num(value[0]), num(value[1])
        if lo and hi and lo > 0 and hi > 0:
            return lo, hi
    return None, None


def collect():
    """Обходит lots/, возвращает (записи, лоты_без_хвоста)."""
    entries, missing = [], []
    if not os.path.isdir(LOTS):
        return entries, missing
    index = read_index()
    prereg = read_prereg()
    for lot_id in sorted(os.listdir(LOTS)):
        if not os.path.isdir(os.path.join(LOTS, lot_id)):
            continue
        analysis = os.path.join(LOTS, lot_id, "research", "analysis.md")
        if not os.path.exists(analysis):
            missing.append((lot_id, "нет research/analysis.md"))
            continue
        tail = extract_tail(analysis)
        if tail is None:
            missing.append((lot_id, "нет YAML-хвоста"))
            continue
        idx = index.get(tail.get("lot_id", lot_id), index.get(lot_id, {}))
        ceiling = tail.get("bid_ceiling") or {}
        if not isinstance(ceiling, dict):
            ceiling = {}
        fc_lo, fc_hi = pair(tail.get("hammer_forecast"))
        fv_lo, fv_hi = pair(tail.get("fair_value"))
        actual = num(tail.get("hammer_actual"))
        if actual is None:
            actual = num(idx.get("hammer"))
        lock = prereg.get(tail.get("lot_id", lot_id))
        entries.append({
            "lot_id": tail.get("lot_id", lot_id),
            "category": tail.get("category", ""),
            "route": tail.get("route", ""),
            "tier": tail.get("tier", ""),
            "skill_version": str(tail.get("skill_version", "")),
            "prereg": "да" if lock and not lock.get("postfactum") else "нет",
            "prereg_ts": lock.get("ts", "") if lock else "",
            "est_low": num(idx.get("estimate_low")),
            "est_high": num(idx.get("estimate_high")),
            "fair_lo": fv_lo, "fair_hi": fv_hi,
            "fc_lo": fc_lo, "fc_hi": fc_hi,
            "walk_away": num(ceiling.get("walk_away")),
            "base": num(ceiling.get("base")),
            "actual": actual,
            "result": idx.get("result", ""),
            "verdict_auth": str(tail.get("verdict_auth", ""))[:160],
            "truncated": tail.get("truncated", ""),
            "degradations": ";".join(map(str, tail.get("degradations") or [])),
        })
    return entries, missing


def write_ledger(entries):
    if not entries:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(entries[0].keys()))
        writer.writeheader()
        writer.writerows(entries)


def geo_mean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def median(values):
    vals = sorted(values)
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def section_capture(entries, missing):
    total = len(entries) + len(missing)
    print("\n## 1. Захват")
    print("лотов в lots/            : %d" % total)
    print("с YAML-хвостом           : %d" % len(entries))
    print("с фактическим молотком   : %d" % len([e for e in entries if e["actual"]]))
    print("с предрегистрацией       : %d" % len([e for e in entries if e["prereg"] == "да"]))
    if missing:
        print("\nбез хвоста — калибровать нечем:")
        for lot_id, why in missing:
            print("  - %-28s %s" % (lot_id, why))


def section_forecast(clean):
    print("\n## 2. Прогноз молотка против факта (только предрегистрированные)")
    if not clean:
        print("Ни одного лота с зафиксированным до торгов прогнозом.")
        print("Метрик прогноза нет — и подставить их из старых разборов нельзя:")
        print("полоса, вписанная при известном молотке, всегда «попадает».")
        print("Первый чистый лот появится после `python3 code/prereg.py lock <id>`")
        print("на живом лоте до закрытия торгов.")
        return
    print("%-24s %10s %14s %8s %7s" % ("лот", "факт", "прогноз", "попал", "×сдвиг"))
    hits, biases, widths = 0, [], []
    for e in clean:
        hit = e["fc_lo"] <= e["actual"] <= e["fc_hi"]
        hits += hit
        biases.append(e["actual"] / math.sqrt(e["fc_lo"] * e["fc_hi"]))
        widths.append(e["fc_hi"] / e["fc_lo"])
        print("%-24s %10.0f %14s %8s %7.2f" % (
            e["lot_id"], e["actual"],
            "%.0f–%.0f" % (e["fc_lo"], e["fc_hi"]),
            "да" if hit else "НЕТ", biases[-1]))
    print("\nпопадание в полосу : %d из %d" % (hits, len(clean)))
    print("систем. смещение   : ×%.2f  (>1 = навык занижает, <1 = завышает)"
          % geo_mean(biases))
    print("средняя ширина     : ×%.1f  (шире ×4 — «попал», почти ничего не сказав)"
          % geo_mean(widths))
    if len(clean) < 10:
        print("n=%d — читать как анекдот, не как метрику (порог 10)." % len(clean))


def section_postfactum(post):
    if not post:
        return
    print("\n## 3. Разборы постфактум (вне метрик прогноза)")
    print("Материал для кросс-таблицы «вердикт против поведения рынка».")
    print("%-24s %9s %7s  %s" % ("лот", "молоток", "к low", "вердикт"))
    for e in post:
        ratio = "%.2f" % (e["actual"] / e["est_low"]) if e["est_low"] else "—"
        print("%-24s %9.0f %7s  %s" % (
            e["lot_id"], e["actual"], ratio, e["verdict_auth"][:70]))


def section_bids(scored):
    rows = [e for e in scored if e["walk_away"]]
    if not rows:
        return
    print("\n## 4. Решение по ставке против рынка")
    for e in rows:
        verdict = "перебили — уход подтверждён" if e["actual"] > e["walk_away"] \
            else "взяли бы в пределах потолка"
        print("  %-24s потолок %8.0f | молоток %8.0f | %s" % (
            e["lot_id"], e["walk_away"], e["actual"], verdict))


def section_base_rates(scored):
    ratios = [(e["lot_id"], e["actual"] / e["est_low"])
              for e in scored if e["est_low"]]
    if not ratios:
        return
    print("\n## 5. Эстимейт дома как база (вход в base-rates.md)")
    for lot_id, r in ratios:
        print("  %-24s молоток/low = %.2f" % (lot_id, r))
    print("  медиана по выборке      = %.2f  (n=%d)"
          % (median([r for _, r in ratios]), len(ratios)))
    print("  в base-rates.md записано: 0,5–0,6 для Eden 21.08")


def report(entries, missing):
    print("=" * 64)
    print("КАЛИБРОВКА auction-lot-analysis")
    print("=" * 64)
    scored = [e for e in entries if e["actual"] and e["fc_lo"]]
    clean = [e for e in scored if e["prereg"] == "да"]
    post = [e for e in scored if e["prereg"] != "да"]
    section_capture(entries, missing)
    section_forecast(clean)
    section_postfactum(post)
    section_bids(scored)
    section_base_rates(scored)
    print("\nledger: %s" % os.path.relpath(LEDGER, ROOT))


def main():
    entries, missing = collect()
    write_ledger(entries)
    report(entries, missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
