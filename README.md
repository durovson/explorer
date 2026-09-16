# Stars & Premium Shop

Telegram-бот на Python/aiogram 3 для прямой продажи Telegram Stars и Premium через
Fragment. Пользователь не пополняет счет: каждый заказ — отдельный платеж на
специальный TON-кошелек.

## Архитектура

```text
app/
├── api/            # FastAPI health/webhook и Telegram notifications
├── core/           # enums, exceptions
├── database/       # асинхронная граница Supabase
├── handlers/       # тонкие aiogram handlers
├── keyboards/      # inline UI
├── middleware/     # создание/получение пользователя
├── models/         # Pydantic entities
├── repositories/   # Supabase/PostgREST и RPC
├── services/       # заказы, цены, TON/USDT, Fragment, рефералы, admin
├── states/         # только не финансовый FSM ввода
├── tasks/          # независимые payment/expiry/fulfillment workers
└── utils/          # GRNT-style media renderer
```

Финансовое состояние находится только в Supabase. FSM хранит лишь временные поля
мастера покупки и никогда не подтверждает оплату.

## Гарантии платежа и идемпотентности

- валюта ограничена `TON` и `USDT`; master USDT жестко проверяется конфигурацией;
- для входящего перевода должны совпасть destination, asset, atomic amount и memo;
- `tx_hash` уникален в БД, поэтому одна транзакция не оплатит два заказа;
- подтверждение платежа и история статуса записываются одной PostgreSQL RPC;
- Fragment-попытка имеет внутренний уникальный ключ и отдельный audit record; ключ
  также отправляется поставщику как `Idempotency-Key`, но безопасность не зависит
  от поддержки этого недокументированного request-header;
- неоднозначный ответ никогда не повторяется автоматически.

## Установка

1. Создайте Supabase-проект и выполните [schema.sql](supabase/schema.sql).
2. Скопируйте `.env.example` в `.env`, заполните секреты.
3. Установите зависимости и запустите тесты:

```bash
python -m pip install -r requirements.txt
pytest -q
```

4. Локальный запуск: `python main.py`.

Для Render приложен `render.yaml`; сервис должен иметь ровно один polling instance.
Для горизонтального масштабирования включите webhook и задайте `APP_BASE_URL`,
`TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_USE_POLLING=false`.

## Медиа GRNT

`app/assets/menu.png` перенесен из GRNT и используется как fallback. Renderer ищет
GIF/MP4/PNG в `app/assets/media/`: `main_menu`, `shop`, `recipient`, `product`,
`payment_method`, `payment_wait`, `loading`, `success`, `error`, `orders`,
`referrals`, `settings`. В предоставленной сборке GRNT самих GIF не было, поэтому
добавление файлов с этими именами автоматически активирует их без правок кода.

## Fragment API

`fragment-api.com` — независимый от Telegram/Fragment поставщик. Он публикует
OpenAPI-схему по `https://api.fragment-api.com/api/schema.yaml`. Адаптер использует
JWT Fragment Connection, `misc/user`, `order/stars`, `order/premium` и `order/{id}`.
Перед production выполните тестовую покупку на минимальной сумме и убедитесь, что
`TON_RECEIVER_ADDRESS` относится к ожидаемому операционному кошельку Fragment
Connection. JWT хранится только в Render environment и никогда не записывается в
Supabase или логи.

## Эксплуатационные команды

- `/admin_stats` — сводка пользователей, заказов и оборота;
- `/approve_retry <UUID> <причина>` — только после ручной проверки Fragment;
- `GET /health` — Supabase и состояние фоновых воркеров.

Подробное сопоставление проектов находится в [MIGRATION_PLAN.md](MIGRATION_PLAN.md).
