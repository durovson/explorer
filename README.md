# Stars & Premium Shop

Telegram-бот для прямой продажи Telegram Stars и Premium. Пользователь оплачивает каждый заказ отдельно в TON или официальном USDT-on-TON; внутреннего баланса и промокодов нет.

## Текущая архитектура

Проект работает на **Render + Supabase**, а не на Telegram Serverless.

Причина: покупка через Marketapp API сначала строит TON-транзакцию, а для автоматической выдачи Stars/Premium сервер должен безопасно подписать и отправить ее операционным TON-кошельком. Python SDK `marketapp-api` делает это через seed кошелька и `tonutils`. В Telegram Serverless нет подходящего пакетного runtime и runtime secret manager для безопасного хранения seed, поэтому для этого проекта Render безопаснее и проще.

- Render: FastAPI + aiogram, Telegram webhook, фоновые проверки оплат.
- Supabase: заказы, платежные состояния и аудит fulfillment.
- Marketapp: цены, проверка получателя и покупка Stars/Premium.
- TON Center: проверка входящих TON/USDT переводов и wallet RPC для auto-pay.

## Marketapp вместо Fragment Connection JWT

`Fragment Connection JWT` больше не используется. Бот использует официальный HTTPS API Marketapp через пакет `marketapp-api==1.0.1`.

Секреты хранятся только в Render Environment: `MARKETAPP_API_TOKEN`, `MARKETAPP_WALLET_SEED`, `TONCENTER_API_KEY` и Telegram/Supabase ключи. Seed и API-токены нельзя добавлять в Git, Supabase или логи. Используется именно `https://api.marketapp.org`; HTTP для токена недопустим.

## Фиксированная комиссия

База цены берется из Marketapp непосредственно перед созданием заказа. Сверху применяется фиксированная надбавка, откалиброванная по эталонному боту:

- TON: `539612 / 10229388` ≈ **5.2751%**;
- USDT: `19 / 75` = **25.3333%**.

Отдельной `providerFee` нет. Те же фиксированные коэффициенты применяются к Stars и Premium. Для 100 Stars на контрольной базе 1.0229388 TON / 1.50 USD это дает 1.0769 TON / 1.88 USDT.

Промокодов, купонов и пользовательских скидочных кодов в коде нет.

## Безопасность исполнения покупки

После подтверждения входящей оплаты заказ атомарно захватывается одним worker. Marketapp auto-pay выполняется ровно один раз на попытку. Если SDK вернул неоднозначную ошибку после возможной отправки TON-транзакции, автоматического повтора нет: заказ переводится в `MANUAL_REVIEW`. Ручной повтор допустим только после проверки блокчейна.

Операционный `TON_RECEIVER_ADDRESS` рекомендуется делать адресом того же кошелька, чей seed указан в `MARKETAPP_WALLET_SEED`. Для USDT нужен отдельный запас TON на операционном кошельке для закупки/сетевых комиссий.

## Деплой без локального компьютера

См. [DEPLOY.md](DEPLOY.md). Вкратце:

1. Создать бесплатный Supabase project и выполнить `supabase/schema.sql` через SQL Editor.
2. В Render создать Blueprint из этого GitHub-репозитория.
3. Ввести секреты, которые Blueprint помечает `sync: false`.
4. Render сам собирает Python-приложение, поднимает HTTPS webhook и далее автоматически деплоит каждый commit в `main`.

Локальный Node.js, Telegram Serverless CLI и локальный Python для production деплоя не нужны.

> Free Render подходит для тестирования/небольшой нагрузки и засыпает при отсутствии входящего трафика. Для стабильной production-выдачи лучше перейти на постоянно работающий Render instance.

## Эксплуатация

- `/admin_stats` — сводка пользователей, заказов и оборота;
- `/approve_retry <UUID> <причина>` — ручной повтор только после проверки неоднозначной Marketapp/TON транзакции;
- `GET /health` — состояние Supabase и фоновых workers.
