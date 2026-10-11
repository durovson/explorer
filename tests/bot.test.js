import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import * as schema from '../tgcloud/schema.js';
import { db,resetDatabase,setFetch,apiCalls } from './sdk-mock.js';
import { config } from '../tgcloud/lib/config.js';
import { onCallback,onMessage } from '../tgcloud/lib/bot.js';
import { getSession,getOrder,listOrders } from '../tgcloud/lib/store.js';
import { paymentText,paymentKeyboard } from '../tgcloud/lib/ui.js';

const user={id:1001,username:'alice_user',first_name:'Alice'};
const wallet=`0:${'1'.repeat(64)}`;
const otherWallet=`0:${'2'.repeat(64)}`;
const message={message_id:42,chat:{id:user.id,type:'private'},text:'menu'};
let queryCount=0,posts=0,preflights=0,networkRows=[];
const response=data=>({ok:true,status:200,json:async()=>data});
const click=async(data,from=user,id)=>{
  if(/^(recipient|quantity|currency|custom)(:|$)/.test(data)) {
    const s=await getSession(from.id);
    const [action,arg='']=data.split(':');
    data=`${action}:${arg}:${s?`${String(s.data.sessionKey).slice(-16)}_${s.data.revision || 0}`:'expired'}`;
  }
  return onCallback({id:id || `query-${++queryCount}`,from,message:{...message,chat:{...message.chat,id:from.id}},data});
};
async function begin(quantity=100) {
  await click('buy:STARS'); await click('recipient:self'); await click(`quantity:${quantity}`); await click('currency:TON');
  return (await listOrders(user.id)).items[0];
}
function tx(order,at=order.createdAt) {
  return {account:order.walletAddress,hash:'a'.repeat(64),lt:'100',now:at,finality:'finalized',emulated:false,mc_block_seqno:1,
    description:{aborted:false,compute_ph:{success:true,skipped:false,exit_code:0}},out_msgs:[],
    in_msg:{source:otherWallet,destination:order.walletAddress,value:order.amountAtomic,bounced:false,opcode:'0x00000000',
      message_content:{decoded:{'@type':'text_comment',text:order.memo}}}};
}
beforeEach(()=>{
  resetDatabase(schema); queryCount=0;posts=0;preflights=0;networkRows=[];
  Object.assign(config,{priceSource:'manual',salesEnabled:true,pricingVerified:true,receiverAddress:wallet,toncenterApiKey:'test-only',
    botUsername:'TestShopBot',supportUrl:'',miniAppUrl:'',paymentTtlSeconds:900,
    stars:{TON:{basePerUnit:'0.01',markupBps:500,providerFee:'0.05'},USDT:{basePerUnit:'0.015',markupBps:500,providerFee:'0'}},
    premium:{TON:{3:'4',6:'8',12:'15'},USDT:{3:'10',6:'20',12:'40'}},
    fragment:{baseUrl:'https://api.fragment-api.com/v1',jwt:'test-only'}});
  setFetch(async(url,options)=>{
    if(url.includes('/misc/user/')) {preflights++;return response({username:'alice_user'});}
    if(url.includes('/transactions?')) return response({transactions:networkRows});
    if(options?.method==='POST' && url.endsWith('/order/stars/')) {
      posts++;const payload=JSON.parse(options.body);
      return response({id:'provider-1',status:'COMPLETED',success:true,receiver:payload.username,type:'STARS',goods_quantity:payload.quantity});
    }
    throw new Error('Unexpected HTTP in test');
  });
});

