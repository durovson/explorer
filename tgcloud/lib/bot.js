import { api, fetch } from 'sdk';
import { config, requireSales } from './config.js';
import * as store from './store.js';
import { findPayment } from './chain.js';
import { fulfill, reconcile } from './fulfillment.js';
import { quote, normalizeRecipient, markupPercent } from './pricing.js';
import { getFragmentPrices } from './fragment-prices.js';
import { formatAtomic } from './amounts.js';
import { button, keyboard, homeBack, homeKeyboard, send, render as renderCard, escapeHtml, itemLabel, feeText, paymentText, paymentKeyboard } from './ui.js';

const now = () => Math.floor(Date.now()/1000);
const positiveId = raw => { if (!/^[1-9]\d*$/.test(raw)) throw new Error('Заказ не найден'); const n=Number(raw); if(!Number.isSafeInteger(n)) throw new Error('Заказ не найден'); return n; };
const checkoutToken = data => `${String(data.sessionKey).slice(-16)}_${data.revision || 0}`;
const sessionOrThrow = async (uid,message) => {
  const s=await store.getSession(uid);
  if(!s) throw new Error('Сессия завершена. Начните покупку заново.');
  if(message && (s.data.chatId!==message.chat.id || s.data.messageId!==message.message_id)) throw new Error('Кнопка устарела. Откройте текущий экран покупки.');
  return s;
};
const saveWizard = (uid,state,data) => store.saveSession(uid,state,{...data,revision:(data.revision || 0)+1});

async function render(message,text,markup) {
  const session=await store.getSession(message.chat.id);
  if(session && markup?.inline_keyboard) {
    markup={inline_keyboard:markup.inline_keyboard.map(row=>row.map(b=>{
      if(!/^(recipient|quantity|currency|custom)(:|$)/.test(b.callback_data || '')) return b;
      const [action,arg='']=b.callback_data.split(':');
      return {...b,callback_data:`${action}:${arg}:${checkoutToken(session.data)}`};
    }))};
  }
  const result=await renderCard(message,text,markup);
  if(result?.message_id && result.message_id!==message.message_id) {
    const s=await store.getSession(message.chat.id);
    if(s && s.data.messageId===message.message_id) {
      await store.saveSession(message.chat.id,s.state,{...s.data,chatId:message.chat.id,messageId:result.message_id});
    }
  }
  return result;
}

async function home(message) {
  const totals = await store.stats();
  await render(message, `<b>Добро пожаловать в ${escapeHtml(config.shopName)}!</b>\n\n` +
    'Здесь можно купить Telegram Stars и Premium для себя или в подарок.\n\n' +
    'Оплата: TON или USDT в сети TON. Все комиссии видны до оплаты.\n' +
    `Завершено заказов: <b>${totals.completed || 0}</b> · Куплено Stars: <b>${totals.stars || 0}</b>`, homeKeyboard(config));
}

async function showProducts(message, uid) {
  const s = await sessionOrThrow(uid,message);
  const data=s.data;
  await saveWizard(uid,'quantity',data);
  const options = data.product === 'STARS' ? [50,100,250,500,1000,2500,5000,10000] : [3,6,12];
  const rows=[];
  for(let i=0;i<options.length;i+=2) rows.push(options.slice(i,i+2).map(n=>button(data.product==='STARS'?`${n} ⭐`:`${n} мес.`,`quantity:${n}`)));
  if(data.product==='STARS') rows.push([button('Другое количество','custom')]);
  rows.push([button('‹ Получатель','recipient:choose'),button('‹ Главное меню','home')]);
  await render(message, `<b>${data.product==='STARS'?'⭐ Купить Stars':'💎 Купить Premium'}</b>\n\nПолучатель: <b>${escapeHtml(data.recipient)}</b>\nВыберите ${data.product==='STARS'?'количество':'срок'}:`,{inline_keyboard:rows});
}

async function showRecipient(message,uid,user) {
  const s=await sessionOrThrow(uid,message);
  await saveWizard(uid,'recipient_choice',s.data);
  const rows=[];
  if(user.username) rows.push([button('Купить себе','recipient:self')]);
  rows.push([button('Подарить по @username','recipient:other')],[button('‹ Главное меню','home')]);
  await render(message,'<b>🎁 Получатель</b>\n\nКому отправить покупку?',{inline_keyboard:rows});
}

