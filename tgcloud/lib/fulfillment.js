import { fetch } from 'sdk';
import { config as defaultConfig } from './config.js';
import { claimFulfillment, finishOrder, getOrderInternal } from './store.js';

const PENDING = new Set(['CREATED', 'PENDING', 'BLOCKCHAIN_SENT']);
const NO_ID_CUTOFF_SECONDS = 300;
const current = (id) => getOrderInternal(id);
function fragmentConfig(config) {
  const fragment = config.fragment;
  if (!fragment?.jwt || !fragment?.baseUrl) throw new Error('Fragment is not configured');
  if (!/^https:\/\/[a-zA-Z0-9.-]+(?::\d+)?(?:\/[a-zA-Z0-9._~!$&'()*+,;=:@%/-]*)?$/.test(fragment.baseUrl)) {
    throw new Error('Fragment requires an HTTPS base URL');
  }
  return { baseUrl: fragment.baseUrl.replace(/\/+$/, ''), headers: { Authorization: `JWT ${fragment.jwt}`, Accept: 'application/json' } };
}
async function save(id, expected, patch) {
  return await finishOrder(id, expected, patch) || current(id);
}
function providerId(data) {
  return typeof data?.id === 'string' && data.id.length > 0 && data.id.length <= 256 ? data.id : null;
}
function identityMatches(order, data) {
  return typeof data.receiver === 'string' && data.receiver.toLowerCase() === order.recipient.replace(/^@/, '').toLowerCase()
    && data.type === order.product && data.goods_quantity === order.quantity;
}
async function applyResponse(order, expected, response, data) {
  const externalId = providerId(data);
  const patch = { providerResponse: data };
  if (externalId && (!order.externalId || order.externalId === externalId)) patch.externalId = externalId;
  // A transport error or non-success HTTP code cannot be evidence of a successful purchase.
  if (!response.ok) {
    const definitiveRejection = response.status >= 400 && response.status < 500 && Array.isArray(data?.errors)
      && data.errors.length > 0 && data.errors.every((e) => e && typeof e.code === 'string' && typeof e.error === 'string');
    return save(order.id, expected, { ...patch, status: definitiveRejection ? 'FAILED' : 'REVIEW', error: `Fragment HTTP ${response.status}; outcome requires reconciliation` });
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) || !externalId
    || (order.externalId && order.externalId !== externalId)) {
    return save(order.id, expected, { ...patch, status: 'REVIEW', error: 'Fragment response has no valid matching order id' });
  }
  // Never accept an order belonging to another recipient/product as delivery evidence.
  if (!identityMatches(order, data)) {
    return save(order.id, expected, { ...patch, status: 'REVIEW', error: 'Fragment response recipient, product or quantity does not match invoice' });
  }
  if (data.status === 'COMPLETED' && data.success === true) {
    return save(order.id, expected, { ...patch, status: 'COMPLETED', error: null });
  }
  if (data.status === 'FAILED' && data.success === false) {
    return save(order.id, expected, { ...patch, status: 'FAILED', error: 'Fragment reported a failed purchase; support must resolve the paid invoice' });
  }
  if (PENDING.has(data.status) && data.success !== false) {
    return save(order.id, expected, { ...patch, status: expected, error: null });
  }
  return save(order.id, expected, { ...patch, status: 'REVIEW', error: 'Unknown or contradictory Fragment order status' });
}

export async function fulfill(order, config = defaultConfig) {
  if (!order || order.status !== 'PAID') return order;
  // Validate configuration before claiming: no side effect has happened yet on config failure.
  const fragment = fragmentConfig(config);
  const claimed = await claimFulfillment(order.id);
  if (!claimed) return current(order.id);
  const payload = {
    username: claimed.recipient.replace(/^@/, ''), show_sender: false,
    currency: claimed.currency === 'TON' ? 'ton' : 'usdt_ton',
  };
  if (claimed.product === 'STARS') payload.quantity = claimed.quantity;
  else payload.months = claimed.quantity;
  let response;
  let data;
  try {
    // The provider does not document request idempotency. There is exactly one POST after a durable CAS claim.
    response = await fetch(`${fragment.baseUrl}/order/${claimed.product === 'STARS' ? 'stars' : 'premium'}/`, {
      method: 'POST', headers: { ...fragment.headers, 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    data = await response.json();
  } catch {
    return save(claimed.id, 'FULFILLING', { status: 'REVIEW', error: 'Fragment POST outcome is unknown; automatic retry is disabled' });
  }
  return applyResponse(claimed, 'FULFILLING', response, data);
}

export async function reconcile(order, config = defaultConfig) {
  if (!order || !['FULFILLING', 'REVIEW'].includes(order.status)) return order;
  if (!order.externalId) {
    const timestamp = Math.floor(Date.now() / 1000);
    if (order.status === 'FULFILLING' && (!order.attemptAt || timestamp - order.attemptAt >= NO_ID_CUTOFF_SECONDS)) {
      return save(order.id, 'FULFILLING', { status: 'REVIEW', error: 'Fragment attempt has no external id after safe cutoff; manual reconciliation required' });
    }
    return current(order.id);
  }
  const fragment = fragmentConfig(config);
  let response;
  let data;
  try {
    response = await fetch(`${fragment.baseUrl}/order/${encodeURIComponent(order.externalId)}/`, { headers: fragment.headers });
    data = await response.json();
  } catch {
    // A failed read says nothing about fulfillment. Leave the durable id for the next GET.
    return current(order.id);
  }
  if (!response.ok) return current(order.id);
  return applyResponse(order, order.status, response, data);
}
