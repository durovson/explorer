# Облачный деплой без локального компьютера

Этот вариант не требует `tgcloud`, Node.js, Python или терминала на вашем компьютере. Нужны только GitHub, Supabase, Render, Telegram BotFather, TON Center и Marketapp.

## 1. Supabase

1. Создайте новый Free project.
2. Откройте **SQL Editor**.
3. Скопируйте весь `supabase/schema.sql`, выполните один раз.
4. В Project Settings → API возьмите Project URL (`SUPABASE_URL`) и service-role key (`SUPABASE_SERVICE_ROLE_KEY`).

Service-role key храните только в Render Environment.

## 2. Marketapp и операционный кошелек

1. Получите Marketapp API token.
2. Используйте отдельный TON-кошелек проекта.
3. Его адрес укажите как `TON_RECEIVER_ADDRESS`.
4. Seed этого же кошелька укажите как `MARKETAPP_WALLET_SEED`.
5. Получите TON Center API key.

Бот использует HTTPS Marketapp API. `http://api.marketapp.org` не применяется: секретный токен нельзя отправлять по незашифрованному HTTP.

Операционный кошелек должен иметь запас TON. Особенно это важно, если клиент платит в USDT: входящий USDT сам по себе не финансирует TON-транзакцию закупки.

## 3. Render Blueprint

1. В Render нажмите **New → Blueprint**.
2. Подключите GitHub и выберите `durovson/explorer`.
3. Render прочитает `render.yaml`.
4. Заполните значения `sync: false`: `TELEGRAM_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `TON_RECEIVER_ADDRESS`, `TONCENTER_API_KEY`, `MARKETAPP_API_TOKEN`, `MARKETAPP_WALLET_SEED`, `ADMIN_IDS`, `SUPPORT_URL`.
5. Создайте Blueprint.

`TELEGRAM_WEBHOOK_SECRET` Render генерирует сам. `APP_BASE_URL` вручную не нужен: приложение берет автоматически созданный `RENDER_EXTERNAL_URL`.

После старта приложение само вызывает Telegram `setWebhook`. Проверка: `https://<ваш-сервис>.onrender.com/health` должна вернуть `ok: true`.

## 4. Автодеплой

`render.yaml` использует `autoDeployTrigger: commit`. После первоначального подключения дальнейший процесс простой:

`изменение main в GitHub → Render build → deploy → новый webhook backend`

Локальный деплой не требуется.

## Ограничение Free Render

Free web service может уснуть после периода без входящего HTTP-трафика и просыпаться при новом Telegram webhook. Фоновые проверки оплаты во время сна не выполняются. Это приемлемо для тестирования, но для магазина с требованием постоянной выдачи рекомендуется always-on instance.
