import { fetch } from 'sdk';
import {
  atomicInteger, decodeBase64, decodeUtf8, matchesPayment, normalizeAddress,
  OFFICIAL_USDT_MASTER, sameAddress, unixSeconds,
} from './amounts.js';

// Source: https://toncenter.com/api/v3/doc.json, checked 2026-10-11.
// Only indexed mainnet data is accepted; pending/emulated transactions cannot pay orders.
const MAINNET_API = 'https://toncenter.com/api/v3';
const INTERNAL_TRANSFER = 0x178d4519;

export class PaymentScanError extends Error {
  constructor(code, message) { super(message); this.name = 'PaymentScanError'; this.code = code; }
}

function hashHex(value) {
  if (typeof value !== 'string') throw new PaymentScanError('INVALID_RESPONSE', 'Missing transaction hash');
  if (/^[0-9a-fA-F]{64}$/.test(value)) return value.toLowerCase();
  try {
    const bytes = decodeBase64(value);
    if (bytes.length !== 32) throw new Error('Wrong hash length');
    return bytes.map(byte => byte.toString(16).padStart(2, '0')).join('');
  } catch { throw new PaymentScanError('INVALID_RESPONSE', 'Invalid transaction hash'); }
}

function logicalTime(value) {
  try { const lt = atomicInteger(value); if (lt > 0n) return lt; } catch {}
  throw new PaymentScanError('INVALID_RESPONSE', 'Missing or invalid logical time');
}

function timestamp(value) {
  try { return unixSeconds(value); } catch {
    throw new PaymentScanError('INVALID_RESPONSE', 'Transaction timestamp is unknown');
  }
}

function opcode(value) {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 0xffffffff) return value;
  if (typeof value === 'string' && /^0x[0-9a-fA-F]{1,8}$/.test(value)) return Number.parseInt(value.slice(2), 16);
  return null;
}

function textComment(decoded, depth = 0) {
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded) || depth > 4) return null;
  const type = decoded['@type'] ?? decoded.type;
  if (type === 'first_from_either' || type === 'second_from_either') return textComment(decoded.value, depth + 1);
  if (type !== 'text_comment') return null;
  const value = decoded.text ?? decoded.comment;
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    try { return decodeUtf8(value); } catch { return null; }
  }
  return null;
}

function transactionSucceeded(tx) {
  const description = tx?.description;
  const finality = tx?.finality;
  const confirmed = finality === 1 || finality === 2 || finality === 'confirmed' || finality === 'finalized';
  const action = description?.action;
  return confirmed && tx.emulated === false
    && Number.isSafeInteger(tx.mc_block_seqno) && tx.mc_block_seqno > 0
    && description?.aborted === false && description.compute_ph?.success === true
    && description.compute_ph.skipped === false
    && (description.compute_ph.exit_code === 0 || description.compute_ph.exit_code === 1)
    && (action == null || (action.success === true && action.valid === true
      && action.no_funds === false && action.result_code === 0))
    && description.bounce == null;
}

function tonPayment(tx) {
  const message = tx.in_msg;
  if (!transactionSucceeded(tx) || message?.bounced !== false || opcode(message.opcode) !== 0) return null;
  if (!sameAddress(tx.account, message.destination)) return null;
  try { normalizeAddress(message.source); atomicInteger(message.value); } catch { return null; }
  const memo = textComment(message.message_content?.decoded);
  if (memo === null) return null;
  return {
    currency: 'TON', txHash: hashHex(tx.hash), amountAtomic: message.value,
    destination: normalizeAddress(message.destination), memo, timestamp: timestamp(tx.now),
    txLt: logicalTime(tx.lt).toString(), sender: normalizeAddress(message.source),
    confirmed: true, success: true, aborted: false,
  };
}

function transferCandidate(row) {
  if (row.transaction_aborted !== false || !sameAddress(row.jetton_master, OFFICIAL_USDT_MASTER)) return null;
  try { atomicInteger(row.amount); normalizeAddress(row.destination); normalizeAddress(row.source_wallet); } catch { return null; }
  const memo = textComment(row.decoded_forward_payload);
  if (memo === null) return null;
  return {
    currency: 'USDT', txHash: hashHex(row.transaction_hash), amountAtomic: row.amount,
    destination: normalizeAddress(row.destination), memo, timestamp: timestamp(row.transaction_now),
    txLt: logicalTime(row.transaction_lt).toString(), sender: row.source,
    jettonMaster: normalizeAddress(OFFICIAL_USDT_MASTER),
    confirmed: true, success: true, aborted: false,
  };
}

function decodedAmount(value) {
  try { return atomicInteger(typeof value === 'object' && value !== null ? value.value : value); } catch { return null; }
}

