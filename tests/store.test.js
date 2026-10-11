import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import * as schema from '../tgcloud/schema.js';
import { db, resetDatabase, setFetch } from './sdk-mock.js';
import {
  ensureUser, setReferrer, getSession, saveSession, clearSession, listOrders,
  getOrder, getOrderInternal, createOrder, markPaid, cancelOrder, expireOrder,
  claimFulfillment, finishOrder, stats, referralStats,
} from '../tgcloud/lib/store.js';
import { fulfill, reconcile } from '../tgcloud/lib/fulfillment.js';

const WALLET = `0:${'1'.repeat(64)}`;
const OTHER_WALLET = `0:${'2'.repeat(64)}`;
const CONFIG = { fragment: { baseUrl: 'https://api.fragment-api.com/v1', jwt: 'test-only-placeholder' } };
const uid = 1001;
const otherUid = 2002;
const values = (key = 'quote-1', overrides = {}) => ({
  userId: uid, recipient: 'example_user', product: 'STARS', quantity: 100,
  currency: 'TON', amountAtomic: '1050000000', baseAtomic: '1000000000',
  markupAtomic: '50000000', providerFeeAtomic: '0', markupBps: 500,
  walletAddress: WALLET, creationKey: key, chatId: uid, messageId: 10,
  ...overrides,
});
const payment = (order, overrides = {}) => ({
  currency: order.currency, txHash: 'a'.repeat(64), amountAtomic: order.amountAtomic,
  destination: order.walletAddress, memo: order.memo, timestamp: order.createdAt,
  confirmed: true, success: true, aborted: false, txLt: '12345678901234567890', sender: OTHER_WALLET,
  ...overrides,
});
const providerOrder = (order, overrides = {}) => ({
  id: '20f9c013-460d-40dc-bb74-6fe1b37a93b0', receiver: order.recipient,
  type: order.product, goods_quantity: order.quantity, status: 'COMPLETED', success: true,
  ...overrides,
});
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
async function paidOrder(key = 'quote-1', overrides = {}) {
  const order = await createOrder(values(key, overrides));
  return markPaid(order.id, order.userId, payment(order, { txHash: String(order.id).padStart(64, '0') }));
}

beforeEach(async () => {
  resetDatabase(schema);
  await ensureUser({ id: uid, username: 'buyer', first_name: 'Buyer' });
  await ensureUser({ id: otherUid, username: 'another', first_name: 'Another' });
});

test('durable session JSON survives user updates and expires after 24 hours', async () => {
  const data = { quoteKey: 'callback-42', quantity: 100, priceAtomic: '900719925474099312345' };
  await saveSession(uid, 'QUANTITY', data);
  await ensureUser({ id: uid, username: 'renamed', first_name: 'Renamed' });
  assert.deepEqual(await getSession(uid), { state: 'QUANTITY', data });
  await db.run('UPDATE sessions SET updated_at=:past WHERE user_id=:uid', { ':past': Math.floor(Date.now() / 1000) - 86401, ':uid': uid });
  assert.equal(await getSession(uid), null);
  await clearSession(uid);
  assert.equal(await getSession(uid), null);
  await assert.rejects(saveSession(9999, 'X', {}), /User must exist/);
});

test('one immutable invoice and one memo are allocated across 20 callback replays', async () => {
  const orders = await Promise.all(Array.from({ length: 20 }, () => createOrder(values('same-quote'))));
  assert.equal(new Set(orders.map((o) => o.id)).size, 1);
  assert.equal(new Set(orders.map((o) => o.memo)).size, 1);
  const replay = await createOrder(values('same-quote', { quantity: 200, amountAtomic: '2100000000', baseAtomic: '2000000000', markupAtomic: '100000000' }));
  assert.equal(replay.quantity, 100);
  assert.equal(replay.amountAtomic, '1050000000');
  assert.equal((await stats()).orders, 1);
  await assert.rejects(createOrder(values('same-quote', { userId: otherUid })), /Invoice allocation/);
});

test('memo allocation crash fails closed and creation replay repairs the same invoice', async () => {
  const order = await createOrder(values());
  await db.run('UPDATE orders SET memo=NULL WHERE id=:id', { ':id': order.id });
  assert.equal(await markPaid(order.id, uid, payment(order)), null);
  const repaired = await createOrder(values());
  assert.equal(repaired.id, order.id);
  assert.equal(repaired.memo, order.memo);
  assert.equal((await stats()).orders, 1);
});

test('owner isolation applies to reads, payment confirmation and cancellation', async () => {
  const order = await createOrder(values());
  assert.equal(await getOrder(order.id, otherUid), null);
  assert.equal(await markPaid(order.id, otherUid, payment(order)), null);
  assert.equal(await cancelOrder(order.id, otherUid), null);
  assert.deepEqual(await listOrders(otherUid), { items: [], hasNext: false });
  assert.equal((await getOrder(order.id, uid)).status, 'WAITING_PAYMENT');
});

