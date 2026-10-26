# Разработка

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Windows (приложение также должно работать на Linux/macOS, но целевая
  платформа — Windows)

## Установка

```powershell
uv sync
```

`uv` создаст `.venv`, установит PySide6 и dev-зависимости из `pyproject.toml`.

## Запуск

```powershell
uv run pos
uv run python main.py
uv run python -m pos
```

Демо-данные:

```powershell
uv run python -m pos.demo
```

Логи пишутся в `data/pos.log`; при фатальном сбое — `data/crash.log`.

## Тесты

```powershell
uv run pytest
```

Без экрана (CI/сервер):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest
```

`tests/conftest.py` создаёт временную папку данных и `AppContext` для каждого
теста. UI-тесты используют offscreen-платформу Qt.

Полезные команды:

```powershell
uv run pytest tests/test_sales.py -v
uv run pytest -k "backup or shift"
uv run python -m compileall -q src
```

## Структура

```text
src/pos/
  app.py            запуск, восстановление, контроллер входа
  config.py         AppPaths, POS_DATA_DIR
  context.py        AppContext (связывание сервисов)
  database.py       SQLite, транзакции, backup, integrity
  schema.sql        схема
  models.py         dataclasses
  money.py          копейки, форматирование, парсинг
  security.py       PBKDF2
  services/         бизнес-логика без UI
  ui/               PySide6
tests/              pytest
docs/               документация
```

## Соглашения

### Деньги

Все суммы — `int` в копейках. Не используйте `float` для денег. Для ввода и
вывода — функции из `pos.money`. В UI используйте `format_money`, в сервисах
храните и сравнивайте целые числа.

### Транзакции

Любая операция, меняющая несколько таблиц, выполняется внутри
`with db.transaction():`. Не вызывайте `commit()` вручную. Вложенные вызовы
безопасны: `Database` использует `SAVEPOINT`.

### Ошибки

Сервисы бросают исключения из `pos.services.errors`:

- `ValidationError` — некорректные входные данные;
- `SaleError` — ошибка оформления продажи;
- `ShiftError` — ошибка смены;
- `AuthError` — ошибка входа;
- `ImportError_` — ошибка импорта.

UI перехватывает `ServiceError` и показывает сообщение. Не показывайте
пользователю трассировку стека.

### UI

- Страницы не выполняют SQL.
- После изменения данных вызывайте `refresh()` страницы или сигналы
  `sale_completed` / `shift_changed` / `import_completed`.
- Общие виджеты и диалоги — в `ui/widgets.py`, стили — в `ui/theme.py`.
- Проверка прав — `ctx.users.has_permission(user, key)`, а не сравнение роли.
- Для модальных окон используйте `QDialog.DialogCode.Accepted`.

### Импорт

Сопоставление полей описано в `TARGETS` и `FIELD_SYNONYMS` в
`services/legacy.py`. Новые поля добавляйте в `FieldSpec`, `FIELD_SYNONYMS`,
`map_row`, `_import_*` и тесты.

### Схема и миграции

1. Измените `schema.sql` и увеличьте `SCHEMA_VERSION` в `database.py`.
2. Добавьте миграцию в `_migrate()` для существующих баз.
3. Обновите тесты и `docs/database.md`.

Текущая версия схемы — 2. Миграция с версии 1 добавляет
`items.is_consumable` и таблицу `service_consumables`, не удаляя данные.

Не удаляйте данные пользователей без резервной копии.

## Тестовые данные

Фикстуры в `tests/conftest.py`:

| Фикстура | Что создаёт |
| --- | --- |
| `paths` | временные `AppPaths` |
| `ctx` | подключённый `AppContext` |
| `admin` | пользователь-администратор |
| `seller` | продавец с правом `view_stats` |

Пример теста:

```python
def test_sale(ctx, admin):
    item = ctx.catalog.create_item(
        name="Кофе", kind="product", price=15000, cost=5000,
        initial_stock=10, user_id=admin.id,
    )
    shift = ctx.shifts.open_shift(admin.id)
    sale = ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[SaleLineInput(item_id=item.id, qty=1, unit_price=15000)],
        payments=[PaymentInput(method_id=1, amount=15000)],
    )
    assert sale.total == 15000
```

## Отладка

- Проверить базу: `sqlite3 data/pos.db` (если установлен CLI) или через
  Python.
- Проверить целостность: кнопка в настройках или
  `uv run python -c "from pos.database import Database; ..."`.
- Посмотреть события смены: таблица `shift_events`.
- Посмотреть журнал импорта: таблица `import_jobs`.
- UI без монитора: `QT_QPA_PLATFORM=offscreen`.

## Упаковка

Проект использует `hatchling` и точку входа `pos = "pos.app:main"`.
Для сборки wheel:

```powershell
uv build
```

Для распространения на Windows можно использовать PyInstaller, включив
`src/pos/schema.sql` как data-файл. Папка `data/` должна создаваться рядом с
исполняемым файлом или задаваться через `POS_DATA_DIR`.