// The transfer table records sender debit, which alone cannot prove recipient credit.
// Verify the receiving USDT wallet transaction and its link to that sender transaction.
function verifyUsdtCredit(row, trace, wallet, order) {
  if (trace?.is_incomplete !== false || trace.trace_info?.trace_state !== 'complete'
    || trace.trace_info.pending_messages !== 0 || trace.warning) {
    throw new PaymentScanError('TRACE_INCOMPLETE', 'The USDT transfer trace is not complete yet');
  }
  if (!trace.transactions || typeof trace.transactions !== 'object' || Array.isArray(trace.transactions)) {
    throw new PaymentScanError('INVALID_RESPONSE', 'Missing USDT trace transactions');
  }
  const sourceHash = hashHex(row.transaction_hash);
  const transactions = Object.values(trace.transactions);
  if (transactions.length > 500) throw new PaymentScanError('TRACE_LIMIT', 'USDT trace exceeds verification limit');
  const source = transactions.find(tx => hashHex(tx.hash) === sourceHash);
  if (!source || !transactionSucceeded(source) || !sameAddress(source.account, row.source_wallet)) return null;
  const outgoing = source.out_msgs;
  if (!Array.isArray(outgoing)) throw new PaymentScanError('INVALID_RESPONSE', 'Missing source messages');
  const credits = [];
  for (const tx of transactions) {
    if (!sameAddress(tx.account, wallet.address)) continue;
    if (!transactionSucceeded(tx) || tx.in_msg?.bounced !== false || opcode(tx.in_msg.opcode) !== INTERNAL_TRANSFER) continue;
    const message = tx.in_msg;
    if (!sameAddress(message.source, source.account) || !sameAddress(message.destination, wallet.address)) continue;
    if (!outgoing.some(out => hashHex(out.hash) === hashHex(message.hash))) continue;
    const decoded = message.message_content?.decoded;
    if (decoded?.['@type'] !== 'jetton_internal_transfer'
      || decodedAmount(decoded.amount) !== atomicInteger(order.amountAtomic)
      || String(decoded.query_id) !== String(row.query_id)
      || textComment(decoded.forward_payload) !== order.memo) continue;
    const payment = {
      currency: 'USDT', txHash: hashHex(tx.hash), sourceTxHash: sourceHash,
      amountAtomic: decodedAmount(decoded.amount).toString(),
      destination: normalizeAddress(wallet.owner), memo: order.memo, timestamp: timestamp(tx.now),
      txLt: logicalTime(tx.lt).toString(), sender: row.source,
      jettonMaster: normalizeAddress(wallet.jetton), confirmed: true, success: true, aborted: false,
    };
    if (matchesPayment(order, payment)) credits.push(payment);
  }
  if (credits.length > 1) throw new PaymentScanError('AMBIGUOUS_PAYMENT', 'Multiple credits match one transfer');
  return credits[0] ?? null;
}

function settings(order, config) {
  if (order.currency !== 'TON' && order.currency !== 'USDT') throw new PaymentScanError('INVALID_ORDER', 'Unsupported currency');
  try {
    if (atomicInteger(order.amountAtomic) <= 0n || !order.memo || typeof order.memo !== 'string') throw new Error('Invalid amount or memo');
    const created = unixSeconds(order.createdAt);
    const expires = unixSeconds(order.expiresAt);
    if (expires < created) throw new Error('Invalid payment time window');
    if (!sameAddress(order.walletAddress, config.receiverAddress)) throw new Error('Receiver does not match order');
    normalizeAddress(config.receiverAddress);
  } catch { throw new PaymentScanError('INVALID_ORDER', 'Invalid order or receiver configuration'); }
  const base = (config.toncenterV3Url ?? MAINNET_API).replace(/\/$/, '');
  if (base !== MAINNET_API) throw new PaymentScanError('INVALID_CONFIG', 'Only the official Toncenter mainnet URL is accepted');
  if (config.usdtMaster && !sameAddress(config.usdtMaster, OFFICIAL_USDT_MASTER)) {
    throw new PaymentScanError('INVALID_CONFIG', 'Only the official TON USDT master is accepted');
  }
  const limit = config.scanLimit ?? 50;
  const pages = config.scanMaxPages ?? 4;
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000 || !Number.isInteger(pages) || pages < 1 || pages > 20) {
    throw new PaymentScanError('INVALID_CONFIG', 'Invalid bounded payment scan limits');
  }
  return { base, limit, pages, receiver: normalizeAddress(config.receiverAddress) };
}

async function request(base, path, params, config) {
  const query = Object.entries(params).map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&');
  let response;
  try {
    response = await fetch(`${base}${path}?${query}`, {
      method: 'GET', headers: config.toncenterApiKey ? { 'X-API-Key': config.toncenterApiKey } : {},
    });
  } catch { throw new PaymentScanError('PROVIDER_UNAVAILABLE', 'Toncenter is temporarily unavailable'); }
  if (!response.ok) throw new PaymentScanError('PROVIDER_UNAVAILABLE', `Toncenter returned HTTP ${response.status}`);
  let data;
  try { data = await response.json(); } catch { throw new PaymentScanError('INVALID_RESPONSE', 'Toncenter returned invalid JSON'); }
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.error) throw new PaymentScanError('INVALID_RESPONSE', 'Toncenter returned an invalid response');
  return data;
}

