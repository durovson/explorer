# Архитектурное решение

## Почему не Telegram Serverless

BotFather показывает удобное управление Serverless schema и CLI Access, однако полный deploy кода остается CLI-ориентированным. Для этого проекта есть более важное ограничение: Marketapp purchase возвращает/исполняет TON-транзакцию, а автоматическая выдача требует локальной подписи операционным wallet seed.

Хранить seed в сгенерированном JS-модуле Telegram Serverless и реализовывать кошелек без нормальной пакетной среды нецелесообразно. Поэтому проект возвращен на облачный Python backend.

## Выбранная схема

- Render web service: webhook + фоновые workers.
- Supabase: финансовое состояние и атомарные RPC.
- Marketapp API: цены, recipient preflight, Stars/Premium purchase.
- TON Center: подтверждение входящих TON/USDT и wallet provider для auto-pay.
- GitHub main: единственный источник кода; Render auto-deploy.

## Изменения относительно предыдущей версии

- Fragment Connection JWT полностью убран из конфигурации.
- Marketapp API token + отдельный wallet seed хранятся в Render Environment.
- Промокоды не используются и не предусмотрены в FSM/БД/UI.
- Наценка фиксирована: ≈5.2751% TON и 25.3333% USDT.
- Динамическая база цены берется из Marketapp, затем фиксируется в заказе.
- Неоднозначная попытка fulfillment не повторяется автоматически.
