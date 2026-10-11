import { db } from 'sdk';
import { matchesPayment } from './amounts.js';

const now = () => Math.floor(Date.now() / 1000);
const SESSION_SECONDS = 24 * 60 * 60;
const PAGE_SIZE = 5;
const projection = `id, user_id AS userId, recipient, product, quantity, currency,
  amount_atomic AS amountAtomic, base_atomic AS baseAtomic, markup_atomic AS markupAtomic,
  provider_fee_atomic AS providerFeeAtomic, markup_bps AS markupBps, wallet_address AS walletAddress,
  memo, creation_key AS creationKey, status, tx_hash AS txHash, tx_lt AS txLt, sender,
  external_id AS externalId, attempt_at AS attemptAt, paid_at AS paidAt, completed_at AS completedAt,
  created_at AS createdAt, expires_at AS expiresAt, updated_at AS updatedAt,
  chat_id AS chatId, message_id AS messageId, error, provider_response AS providerResponse`;

function decode(row) {
  if (!row) return null;
  if (typeof row.providerResponse === 'string') {
    try { row.providerResponse = JSON.parse(row.providerResponse); } catch { row.providerResponse = null; }
  }
  return row;
}
function userId(value) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error('Invalid Telegram user id');
  return value;
}
function orderId(value) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error('Invalid order id');
  return value;
}
function atomic(value, positive = false) {
  if (typeof value !== 'string' || !/^(0|[1-9]\d*)$/.test(value) || (positive && BigInt(value) <= 0n)) {
    throw new Error('Amounts must be canonical atomic-unit strings');
  }
  return value;
}
function changed(result) { return result.rowsAffected > 0; }
function uniquenessError(error) { return /unique constraint|constraint_unique/i.test(String(error?.message || error)); }

export async function ensureUser(user) {
  const uid = userId(user.id);
  const timestamp = now();
  await db.run(`INSERT INTO users (id,username,first_name,language_code,created_at,updated_at)
    VALUES (:uid,:username,:name,:lang,:now,:now)
    ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name,
      language_code=excluded.language_code, updated_at=excluded.updated_at`, {
    ':uid': uid, ':username': user.username || null, ':name': user.first_name || '',
    ':lang': user.language_code || 'ru', ':now': timestamp,
  });
  return db.get(`SELECT id,username,first_name AS firstName,language_code AS languageCode,
    referrer_id AS referrerId,created_at AS createdAt,updated_at AS updatedAt FROM users WHERE id=:uid`, { ':uid': uid });
}

export async function setReferrer(uid, refUid) {
  userId(uid); userId(refUid);
  if (uid === refUid) return false;
  const result = await db.run(`UPDATE users SET referrer_id=:refUid WHERE id=:uid
    AND referrer_id IS NULL AND EXISTS (SELECT 1 FROM users WHERE id=:refUid)
    AND NOT EXISTS (SELECT 1 FROM orders WHERE user_id=:uid)`, { ':uid': uid, ':refUid': refUid });
  return changed(result);
}

export async function getSession(uid) {
  const row = await db.get(`SELECT state,data,updated_at AS updatedAt FROM sessions
    WHERE user_id=:uid AND updated_at>=:cutoff`, { ':uid': userId(uid), ':cutoff': now() - SESSION_SECONDS });
  if (!row) return null;
  try { return { state: row.state, data: JSON.parse(row.data) }; } catch { return null; }
}

export async function saveSession(uid, state, data = {}) {
  userId(uid);
  if (typeof state !== 'string' || !state || state.length > 64 || !data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid session');
  }
  const encoded = JSON.stringify(data);
  if (encoded.length > 32768) throw new Error('Session is too large');
  const result = await db.run(`INSERT INTO sessions (user_id,state,data,updated_at)
    SELECT :uid,:state,:data,:now WHERE EXISTS (SELECT 1 FROM users WHERE id=:uid)
    ON CONFLICT(user_id) DO UPDATE SET state=excluded.state,data=excluded.data,updated_at=excluded.updated_at`, {
    ':uid': uid, ':state': state, ':data': encoded, ':now': now(),
  });
  if (!changed(result)) throw new Error('User must exist before creating a session');
  return { state, data };
}

export async function clearSession(uid) {
  await db.run('DELETE FROM sessions WHERE user_id=:uid', { ':uid': userId(uid) });
}

export async function listOrders(uid, page = 0) {
  userId(uid);
  if (!Number.isSafeInteger(page) || page < 0) throw new Error('Invalid page');
  const rows = await db.all(`SELECT ${projection} FROM orders WHERE user_id=:uid
    ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset`, {
    ':uid': uid, ':limit': PAGE_SIZE + 1, ':offset': page * PAGE_SIZE,
  });
  return { items: rows.slice(0, PAGE_SIZE).map(decode), hasNext: rows.length > PAGE_SIZE };
}