test('unsafe numeric atomic amounts and inconsistent quote totals never enter storage', async () => {
  for (const overrides of [
    { amountAtomic: 1050000000 }, { amountAtomic: '01050000000' },
    { amountAtomic: '1050000001' }, { quantity: 49 }, { quantity: 1.5 },
    { product: 'PREMIUM', quantity: 1 },
  ]) await assert.rejects(createOrder(values('invalid', overrides)));
  assert.equal((await stats()).orders, 0);
  const large = await createOrder(values('large', {
    amountAtomic: '900719925474099300050', baseAtomic: '900719925474099300000', markupAtomic: '50',
  }));
  assert.equal(large.amountAtomic, '900719925474099300050');
});

test('payment proof must match destination, exact memo, amount and quote time window', async () => {
  const order = await createOrder(values());
  for (const overrides of [
    { destination: OTHER_WALLET }, { memo: `${order.memo} ` }, { amountAtomic: '1049999999' },
    { amountAtomic: Number(order.amountAtomic) }, { currency: 'USDT' },
    { timestamp: order.createdAt - 1 }, { timestamp: order.expiresAt + 1 },
    { success: false }, { aborted: true }, { confirmed: false },
  ]) assert.equal(await markPaid(order.id, uid, payment(order, overrides)), null);
  assert.equal((await markPaid(order.id, uid, payment(order))).status, 'PAID');
});

test('one transaction hash cannot be reused, and concurrent confirmations win once', async () => {
  const first = await createOrder(values('first'));
  const second = await createOrder(values('second'));
  const results = await Promise.all(Array.from({ length: 10 }, () => markPaid(first.id, uid, payment(first))));
  assert.equal(results.filter(Boolean).length, 1);
  assert.equal(await markPaid(second.id, uid, payment(second)), null);
  assert.equal((await getOrder(second.id, uid)).status, 'WAITING_PAYMENT');
  const winner = await markPaid(second.id, uid, payment(second, { txHash: 'b'.repeat(64) }));
  assert.equal(winner.status, 'PAID');
});

test('payment/cancel race uses one atomic state winner and never cancels paid orders', async () => {
  const order = await createOrder(values());
  const results = await Promise.all([markPaid(order.id, uid, payment(order)), cancelOrder(order.id, uid)]);
  assert.equal(results.filter(Boolean).length, 1);
  const final = await getOrder(order.id, uid);
  assert.ok(['PAID', 'CANCELLED'].includes(final.status));
  if (final.status === 'PAID') assert.equal(await cancelOrder(order.id, uid), null);
  else assert.equal(await markPaid(order.id, uid, payment(order)), null);
});

test('expired invoice cannot be claimed and cancelled invoices cannot be paid', async () => {
  const order = await createOrder(values());
  await db.run('UPDATE orders SET created_at=:created,expires_at=:expires WHERE id=:id', {
    ':created': order.createdAt - 100, ':expires': order.createdAt - 1, ':id': order.id,
  });
  assert.equal((await expireOrder(order.id, uid)).status, 'EXPIRED');
  assert.equal(await claimFulfillment(order.id), null);
  assert.equal(await markPaid(order.id, uid, payment(order)), null);
});

test('paid-to-fulfilling claim wins once and completed orders cannot regress', async () => {
  const order = await paidOrder();
  const claims = await Promise.all(Array.from({ length: 15 }, () => claimFulfillment(order.id)));
  assert.equal(claims.filter(Boolean).length, 1);
  assert.ok(claims.find(Boolean).attemptAt);
  assert.equal((await finishOrder(order.id, 'FULFILLING', { status: 'COMPLETED', externalId: 'external-1' })).status, 'COMPLETED');
  assert.equal(await finishOrder(order.id, 'FULFILLING', { status: 'REVIEW' }), null);
  assert.equal(await claimFulfillment(order.id), null);
  await assert.rejects(finishOrder(order.id, 'REVIEW', { status: 'PAID' }), /Invalid fulfillment transition/);
});

test('concurrent delivery triggers exactly one POST and uses the documented Fragment body', async () => {
  const order = await paidOrder();
  const requests = [];
  setFetch(async (url, options) => { requests.push({ url, options }); await Promise.resolve(); return response(providerOrder(order)); });
  await Promise.all(Array.from({ length: 10 }, () => fulfill(order, CONFIG)));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, `${CONFIG.fragment.baseUrl}/order/stars/`);
  assert.deepEqual(JSON.parse(requests[0].options.body), { username: 'example_user', quantity: 100, show_sender: false, currency: 'ton' });
  assert.equal(requests[0].options.headers.Authorization, 'JWT test-only-placeholder');
  assert.equal((await getOrder(order.id, uid)).status, 'COMPLETED');
  assert.equal((await stats()).stars, 100);
});

test('Premium delivery uses months and provider currency rather than Stars quantity', async () => {
  const order = await paidOrder('premium', { product: 'PREMIUM', quantity: 6 });
  let request;
  setFetch(async (url, options) => { request = { url, options }; return response(providerOrder(order)); });
  assert.equal((await fulfill(order, CONFIG)).status, 'COMPLETED');
  assert.equal(request.url, `${CONFIG.fragment.baseUrl}/order/premium/`);
  assert.deepEqual(JSON.parse(request.options.body), { username: 'example_user', months: 6, show_sender: false, currency: 'ton' });
  assert.equal((await stats()).stars, 0);
});

