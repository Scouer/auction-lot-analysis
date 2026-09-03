#!/bin/zsh
# Контур калибровки antique: запереть созревшие прогнозы -> посчитать -> записать отчёт.
# Запускается регулярной задачей antique-calibrate. Руками запускать не требуется.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="$ROOT/calibration/report.md"
{
  echo "# Отчёт калибровки"
  echo
  echo "Генерируется задачей \`antique-calibrate\`. **Руками не править** — перезапишется."
  echo "Прогон: $(date '+%Y-%m-%d %H:%M %Z')"
  echo
  echo '```'
  python3 code/prereg.py autolock 2>&1
  echo
  python3 code/calibrate.py 2>&1
  echo '```'
  echo
  echo "Связано: [[README|контракт калибровки]] · [[../README|проект antique]]"
} > "$OUT"
cat "$OUT"