export async function getOrder(id, uid) {
  return decode(await db.get(`SELECT ${projection} FROM orders WHERE id=:id AND user_id=:uid`, {
    ':id': orderId(id), ':uid': userId(uid),
  }));
}

// Internal code only. Public handlers/endpoints must always call getOrder(id, caller.id).
export async function getOrderInternal(id) {
  return decode(await db.get(`SELECT ${projection} FROM orders WHERE id=:id`, { ':id': orderId(id) }));
}

export async function createOrder(values) {
  const uid = userId(values.userId);
  const quantity = values.quantity;
  if (!Number.isSafeInteger(quantity) || !(
    (values.product === 'STARS' && quantity >= 50 && quantity <= 1000000) ||
    (values.product === 'PREMIUM' && [3, 6, 12].includes(quantity))
  )) throw new Error('Invalid product quantity');
  const recipient = String(values.recipient || '').replace(/^@/, '');
  if (!/^[a-zA-Z][a-zA-Z0-9_]{2,31}$/.test(recipient)) throw new Error('Invalid recipient');
  if (!['TON', 'USDT'].includes(values.currency)) throw new Error('Unsupported currency');
  const amount = atomic(values.amountAtomic, true);
  const base = atomic(values.baseAtomic, true);
  const markup = atomic(values.markupAtomic);
  const fee = atomic(values.providerFeeAtomic);
  if (BigInt(amount) !== BigInt(base) + BigInt(markup) + BigInt(fee)) throw new Error('Quote totals disagree');
  if (!Number.isSafeInteger(values.markupBps) || values.markupBps < 0) throw new Error('Invalid markup');
  if (typeof values.walletAddress !== 'string' || !values.walletAddress) throw new Error('Missing payment destination');
  if (typeof values.creationKey !== 'string' || !values.creationKey || values.creationKey.length > 256) throw new Error('Missing creation key');
  const created = now();
  const expires = values.expiresAt ?? created + 900;
  if (!Number.isSafeInteger(expires) || expires <= created || expires > created + 86400) throw new Error('Invalid quote expiry');
  await db.run(`INSERT INTO orders
    (user_id,recipient,product,quantity,currency,amount_atomic,base_atomic,markup_atomic,provider_fee_atomic,
     markup_bps,wallet_address,creation_key,status,created_at,expires_at,updated_at,chat_id,message_id)
    SELECT :uid,:recipient,:product,:quantity,:currency,:amount,:base,:markup,:fee,:bps,:wallet,:key,
      'WAITING_PAYMENT',:created,:expires,:created,:chat,:message
    WHERE EXISTS (SELECT 1 FROM users WHERE id=:uid)
    ON CONFLICT(creation_key) DO NOTHING`, {
    ':uid': uid, ':recipient': recipient, ':product': values.product, ':quantity': quantity,
    ':currency': values.currency, ':amount': amount, ':base': base, ':markup': markup, ':fee': fee,
    ':bps': values.markupBps, ':wallet': values.walletAddress, ':key': values.creationKey,
    ':created': created, ':expires': expires, ':chat': values.chatId ?? null, ':message': values.messageId ?? null,
  });
  // Atomic assignment from AUTO increment id. A crash before this point leaves a non-payable row;
  // replay of the same creation key repairs it without allocating a second invoice.
  await db.run(`UPDATE orders SET memo='SM-' || id WHERE creation_key=:key AND user_id=:uid
    AND memo IS NULL AND status='WAITING_PAYMENT'`, { ':key': values.creationKey, ':uid': uid });
  const order = decode(await db.get(`SELECT ${projection} FROM orders WHERE creation_key=:key AND user_id=:uid`, {
    ':key': values.creationKey, ':uid': uid,
  }));
  if (!order?.memo) throw new Error('Invoice allocation failed; retry creation with the same key');
  return order;
}