test('documented provider rejection is failed and retains payment evidence', async () => {
  const order = await paidOrder();
  setFetch(async () => response({ errors: [{ code: '20', error: 'Recipient was not found' }] }, 400));
  const failed = await fulfill(order, CONFIG);
  assert.equal(failed.status, 'FAILED');
  assert.equal(failed.txHash, order.txHash);
  assert.equal(await claimFulfillment(order.id), null);
  assert.equal(await cancelOrder(order.id, uid), null);
});

test('ambiguous POST timeout becomes REVIEW and is never automatically retried', async () => {
  const order = await paidOrder();
  let requests = 0;
  setFetch(async () => { requests++; throw new Error('response lost after provider accepted request'); });
  const reviewed = await fulfill(order, CONFIG);
  assert.equal(reviewed.status, 'REVIEW');
  assert.equal(reviewed.externalId, null);
  await fulfill(order, CONFIG);
  await fulfill(reviewed, CONFIG);
  await reconcile(reviewed, CONFIG);
  assert.equal(requests, 1);
});

test('malformed HTTP 200 and HTTP 500 success-looking bodies cannot mark completion', async () => {
  for (const scenario of ['invalid-json', 'http500']) {
    const order = await paidOrder(scenario);
    setFetch(async () => scenario === 'invalid-json'
      ? { ok: true, status: 200, json: async () => { throw new Error('invalid JSON'); } }
      : response(providerOrder(order, { id: `external-${order.id}` }), 500));
    const reviewed = await fulfill(order, CONFIG);
    assert.equal(reviewed.status, 'REVIEW');
  }
});

test('provider mismatched recipient/product/quantity is routed to review', async () => {
  const order = await paidOrder();
  setFetch(async () => response(providerOrder(order, { receiver: 'another_user' })));
  const reviewed = await fulfill(order, CONFIG);
  assert.equal(reviewed.status, 'REVIEW');
  assert.ok(reviewed.externalId);
});

test('pending external id is durable and completion is reconciled only with GET', async () => {
  const order = await paidOrder();
  const calls = [];
  setFetch(async (url, options = {}) => {
    calls.push({ url, method: options.method || 'GET' });
    return response(providerOrder(order, calls.length === 1 ? { status: 'PENDING', success: null } : {}));
  });
  const pending = await fulfill(order, CONFIG);
  assert.equal(pending.status, 'FULFILLING');
  assert.ok(pending.externalId);
  const completed = await reconcile(pending, CONFIG);
  assert.equal(completed.status, 'COMPLETED');
  assert.deepEqual(calls.map((c) => c.method), ['POST', 'GET']);
  assert.equal(calls[1].url, `${CONFIG.fragment.baseUrl}/order/${encodeURIComponent(pending.externalId)}/`);
});

test('provider GET with wrong order id preserves durable id and marks review', async () => {
  const order = await paidOrder();
  const claimed = await claimFulfillment(order.id);
  const pending = await finishOrder(claimed.id, 'FULFILLING', { status: 'FULFILLING', externalId: 'expected-id' });
  setFetch(async () => response(providerOrder(order, { id: 'different-id' })));
  const reviewed = await reconcile(pending, CONFIG);
  assert.equal(reviewed.status, 'REVIEW');
  assert.equal(reviewed.externalId, 'expected-id');
});

test('stale no-id delivery moves to review after cutoff and never issues another POST', async () => {
  const order = await paidOrder();
  const claimed = await claimFulfillment(order.id);
  let calls = 0;
  setFetch(async () => { calls++; throw new Error('should not contact provider'); });
  assert.equal((await reconcile(claimed, CONFIG)).status, 'FULFILLING');
  await db.run('UPDATE orders SET attempt_at=:past WHERE id=:id', { ':past': Math.floor(Date.now() / 1000) - 301, ':id': order.id });
  const stale = await getOrderInternal(order.id);
  assert.equal((await reconcile(stale, CONFIG)).status, 'REVIEW');
  assert.equal(calls, 0);
});

test('missing Fragment configuration leaves paid order available for configuration repair', async () => {
  const order = await paidOrder();
  await assert.rejects(fulfill(order, { fragment: { baseUrl: 'https://api.fragment-api.com/v1', jwt: '' } }), /not configured/);
  assert.equal((await getOrder(order.id, uid)).status, 'PAID');
});

test('referral attribution requires real user, cannot self-refer or change after orders', async () => {
  assert.equal(await setReferrer(uid, uid), false);
  assert.equal(await setReferrer(uid, 9999), false);
  assert.equal(await setReferrer(uid, otherUid), true);
  assert.equal(await setReferrer(uid, otherUid), false);
  await paidOrder();
  assert.deepEqual(await referralStats(otherUid), { invited: 1, completed: 0 });
  const third = 3003;
  await ensureUser({ id: third, first_name: 'Third' });
  await createOrder(values('third', { userId: third }));
  assert.equal(await setReferrer(third, otherUid), false);
});
