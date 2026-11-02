# Антиквариат — локальный контур на Mini

Всё работает **на этой машине**, без облака. Claude/Anthropic API не используется.

## Файлы
| Файл | Что делает |
|---|---|
| `antiq_lib.py` | Notion REST, Gmail (scouer@), Telegram, вызовы `nlm`, трекинг-ссылки, лог, чекпоинт |
| `antiq_daily.py` | ежедневный разбор почты → обновление Notion → пересборка досье → дайджест в TG |
| `antiq_profile.py` | сборка PDF-досье покупки (7 блоков) и заливка в блокнот NotebookLM |
| `antiq_weekly.py` | недельная сверка с кабинетом Invaluable через headless Chrome |
| `state.json` | чекпоинт последнего разбора почты |
| `antiq.log` | журнал прогонов |
| `pdf/`, `img/` | собранные досье и кэш фотографий |
| `chrome-profile/` | отдельный профиль Chrome с сессией Invaluable |

## Расписание (launchd, время MSK)
- `ai.claude.antiq-daily` — каждый день 08:00
- `ai.claude.antiq-weekly` — понедельник 09:00

Проверить: `launchctl list | grep antiq` · Перезапустить: `launchctl kickstart -k gui/$(id -u)/ai.claude.antiq-daily`

## Ручной запуск
```
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_daily.py --dry --since 7   # посмотреть, ничего не меняя
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_daily.py                   # обычный прогон
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_profile.py push 387269D6AE # пересобрать одно досье
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_profile.py shipment 1ZC373C1DL11891046  # всю посылку
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_weekly.py login            # РАЗОВО: вход в Invaluable
/usr/bin/python3 ~/.claude-assistant/antiq/antiq_weekly.py check            # сверка с кабинетом
```

## Что программа делает и чего не делает
Делает: читает почту, обновляет статусы/треки/переписку в Notion, пересобирает PDF-досье
изменившихся отправок в блокноте «Антиквариат», шлёт один дайджест в Telegram.

**Не делает никогда:** не отправляет письма от имени Максима, не платит по счетам и ссылкам,
ничего не удаляет в Notion и Gmail, не трогает maxim.russkikh@gmail.com, не печатает секреты.
Всё, что требует денег или ответа, попадает в дайджест строкой «ТРЕБУЕТ ДЕЙСТВИЯ».

## Что откуда берётся
- Секреты: `../notion.env` (NOTION_TOKEN, TODOIST_TOKEN), `../tg-bot.env` (токен бота), Gmail — `../google_api.py` + `../google_token_scouer.json`
- Базы Notion: инвойсы `226d2214956242b4ac739bad66e8e496`, лоты `093548f1567a406c889c41275501e89e`, переписка `fcec0f33ed114f918e251e9904c64104`
- Блокнот: `78b9a001-0747-42e8-b358-ee2b52a2ccdc`, CLI `~/.local/bin/nlm`
- PDF собирается headless-Chrome, фото качается с image.invaluable.com и жмётся через `sips`

## Известные ограничения
- Треки FedEx/DHL принимаются только из писем самого перевозчика (10–12 цифр иначе ловят телефоны и суммы).
- Письмо форвардера с неизвестным треком не привязывается автоматически: программа ищет этот номер по всей почте, и если отправитель не определился — выносит в раздел «ТРЕКИ БЕЗ ИНВОЙСА».
- Недельная сверка требует живой сессии Invaluable в `chrome-profile/`; если протухла — придёт сообщение в TG с командой для повторного входа.