test('private start and every checkout screen use text only with disclosed fees',async()=>{
  await onMessage({...message,from:user,text:'/start'});
  const order=await begin();
  assert.equal(order.amountAtomic,'1100000000');
  assert.equal((await getSession(user.id)).state,'currency');
  assert.equal(preflights,1);
  const paymentScreen=apiCalls.filter(c=>c.method==='editMessageText').at(-1).params;
  assert.match(paymentScreen.text,/Надбавка сервиса \(5%\)/);
  assert.match(paymentScreen.text,/Дополнительная комиссия/);
  assert.match(paymentScreen.text,/SM-1/);
  assert.equal(apiCalls.some(c=>/Animation|Photo|Video|Media/.test(String(c.method))),false);
});
test('repeated currency callbacks allocate one invoice; changed quantity allocates a fresh snapshot',async()=>{
  const first=await begin(100);
  await click('currency:TON');
  assert.equal((await listOrders(user.id)).items.length,1);
  await click('quantity:back');await click('quantity:250');await click('currency:TON');
  const items=(await listOrders(user.id)).items;
  assert.equal(items.length,2);assert.equal(items[0].quantity,250);assert.notEqual(items[0].id,first.id);
  assert.equal((await getOrder(first.id,user.id)).quantity,100);
});
test('checking a valid payment completes one purchase and never submits a second POST',async()=>{
  const order=await begin();networkRows=[tx(order)];
  await click(`check:${order.id}`);await click(`check:${order.id}`);
  assert.equal((await getOrder(order.id,user.id)).status,'COMPLETED');assert.equal(posts,1);
});
test('another user cannot inspect or verify an invoice, or trigger delivery',async()=>{
  const order=await begin();networkRows=[tx(order)];
  await click(`check:${order.id}`,{id:2002,username:'bob_user',first_name:'Bob'});
  assert.equal(posts,0);assert.equal((await getOrder(order.id,user.id)).status,'WAITING_PAYMENT');
  assert.match(apiCalls.at(-1).params.text,/Заказ не найден/);
});
test('rotation of operator wallet preserves payment verification of an existing invoice',async()=>{
  const order=await begin();config.receiverAddress=otherWallet;networkRows=[tx(order)];
  await click(`order:${order.id}`);
  assert.equal((await getOrder(order.id,user.id)).status,'COMPLETED');
});
test('issued invoices stay searchable after leaving checkout and after late indexing',async()=>{
  const order=await begin();
  await db.run('UPDATE orders SET created_at=:start,expires_at=:end WHERE id=:id',{
    ':start':order.createdAt-1200,':end':order.createdAt-300,':id':order.id});
  const expired=await getOrder(order.id,user.id);
  assert.match(paymentText(expired),/Не отправляйте новые переводы/);
  assert.equal(paymentKeyboard(expired).inline_keyboard.flat().some(b=>b.callback_data?.startsWith('cancel:')),false);
  await click(`cancel:${order.id}`);assert.equal((await getOrder(order.id,user.id)).status,'WAITING_PAYMENT');
  await click('home');networkRows=[tx(expired,expired.createdAt+100)];
  await click(`check:${order.id}`);assert.equal((await getOrder(order.id,user.id)).status,'COMPLETED');
});
test('indexer failure, disabled sales and stale callbacks fail without side effects',async()=>{
  const order=await begin();
  setFetch(async()=>{throw new Error('Indexer unavailable');});
  await click(`check:${order.id}`);assert.equal((await getOrder(order.id,user.id)).status,'WAITING_PAYMENT');assert.equal(posts,0);
  config.salesEnabled=false;await click('buy:STARS');assert.match(apiCalls.at(-1).params.text,/Продажи временно закрыты/);
  await click('home');config.salesEnabled=true;await click('currency:TON');
  assert.equal((await listOrders(user.id)).items.length,1);
});
test('group messages cannot create users or expose a private invoice',async()=>{
  await onMessage({...message,chat:{id:-100,type:'group'},from:user,text:'/start'});
  assert.equal(apiCalls.length,0);assert.equal((await db.get('SELECT COUNT(*) AS n FROM users')).n,0);
});
test('replacing a legacy GIF card updates the durable input target',async()=>{
  await onCallback({id:'legacy-buy',from:user,data:'buy:STARS',message:{...message,animation:{file_id:'legacy'}}});
  const s=await getSession(user.id);
  assert.notEqual(s.data.messageId,message.message_id);
  assert.equal(apiCalls.at(-1).method,'sendMessage');
  assert.equal(s.data.messageId,apiCalls.length);
});
test('buttons from a previous checkout revision or another message cannot change the new order',async()=>{
  await click('buy:STARS');await click('recipient:self');await click('quantity:100');
  const oldCurrency=apiCalls.filter(c=>c.method==='editMessageText').at(-1).params.reply_markup.inline_keyboard.flat().find(b=>b.callback_data?.startsWith('currency:TON')).callback_data;
  await click('quantity:back');await click('quantity:250');
  await onCallback({id:'stale-old-price',from:user,message,data:oldCurrency});
  assert.equal((await listOrders(user.id)).items.length,0);
  assert.match(apiCalls.at(-1).params.text,/Кнопка устарела/);
  const s=await getSession(user.id);
  await onCallback({id:'stale-message',from:user,message:{...message,message_id:999},data:`currency:TON:${String(s.data.sessionKey).slice(-16)}_${s.data.revision}`});
  assert.equal((await listOrders(user.id)).items.length,0);
  await click('currency:TON');assert.equal((await listOrders(user.id)).items[0].quantity,250);
});
test('live Fragment price replaces the configured snapshot before invoice creation',async()=>{
  config.priceSource='fragment';
  config.stars.TON={basePerUnit:'0.01',markupBps:0,markupRatio:{numerator:'539612',denominator:'10229388'},providerFee:'0'};
  config.stars.USDT={basePerUnit:'0.01',markupBps:0,markupRatio:{numerator:'19',denominator:'75'},providerFee:'0'};
  let priceReads=0;
  setFetch(async(url)=>{
    if(url==='https://fragment.com/stars/buy') return {ok:true,status:200,url,headers:{get:()=> 'stel_ssid=anonymous_test_session_123456; path=/'},text:async()=> 'ajInit({"apiUrl":"/api?hash=0123456789abcdef12","unauth":true});'};
    if(url.startsWith('https://fragment.com/api?hash=')) {priceReads++;return {ok:true,status:200,url,json:async()=>({ok:true,cur_price:'<div class="icon-usd">150,000</div><div class="icon-ton">105,000</div>'})};}
    if(url.includes('/misc/user/')) return response({username:'alice_user'});
    throw new Error('Unexpected HTTP');
  });
  const order=await begin();
  assert.equal(priceReads,1);assert.equal(order.baseAtomic,'1050000000');assert.equal(order.amountAtomic,'1105388710');
  assert.equal((await getSession(user.id)).data.quotes.USDT.amountAtomic,'1880000');
});
test('unavailable Fragment blocks a new quote rather than using stale configured prices',async()=>{
  config.priceSource='fragment';setFetch(async()=>{throw new Error('offline');});
  await click('buy:STARS');await click('recipient:self');await click('quantity:100');
  assert.equal((await getSession(user.id)).state,'quantity');
  await click('currency:TON');assert.equal((await listOrders(user.id)).items.length,0);
});
