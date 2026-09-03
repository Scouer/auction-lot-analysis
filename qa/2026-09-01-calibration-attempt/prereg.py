#!/usr/bin/env python3
"""Предрегистрация прогноза по лоту.

Фиксирует прогноз ДО закрытия торгов, чтобы калибровка считалась по настоящим
предсказаниям, а не по числам, подставленным после известного молотка.

Журнал `calibration/prereg.jsonl` — только на дозапись, связан хеш-цепочкой:
каждая запись несёт хеш предыдущей. Отредактировать старую строку задним числом
можно, но цепочка после неё рассыплется, и `verify` это покажет. Это не запрет,
а обнаружимость — большего в обычной папке не сделать, и меньшего достаточно.

Команды:
  python3 code/prereg.py autolock         запереть всё созревшее (регулярная задача)\n  python3 code/prereg.py lock <lot_id>    зафиксировать один лот вручную
  python3 code/prereg.py verify           целостность цепочки + расхождения с хвостами
  python3 code/prereg.py status           что зафиксировано, что нет

Отказ в lock — это работа скрипта, а не ошибка: чаще всего он отказывает потому,
что молоток уже известен, и фиксировать «прогноз» поздно.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrate import ROOT, LOTS, extract_tail, read_index, num, pair  # noqa: E402

PREREG = os.path.join(ROOT, "calibration", "prereg.jsonl")
GENESIS = "GENESIS"
REQUIRED = ("hammer_forecast", "bid_ceiling", "verdict_auth")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat()


def digest(payload):
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load_chain():
    if not os.path.exists(PREREG):
        return []
    records = []
    with open(PREREG, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_record(record):
    os.makedirs(os.path.dirname(PREREG), exist_ok=True)
    with open(PREREG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def analysis_path(lot_id):
    return os.path.join(LOTS, lot_id, "research", "analysis.md")


def forecast_of(tail):
    """Прогнозные поля хвоста — ровно то, что фиксируется."""
    ceiling = tail.get("bid_ceiling") or {}
    if not isinstance(ceiling, dict):
        ceiling = {}
    fc_lo, fc_hi = pair(tail.get("hammer_forecast"))
    fv_lo, fv_hi = pair(tail.get("fair_value"))
    return {
        "hammer_forecast": [fc_lo, fc_hi],
        "fair_value": [fv_lo, fv_hi],
        "bid_ceiling": {k: num(ceiling.get(k))
                        for k in ("base", "regret", "walk_away")},
        "verdict_auth": str(tail.get("verdict_auth", "")).strip(),
        "skill_version": str(tail.get("skill_version", "")),
        "deadline_house": str(tail.get("deadline_house", "")),
    }


def lock_one(lot_id, amend=False, force=False):
    """Пытается запереть прогноз. Возвращает (код, строка-объяснение).

    код: locked | already | postfactum | no_tail | incomplete | no_analysis
    """
    path = analysis_path(lot_id)
    if not os.path.exists(path):
        return "no_analysis", "нет research/analysis.md"

    tail = extract_tail(path)
    if tail is None:
        return "no_tail", "в разборе нет YAML-хвоста — фиксировать нечего"

    missing = [f for f in REQUIRED if not tail.get(f)]
    if missing:
        return "incomplete", "пусты обязательные поля: %s" % ", ".join(missing)

    forecast = forecast_of(tail)
    if not all(forecast["hammer_forecast"]):
        return "incomplete", "hammer_forecast не полоса из двух чисел"
    if forecast["bid_ceiling"].get("walk_away") is None:
        return "incomplete", "не задан bid_ceiling.walk_away"

    # Главная защита: молоток уже известен -> это не прогноз.
    known = num(tail.get("hammer_actual"))
    if known is None:
        known = num(read_index().get(lot_id, {}).get("hammer"))
    if known is not None and not force:
        return "postfactum", "молоток уже известен (%.0f) — разбор постфактум" % known

    chain = load_chain()
    existing = [r for r in chain if r["lot_id"] == lot_id]
    if existing and not amend:
        return "already", "уже зафиксирован %s" % existing[-1]["ts"]

    prev = chain[-1]["hash"] if chain else GENESIS
    record = {
        "ts": now_iso(),
        "lot_id": lot_id,
        "revision": len(existing) + 1,
        "postfactum": bool(known is not None),
        "forecast": forecast,
        "prev": prev,
    }
    record["hash"] = digest(record)
    append_record(record)
    return "locked", "ревизия %d, прогноз %.0f–%.0f, потолок %.0f, hash %s" % (
        record["revision"], forecast["hammer_forecast"][0],
        forecast["hammer_forecast"][1], forecast["bid_ceiling"]["walk_away"],
        record["hash"][:12])


def cmd_lock(args):
    code, why = lock_one(args.lot_id, args.amend, args.force_postfactum)
    if code == "locked":
        print("ЗАФИКСИРОВАНО %s — %s" % (args.lot_id, why))
        return 0
    print("ОТКАЗ по %s: %s" % (args.lot_id, why))
    if code == "postfactum":
        print("       Такой лот идёт в кросс-таблицу «вердикт против исхода»,")
        print("       но не в метрики прогноза. Осознанно — флаг --force-postfactum.")
    if code == "already":
        print("       Пересмотр до торгов законен и виден: --amend допишет ревизию.")
    return 1


def cmd_autolock(args):
    """Запирает всё, что созрело. Ничего не спрашивает, ничего не ломает."""
    lots = sorted(os.listdir(LOTS)) if os.path.isdir(LOTS) else []
    lots = [l for l in lots if os.path.isdir(os.path.join(LOTS, l))]
    tally = {}
    locked_now = []
    for lot_id in lots:
        code, why = lock_one(lot_id)
        tally[code] = tally.get(code, 0) + 1
        if code == "locked":
            locked_now.append((lot_id, why))
        elif args.verbose:
            print("  пропуск %-24s %s" % (lot_id, why))
    for lot_id, why in locked_now:
        print("ЗАПЕРТО %-24s %s" % (lot_id, why))
    if not locked_now:
        print("Запирать нечего: новых разборов с прогнозом нет.")
    parts = ["%s=%d" % (k, v) for k, v in sorted(tally.items())]
    print("итог: %s" % (", ".join(parts) if parts else "лотов нет"))
    # Нечего запирать — это норма, не ошибка.
    return 0


def cmd_verify(args):
    chain = load_chain()
    if not chain:
        print("Журнал пуст — фиксировать ещё нечего.")
        return 0

    print("## Цепочка")
    prev = GENESIS
    broken = 0
    for i, rec in enumerate(chain, 1):
        stored = rec.get("hash")
        body = {k: v for k, v in rec.items() if k != "hash"}
        ok_hash = digest(body) == stored
        ok_link = rec.get("prev") == prev
        if not (ok_hash and ok_link):
            broken += 1
            why = []
            if not ok_hash:
                why.append("запись изменена после фиксации")
            if not ok_link:
                why.append("разрыв связи с предыдущей")
            print("  строка %d  %-24s РАЗРЫВ: %s"
                  % (i, rec.get("lot_id", "?"), "; ".join(why)))
        prev = stored
    print("  записей: %d, разрывов: %d" % (len(chain), broken))

    print("\n## Прогноз в журнале против текущего хвоста")
    drift = 0
    latest = {}
    for rec in chain:
        latest[rec["lot_id"]] = rec
    for lot_id, rec in sorted(latest.items()):
        path = analysis_path(lot_id)
        tail = extract_tail(path) if os.path.exists(path) else None
        if tail is None:
            print("  %-24s хвост пропал из разбора" % lot_id)
            drift += 1
            continue
        current = forecast_of(tail)
        keys = ("hammer_forecast", "fair_value", "bid_ceiling", "verdict_auth")
        diffs = [k for k in keys if current.get(k) != rec["forecast"].get(k)]
        if diffs:
            drift += 1
            print("  %-24s РАСХОЖДЕНИЕ: %s" % (lot_id, ", ".join(diffs)))
            if "hammer_forecast" in diffs:
                print("      было %s → стало %s"
                      % (rec["forecast"]["hammer_forecast"],
                         current["hammer_forecast"]))
        else:
            print("  %-24s совпадает" % lot_id)
    print("  расхождений: %d" % drift)

    if broken or drift:
        print("\nРасхождение само по себе не нарушение: прогноз можно уточнять")
        print("до торгов. Нарушение — уточнить его после. Смотреть на даты.")
    return 1 if broken else 0


def cmd_status(args):
    chain = load_chain()
    locked = {r["lot_id"] for r in chain}
    index = read_index()
    lots = sorted(os.listdir(LOTS)) if os.path.isdir(LOTS) else []
    lots = [l for l in lots if os.path.isdir(os.path.join(LOTS, l))]

    print("%-24s %-12s %-10s %s" % ("лот", "прогноз", "молоток", "статус"))
    for lot_id in lots:
        hammer = num(index.get(lot_id, {}).get("hammer"))
        path = analysis_path(lot_id)
        tail = extract_tail(path) if os.path.exists(path) else None
        if hammer is None and tail is not None:
            hammer = num(tail.get("hammer_actual"))
        if lot_id in locked:
            status = "чистая калибровка" if hammer else "ждём торгов"
        elif hammer is not None:
            status = "постфактум — вне метрик прогноза"
        elif tail is None:
            status = "нет хвоста — ЗАФИКСИРОВАТЬ НЕЧЕГО"
        else:
            status = "хвост есть, прогноз НЕ зафиксирован → lock"
        print("%-24s %-12s %-10s %s" % (
            lot_id,
            "есть" if lot_id in locked else "нет",
            "%.0f" % hammer if hammer else "—",
            status))
    print("\nзафиксировано: %d из %d лотов" % (len(locked & set(lots)), len(lots)))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_lock = sub.add_parser("lock", help="зафиксировать прогноз по лоту")
    p_lock.add_argument("lot_id")
    p_lock.add_argument("--amend", action="store_true",
                        help="дописать новую ревизию прогноза (до торгов)")
    p_lock.add_argument("--force-postfactum", action="store_true",
                        help="зафиксировать при известном молотке, с пометкой")
    p_lock.set_defaults(func=cmd_lock)

    p_auto = sub.add_parser("autolock",
                            help="запереть всё созревшее (для регулярной задачи)")
    p_auto.add_argument("-v", "--verbose", action="store_true",
                        help="показывать и пропущенные лоты с причиной")
    p_auto.set_defaults(func=cmd_autolock)

    sub.add_parser("verify", help="целостность журнала").set_defaults(func=cmd_verify)
    sub.add_parser("status", help="что зафиксировано").set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