async function showCurrencies(message,uid,quantity) {
  const s=await sessionOrThrow(uid,message);
  let pricingConfig = config;
  if (s.data.product === 'STARS' && config.priceSource === 'fragment') {
    const prices = await getFragmentPrices();
    pricingConfig = {...config,stars:{TON:{...config.stars.TON,basePerUnit:prices.TON},USDT:{...config.stars.USDT,basePerUnit:prices.USDT}}};
  }
  const quotes={};
  for(const currency of ['TON','USDT']) {
    try { quotes[currency]=quote(s.data.product,quantity,currency,pricingConfig); } catch (_) { /* unavailable tariff */ }
  }
  if(!Object.keys(quotes).length) throw new Error('Этот тариф пока недоступен.');
  const data={...s.data,quantity,quotes,quotedAt:now()};
  await saveWizard(uid,'currency',data);
  const rows=Object.values(quotes).map(q=>[button(`${formatAtomic(q.amountAtomic,q.currency)} ${q.currency}`,`currency:${q.currency}`)]);
  rows.push([button('‹ Количество','quantity:back'),button('‹ Главное меню','home')]);
  const fees=Object.values(quotes).map(q=>`<b>${q.currency}</b>\n${feeText(q)}`).join('\n\n');
  await render(message,`<b>${itemLabel(data)}</b> → <b>${escapeHtml(data.recipient)}</b>\n\n${fees}\n\nВыберите валюту:`,{inline_keyboard:rows});
}

async function recipientExists(recipient) {
  const res=await fetch(`${config.fragment.baseUrl}/misc/user/${encodeURIComponent(recipient.slice(1))}/`,{headers:{Authorization:`JWT ${config.fragment.jwt}`,Accept:'application/json'}});
  if(res.status===404) throw new Error('Получатель не найден. Проверьте @username.');
  if(!res.ok) throw new Error('Проверка получателя временно недоступна.');
  const user=await res.json();
  if(!user || typeof user.username !== 'string' || user.username.toLowerCase()!==recipient.slice(1).toLowerCase()) throw new Error('Проверка получателя временно недоступна.');
}

async function refreshOrder(order) {
  if(order.status==='WAITING_PAYMENT') {
    const payment=await findPayment(order,{...config,receiverAddress:order.walletAddress});
    if(payment) order=await store.markPaid(order.id,order.userId,payment) || await store.getOrder(order.id,order.userId);
    // Do not expire a late-indexed payment automatically. Expired invoices remain
    // searchable; timestamps in matchesPayment reject transfers sent after TTL.
  }
  if(order.status==='PAID') order=await fulfill(order,config);
  else if(order.status==='FULFILLING' || (order.status==='REVIEW' && order.externalId)) order=await reconcile(order,config);
  return order;
}

export async function onMessage(message,ctx={}) {
  if(message.chat?.type!=='private' || !message.from || message.from.is_bot) return;
  const uid=message.from.id;
  await store.ensureUser(message.from);
  const text=String(message.text || '').trim();
  if(/^\/start(?:@\w+)?(?:\s|$)/.test(text) || text==='/menu') {
    const ref=text.match(/\sref_(\d+)$/);
    if(ref) await store.setReferrer(uid,Number(ref[1]));
    await store.clearSession(uid);
    const newMessage=await send(message.chat.id,'Загружаем меню…',homeKeyboard(config));
    await home(newMessage);
    return;
  }
  if(text==='/admin_stats') {
    if(!config.adminIds.includes(uid)) return;
    const stats=await store.stats();
    await send(message.chat.id,`<b>Статистика</b>\nПользователей: ${stats.users}\nЗаказов: ${stats.orders}\nЗавершено: ${stats.completed}\nStars: ${stats.stars}`);
    return;
  }
  const s=await store.getSession(uid);
  if(!s) { await send(message.chat.id,'Откройте меню командой /start.',homeKeyboard(config)); return; }
  const card={chat:{id:s.data.chatId},message_id:s.data.messageId};
  try {
    requireSales();
    if(s.state==='recipient_input') {
      const recipient=normalizeRecipient(text);
      await saveWizard(uid,'quantity',{...s.data,recipient});
      await showProducts(card,uid);
    } else if(s.state==='custom_quantity') {
      if(!/^\d+$/.test(text)) throw new Error('Введите целое число от 50 до 1 000 000.');
      const quantity=Number(text);
      if(quantity<50 || quantity>1000000 || !Number.isSafeInteger(quantity)) throw new Error('Введите целое число от 50 до 1 000 000.');
      await showCurrencies(card,uid,quantity);
    } else await send(message.chat.id,'Выберите действие кнопкой ниже.',homeKeyboard(config));
  } catch(error) { await send(message.chat.id,escapeHtml(error.message)); }
}

