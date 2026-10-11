import { api, BotApiError } from 'sdk';
import { formatAtomic } from './amounts.js';
import { markupPercent } from './pricing.js';

export const escapeHtml = value => String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
export const button = (text, data) => ({ text, callback_data: data });
export const keyboard = (...rows) => ({ inline_keyboard: rows });
export const homeBack = () => keyboard([button('‹ Главное меню','home')]);
export const itemLabel = order => order.product === 'STARS' ? `${order.quantity} ⭐` : `Premium · ${order.quantity} мес.`;

export function homeKeyboard(config) {
  const rows = [
    [button('⭐ Купить Stars','buy:STARS'),button('💎 Купить Premium','buy:PREMIUM')],
    [button('▤ Мои заказы','orders:0'),button('🎁 Друзья','friends')]
  ];
  const links = [];
  if (config.miniAppUrl) links.push({text:'🚀 Приложение',web_app:{url:config.miniAppUrl}});
  if (config.supportUrl) links.push({text:'💬 Поддержка',url:config.supportUrl});
  if (links.length) rows.push(links);
  rows.push([button('⚙ Настройки','settings')]);
  return {inline_keyboard:rows};
}

// All screens are plain text. This also replaces legacy photo/GIF cards safely.
export async function render(message, text, replyMarkup = homeBack()) {
  const params = {chat_id:message.chat.id,text,parse_mode:'HTML',reply_markup:replyMarkup,link_preview_options:{is_disabled:true}};
  if (!message.animation && !message.photo && !message.video && message.message_id) {
    try { return await api.editMessageText({...params,message_id:message.message_id}); }
    catch (error) {
      if (!(error instanceof BotApiError) || error.code !== 400) throw error;
      if (/message is not modified/i.test(error.description)) return message;
      if (!/message to edit not found|message can't be edited|no text in the message/i.test(error.description)) throw error;
    }
  }
  return api.sendMessage(params);
}

export async function send(chatId,text,replyMarkup = homeBack()) {
  return api.sendMessage({chat_id:chatId,text,parse_mode:'HTML',reply_markup:replyMarkup,link_preview_options:{is_disabled:true}});
}

export function feeText(q) {
  const c = q.currency;
  const baseLabel = q.product === 'STARS' ? (c === 'USDT' ? 'Цена Stars в USD × 1 USDT/USD' : 'Цена Stars на Fragment') : 'Цена товара';
  return `${baseLabel}: <b>${formatAtomic(q.baseAtomic,c)} ${c}</b>\n` +
    `Надбавка сервиса (${markupPercent(q.baseAtomic,q.markupAtomic)}%): <b>${formatAtomic(q.markupAtomic,c)} ${c}</b>\n` +
    `Дополнительная комиссия: <b>${formatAtomic(q.providerFeeAtomic,c)} ${c}</b>\n` +
    `Итого: <b>${formatAtomic(q.amountAtomic,c)} ${c}</b>\n` +
    'Комиссия сети оплачивается кошельком отдельно и в сумму заказа не входит.';
}

const statusLabels = {
  WAITING_PAYMENT:'Ожидает оплаты',PAID:'Оплачен',FULFILLING:'Отправляется',COMPLETED:'Завершён',
  REVIEW:'Нужна проверка поддержки',FAILED:'Не выполнен — обратитесь в поддержку',CANCELLED:'Отменён',EXPIRED:'Время оплаты истекло'
};

export function paymentText(order) {
  let text = `<b>Заказ #${order.id} · ${escapeHtml(statusLabels[order.status] || order.status)}</b>\n\n` +
    `${itemLabel(order)} → <b>${escapeHtml(order.recipient)}</b>\n\n${feeText(order)}`;
  if (order.status === 'WAITING_PAYMENT' && Math.floor(Date.now()/1000) <= order.expiresAt) {
    text += `\n\nСеть: <b>TON mainnet</b>\nАдрес:\n<code>${escapeHtml(order.walletAddress)}</code>` +
      `\n\nКомментарий (memo):\n<code>${escapeHtml(order.memo)}</code>\n\n` +
      `Отправьте ровно ${formatAtomic(order.amountAtomic,order.currency)} ${order.currency} с этим комментарием.\n` +
      `Оплатить до: ${new Date(order.expiresAt * 1000).toISOString().replace('T',' ').slice(0,16)} UTC.\n` +
      'После перевода нажмите «Проверить оплату». Транзакция должна попасть в блокчейн до окончания срока.';
  }
  if(order.status==='WAITING_PAYMENT' && Math.floor(Date.now()/1000)>order.expiresAt) {
    text += '\n\nСрок оплаты истёк. Не отправляйте новые переводы по этому заказу. Можно проверить платеж, отправленный в пределах срока оплаты, даже если он появился в индексаторе позже.';
  }
  if (order.txHash) text += `\n\nТранзакция: <code>${escapeHtml(order.txHash)}</code>`;
  return text;
}

export function paymentKeyboard(order) {
  const rows = [];
  if (order.status === 'WAITING_PAYMENT') {
    // TON deep links are copyable text; Bot API URL buttons require HTTP(S)/tg.
    rows.push([button('↻ Проверить оплату',`check:${order.id}`)]);
  } else if (['PAID','FULFILLING','REVIEW'].includes(order.status)) {
    rows.push([button('↻ Обновить статус',`check:${order.id}`)]);
  }
  rows.push([button('▤ Мои заказы','orders:0'),button('‹ Главное меню','home')]);
  return {inline_keyboard:rows};
}