async function scanWindow(order, config, options) {
  const isTon = order.currency === 'TON';
  const path = isTon ? '/transactions' : '/jetton/transfers';
  const field = isTon ? 'transactions' : 'jetton_transfers';
  const end = Math.min(unixSeconds(order.expiresAt), Math.floor(Date.now() / 1000));
  if (end < unixSeconds(order.createdAt)) return [];
  const params = {
    ...(isTon ? { account: options.receiver } : {
      owner_address: options.receiver, jetton_master: normalizeAddress(OFFICIAL_USDT_MASTER), direction: 'in',
    }),
    // One-second query expansion covers API versions with exclusive time filters.
    // Local matching below still enforces the exact inclusive order window.
    start_utime: Math.max(0, unixSeconds(order.createdAt) - 1), end_utime: end + 1,
    sort: 'desc', limit: options.limit, offset: 0,
  };
  const all = [];
  const seen = new Set();
  let previousLt = null;
  for (let page = 0; page < options.pages; page++) {
    const data = await request(options.base, path, params, config);
    const rows = data[field];
    if (!Array.isArray(rows) || rows.length > options.limit) throw new PaymentScanError('INVALID_RESPONSE', 'Missing or oversized transaction page');
    for (const row of rows) {
      if (!row || typeof row !== 'object') throw new PaymentScanError('INVALID_RESPONSE', 'Invalid transaction row');
      const hash = hashHex(isTon ? row.hash : row.transaction_hash);
      const lt = logicalTime(isTon ? row.lt : row.transaction_lt);
      timestamp(isTon ? row.now : row.transaction_now);
      if (seen.has(hash) || (previousLt !== null && (lt > previousLt || (isTon && lt === previousLt)))) {
        throw new PaymentScanError('UNSTABLE_PAGINATION', 'Transaction pagination changed or is not ordered');
      }
      seen.add(hash);
      previousLt = lt;
      all.push(row);
    }
    if (rows.length < options.limit) return all;
    if (isTon) {
      // Account transaction logical times are unique: use a strict keyset cursor.
      params.end_lt = (previousLt - 1n).toString();
    } else {
      // Transfers across accounts may share an LT. Preserve ties with offset;
      // anchor to the first page's newest LT and reject overlap or sort changes.
      if (page === 0) params.end_lt = logicalTime(rows[0].transaction_lt).toString();
      params.offset += rows.length;
    }
  }
  // Even an earlier matching row is never accepted from an incomplete scan.
  throw new PaymentScanError('SCAN_INCOMPLETE', 'Payment window exceeds the configured scan limit; retry with a larger limit');
}

export async function findPayment(order, config) {
  const options = settings(order, config);
  const rows = await scanWindow(order, config, options);
  const payments = [];
  if (order.currency === 'TON') {
    for (const tx of rows) {
      const payment = tonPayment(tx);
      if (payment && matchesPayment(order, payment)) payments.push(payment);
    }
  } else {
    const candidates = rows.filter(row => {
      const payment = transferCandidate(row);
      return payment && matchesPayment(order, payment);
    });
    if (candidates.length) {
      const walletsData = await request(options.base, '/jetton/wallets', {
        owner_address: options.receiver, jetton_address: normalizeAddress(OFFICIAL_USDT_MASTER), limit: 2, offset: 0,
      }, config);
      const wallets = walletsData.jetton_wallets;
      if (!Array.isArray(wallets) || wallets.length !== 1
        || !sameAddress(wallets[0].owner, options.receiver)
        || !sameAddress(wallets[0].jetton, OFFICIAL_USDT_MASTER)) {
        throw new PaymentScanError('WALLET_UNVERIFIED', 'The receiving USDT wallet cannot be verified');
      }
      try { normalizeAddress(wallets[0].address); } catch { throw new PaymentScanError('WALLET_UNVERIFIED', 'Invalid receiving USDT wallet'); }
      for (const row of candidates) {
        const tracesData = await request(options.base, '/traces', { tx_hash: row.transaction_hash, limit: 2, offset: 0 }, config);
        if (!Array.isArray(tracesData.traces) || tracesData.traces.length !== 1) {
          throw new PaymentScanError('TRACE_INCOMPLETE', 'The USDT trace cannot be verified yet');
        }
        const payment = verifyUsdtCredit(row, tracesData.traces[0], wallets[0], order);
        if (payment) payments.push(payment);
      }
    }
  }
  const unique = new Map(payments.map(payment => [payment.txHash, payment]));
  if (unique.size > 1) throw new PaymentScanError('AMBIGUOUS_PAYMENT', 'Multiple transactions match this order; manual review required');
  return unique.values().next().value ?? null;
}

export { matchesPayment } from './amounts.js';