export async function onCallback(query) {
  if(query.message?.chat?.type!=='private' || !query.from || query.from.is_bot) return;
  await api.answerCallbackQuery({callback_query_id:query.id});
  const message=query.message, uid=query.from.id, raw=String(query.data || ''), [action,arg,token]=raw.split(':');
  await store.ensureUser(query.from);
  try {
    if(['recipient','quantity','custom','currency'].includes(action)) {
      const s=await sessionOrThrow(uid,message);
      if(token!==checkoutToken(s.data)) throw new Error('Кнопка устарела. Откройте текущий экран покупки.');
    }
    if(action==='home') { await store.clearSession(uid); await home(message); return; }
    if(action==='buy' && ['STARS','PREMIUM'].includes(arg)) {
      requireSales();
      await saveWizard(uid,'recipient_choice',{product:arg,sessionKey:query.id,chatId:message.chat.id,messageId:message.message_id});
      await showRecipient(message,uid,query.from); return;
    }
    if(action==='recipient') {
      requireSales(); const s=await sessionOrThrow(uid,message);
      if(arg==='choose') { await showRecipient(message,uid,query.from); return; }
      if(s.state!=='recipient_choice') throw new Error('Кнопка устарела. Начните покупку заново.');
      if(arg==='self') {
        if(!query.from.username) throw new Error('Установите username в настройках Telegram.');
        await saveWizard(uid,'quantity',{...s.data,recipient:normalizeRecipient(query.from.username)});
        await showProducts(message,uid);
      } else if(arg==='other') {
        await saveWizard(uid,'recipient_input',s.data);
        await render(message,'<b>🎁 Получатель</b>\n\nВведите @username получателя:',homeBack());
      } else throw new Error('Неизвестная кнопка');
      return;
    }
    if(action==='quantity' || action==='custom') {
      requireSales(); const s=await sessionOrThrow(uid,message);
      if(!s.data.recipient) throw new Error('Сначала выберите получателя.');
      if(arg==='back') { await showProducts(message,uid); return; }
      if(s.state!=='quantity') throw new Error('Кнопка устарела.');
      if(action==='custom' && s.data.product==='STARS') {
        await saveWizard(uid,'custom_quantity',s.data);
        await render(message,'<b>⭐ Количество Stars</b>\n\nВведите целое число от 50 до 1 000 000:',homeBack());
      } else {
        const quantity=positiveId(arg || '');
        await showCurrencies(message,uid,quantity);
      }
      return;
    }
    if(action==='currency') {
      requireSales(); const s=await sessionOrThrow(uid,message);
      if(s.state!=='currency' || !s.data.quotes?.[arg]) throw new Error('Кнопка устарела. Начните покупку заново.');
      if(now()-s.data.quotedAt>300) throw new Error('Цена устарела. Начните покупку заново.');
      await recipientExists(s.data.recipient);
      const order=await store.createOrder({...s.data.quotes[arg],userId:uid,recipient:s.data.recipient,
        walletAddress:config.receiverAddress,creationKey:`${uid}:${s.data.sessionKey}:${s.data.recipient}:${s.data.product}:${s.data.quantity}:${arg}:${s.data.quotes[arg].amountAtomic}`,createdAt:now(),expiresAt:now()+config.paymentTtlSeconds,
        chatId:message.chat.id,messageId:message.message_id});
      await render(message,paymentText(order),paymentKeyboard(order)); return;
    }
    if(['check','order','cancel'].includes(action)) {
      let order=await store.getOrder(positiveId(arg || ''),uid);
      if(!order) throw new Error('Заказ не найден.');
      if(action==='cancel') {
        await send(message.chat.id,'Реквизиты этого заказа уже выданы. Можно вернуться в меню; ранее отправленный платеж останется доступен для проверки.',homeBack()); return;
      }
      order=await refreshOrder(order);
      await render(message,paymentText(order),paymentKeyboard(order)); return;
    }
    if(action==='orders') {
      const page=/^\d+$/.test(arg || '')?Math.min(Number(arg),10000):0;
      const {items,hasNext}=await store.listOrders(uid,page);
      const text=items.length?items.map(o=>`#${o.id} · ${itemLabel(o)} → ${escapeHtml(o.recipient)}\n${formatAtomic(o.amountAtomic,o.currency)} ${o.currency} · ${escapeHtml(o.status)}`).join('\n\n'):'Заказов пока нет.';
      const rows=items.map(o=>[button(`Заказ #${o.id}`,`order:${o.id}`)]);
      const paging=[]; if(page>0) paging.push(button('‹ Назад',`orders:${page-1}`)); if(hasNext) paging.push(button('Далее ›',`orders:${page+1}`));
      if(paging.length) rows.push(paging); rows.push([button('‹ Главное меню','home')]);
      await render(message,`<b>▤ Мои заказы</b>\n\n${text}`,{inline_keyboard:rows}); return;
    }
    if(action==='friends') {
      const stats=await store.referralStats(uid);
      const username=config.botUsername || (await api.getMe()).username;
      const link=`https://t.me/${username}?start=ref_${uid}`;
      await render(message,`<b>🎁 Друзья</b>\n\nВаша ссылка:\n<code>${escapeHtml(link)}</code>\n\nПриглашено: ${stats.invited}\nЗавершённых заказов друзей: ${stats.completed}\n\nДенежная реферальная программа пока не включена.`,homeBack()); return;
    }
    if(action==='settings') {
      const rates=['TON','USDT'].map(c=>{
        const rate=config.stars[c];
        if(!rate?.basePerUnit) return `${c}: тариф не настроен`;
        const q=quote('STARS',100,c,config);
        return `${c}: надбавка ${markupPercent(q.baseAtomic,q.markupAtomic)}%, дополнительная комиссия ${escapeHtml(rate.providerFee || '0')} ${c}`;
      }).join('\n');
      await render(message,`<b>⚙ Настройки и комиссии</b>\n\n${rates}\n\nЦена Stars в TON обновляется с Fragment перед выбором валюты. Для USDT используется долларовая цена Stars по курсу 1 USD = 1 USDT; надбавка включает расходы сервиса.\nКомиссию сети показывает кошелёк перед отправкой.\nЯзык: русский. Оплата каждого заказа отдельным переводом.\n${config.salesEnabled?'Продажи открыты.':'Продажи временно закрыты.'}`,homeBack()); return;
    }
    throw new Error('Кнопка устарела. Откройте меню.');
  } catch(error) {
    // Provider/indexer failures must never claim a successful payment.
    const permanentScanErrors=['AMBIGUOUS_PAYMENT','SCAN_INCOMPLETE','INVALID_CONFIG','INVALID_ORDER','TRACE_LIMIT','WALLET_UNVERIFIED'];
    if(error.name==='PaymentScanError') console.warn('Payment check stopped',{code:error.code,orderId:arg || null});
    const text=error.name==='PaymentScanError'?(permanentScanErrors.includes(error.code)?
      'Оплата требует проверки поддержки. Сообщите номер заказа; автоматическое подтверждение остановлено.':
      'Не удалось завершить проверку сети. Повторите позже; заказ не подтверждён.'):
      /^Получатель|^Проверка|^Сессия|^Кнопка|^Заказ|^Продажи|^Этот тариф|^Сначала|^Цена|^Установите|^Неизвестная/.test(error.message)?error.message:'Сервис временно недоступен. Попробуйте позже.';
    await send(message.chat.id,escapeHtml(text),homeBack());
  }
}
