# antique — плагин разбора аукционных лотов

Репозиторий = плагин Cowork (источник истины). Навык: `auction-lot-analysis` v2.0 в `skills/auction-lot-analysis/`.

- `references/risk-profile.md` в репо НЕ входит (личный профиль) — живёт в vault `Vasily_Brain/Projects/antique/skill/references/` и добавляется при сборке пакета.
- Сборка установочного пакета: содержимое корня плагина (c risk-profile) → zip → `antique.plugin`; установка — кнопкой на карточке файла в чате Cowork.
- Рабочая копия контента: vault `Projects/antique/skill/` (плоская, без манифеста). Канонические md5 файлов навыка совпадают между репо, vault и установленным плагином.
- Цикл обновления: правка здесь → bump `version` в `.claude-plugin/plugin.json` → синк в vault → сборка `.plugin` → кнопка в чате.