export async function markPaid(id, uid, payment) {
  const order = await getOrder(id, uid);
  if (!order || order.status !== 'WAITING_PAYMENT' || !order.memo || !matchesPayment(order, payment)) return null;
  if (typeof payment.txHash !== 'string' || !payment.txHash || payment.txHash.length > 256) return null;
  try {
    const result = await db.run(`UPDATE orders SET status='PAID',tx_hash=:hash,tx_lt=:lt,sender=:sender,
      paid_at=:timestamp,updated_at=:now WHERE id=:id AND user_id=:uid AND status='WAITING_PAYMENT'
      AND memo=:memo AND amount_atomic=:amount AND wallet_address=:wallet AND currency=:currency
      AND created_at<=:timestamp AND expires_at>=:timestamp`, {
      ':hash': payment.txHash, ':lt': payment.txLt == null ? null : String(payment.txLt),
      ':sender': payment.sender || null, ':timestamp': payment.timestamp, ':now': now(),
      ':id': id, ':uid': uid, ':memo': order.memo, ':amount': order.amountAtomic,
      ':wallet': order.walletAddress, ':currency': order.currency,
    });
    return changed(result) ? getOrder(id, uid) : null;
  } catch (error) {
    // Unique tx_hash makes one on-chain transaction unusable for two invoices.
    if (uniquenessError(error)) return null;
    throw error;
  }
}

export async function cancelOrder(id, uid) {
  const result = await db.run(`UPDATE orders SET status='CANCELLED',updated_at=:now
    WHERE id=:id AND user_id=:uid AND status='WAITING_PAYMENT'`, {
    ':id': orderId(id), ':uid': userId(uid), ':now': now(),
  });
  return changed(result) ? getOrder(id, uid) : null;
}

export async function expireOrder(id, uid) {
  const result = await db.run(`UPDATE orders SET status='EXPIRED',updated_at=:now
    WHERE id=:id AND user_id=:uid AND status='WAITING_PAYMENT' AND expires_at<:now`, {
    ':id': orderId(id), ':uid': userId(uid), ':now': now(),
  });
  return changed(result) ? getOrder(id, uid) : null;
}

export async function claimFulfillment(id) {
  const result = await db.run(`UPDATE orders SET status='FULFILLING',attempt_at=:now,updated_at=:now,error=NULL
    WHERE id=:id AND status='PAID' AND tx_hash IS NOT NULL AND memo IS NOT NULL AND attempt_at IS NULL`, {
    ':id': orderId(id), ':now': now(),
  });
  return changed(result) ? getOrderInternal(id) : null;
}

export async function finishOrder(id, expectedStatus, patch) {
  const transitions = {
    FULFILLING: ['FULFILLING', 'COMPLETED', 'FAILED', 'REVIEW'],
    REVIEW: ['COMPLETED', 'FAILED', 'REVIEW'],
  };
  if (!transitions[expectedStatus]?.includes(patch.status)) throw new Error('Invalid fulfillment transition');
  const params = { ':id': orderId(id), ':expected': expectedStatus, ':status': patch.status, ':now': now() };
  const fields = ['status=:status', 'updated_at=:now'];
  if (patch.externalId !== undefined) {
    if (typeof patch.externalId !== 'string' || !patch.externalId || patch.externalId.length > 256) throw new Error('Invalid provider order id');
    fields.push('external_id=COALESCE(external_id,:external)');
    params[':external'] = patch.externalId;
  }
  if (patch.error !== undefined) { fields.push('error=:error'); params[':error'] = patch.error == null ? null : String(patch.error).slice(0, 1000); }
  if (patch.providerResponse !== undefined) {
    const encoded = JSON.stringify(patch.providerResponse);
    fields.push('provider_response=:response'); params[':response'] = encoded.length <= 32768 ? encoded : JSON.stringify({ omitted: 'response exceeded audit size limit' });
  }
  if (patch.status === 'COMPLETED') fields.push('completed_at=:now');
  const result = await db.run(`UPDATE orders SET ${fields.join(',')}
    WHERE id=:id AND status=:expected${patch.externalId !== undefined ? ' AND (external_id IS NULL OR external_id=:external)' : ''}`, params);
  return changed(result) ? getOrderInternal(id) : null;
}

export async function listPending(limit = 20) {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new Error('Invalid limit');
  return (await db.all(`SELECT ${projection} FROM orders WHERE status IN ('PAID','FULFILLING','REVIEW')
    ORDER BY created_at,id LIMIT :limit`, { ':limit': limit })).map(decode);
}

export async function stats() {
  return db.get(`SELECT (SELECT COUNT(*) FROM users) AS users, COUNT(*) AS orders,
    COUNT(CASE WHEN status='COMPLETED' THEN 1 END) AS completed,
    COALESCE(SUM(CASE WHEN status='COMPLETED' AND product='STARS' THEN quantity ELSE 0 END),0) AS stars FROM orders`);
}

export async function referralStats(uid) {
  return db.get(`SELECT (SELECT COUNT(*) FROM users WHERE referrer_id=:uid) AS invited,
    COUNT(*) AS completed FROM orders WHERE status='COMPLETED'
    AND user_id IN (SELECT id FROM users WHERE referrer_id=:uid)`, { ':uid': userId(uid) });
}
