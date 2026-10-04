# Marketapp Shop

Telegram-бот на Python/aiogram 3 для продажи Telegram Stars, Premium, пополнения
GRAM и аренды Telegram NFT-подарков через Marketapp. Финансовое состояние хранится
в Supabase; FSM используется только для временных полей UI.

## Поток заказа

1. Пользователь выбирает Stars / Premium / GRAM / NFT rent.
2. Бот проверяет получателя или получает каталог аренды через Marketapp.
3. Создаётся заказ и уникальный `memo`; пользователь платит TON (Stars/Premium
   также поддерживают USDT-on-TON).
4. Фоновый worker подтверждает входящую транзакцию по destination + asset + atomic
   amount + memo. Один `tx_hash` не может оплатить два заказа.
5. После `PAYMENT_CONFIRMED` Marketapp формирует операцию. Официальный
   `marketapp-api` SDK подписывает и отправляет TON-транзакцию выделенным
   settlement-кошельком, работающим с GRAM.
6. Результат, provider order id и blockchain tx hash сохраняются в Supabase.
   Неоднозначный результат переводится в `MANUAL_REVIEW` и **не повторяется
   автоматически**.

Старые заказы с `provider=FRAGMENT` продолжают исполняться старым адаптером, что
позволяет мигрировать без потери уже оплаченных заказов.

## Marketapp и blockchain

Marketapp использует API-token в заголовке `Authorization` без `Bearer`. Для
mutating endpoints часть ответов представляет собой транзакции, которые нужно
отправить в TON. Поэтому для автоматического исполнения одного API-token
недостаточно: нужен отдельный settlement wallet.

В Render secrets задайте:

```text
MARKETAPP_API_TOKEN=...
MARKETAPP_WALLET_SEED=word1 word2 ... word24
MARKETAPP_TON_API_KEY=...
MARKETAPP_WALLET_VERSION=V5R1
```

`MARKETAPP_TON_API_KEY` можно не задавать, если уже заполнен `TONCENTER_API_KEY`.
Используйте отдельный wallet с минимально необходимым операционным балансом, а не
основной/личный кошелёк. Token/seed не пишутся в БД, ответы Telegram или логи.

## База данных

Для нового Supabase-проекта сначала выполните `supabase/schema.sql`, затем:

```text
supabase/migrations/20261004_marketapp.sql
```

Для существующего проекта достаточно применить migration. Он добавляет:

- `provider`, `provider_payload`, `provider_order_id/response/tx_hash`;
- поля GRAM и NFT-rent;
- расширенные product constraints;
- provider-aware claim/complete RPC с idempotency lease.

Не деплойте код до применения migration: worker использует RPC
`claim_order_fulfillment_v2` и `complete_order_fulfillment_v2`.

## GRNT-style UI и фото

Сохраняется карточная цепочка: главное меню → получатель/каталог → параметры →
оплата → blockchain confirmation → loading → success/error. В `app/assets/media/`
можно положить `main_menu`, `shop`, `recipient`, `product`, `payment_method`,
`payment_wait`, `loading`, `success`, `error`, `orders`, `referrals`, `settings`,
`wallet`, `rent` в GIF/MP4/PNG/JPG. Для NFT-rent бот умеет отображать remote photo
URL из Marketapp-каталога; если URL нет, используется локальный fallback.

## Идемпотентность и безопасность

- incoming payment проверяется по точной сумме и memo;
- `orders.tx_hash` уникален;
- claim fulfillment выполняется PostgreSQL RPC под row lock;
- у каждой попытки есть уникальный `idempotency_key` и audit record;
- после provider/blockchain ambiguity нет автоматического повторного списания;
- admin retry допустим только после ручной сверки provider/TON transaction.

## Запуск

```bash
python -m pip install -r requirements.txt
python main.py
```

Render-конфигурация находится в `render.yaml`. При polling должен работать ровно
один instance; для масштабирования используйте webhook mode.
