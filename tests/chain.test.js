import test from 'node:test';
import assert from 'node:assert/strict';
import {
  decimalToAtomic, decodeBase64, decodeUtf8, formatAtomic, matchesPayment,
  normalizeAddress, OFFICIAL_USDT_MASTER, sameAddress,
} from '../tgcloud/lib/amounts.js';
import { findPayment } from '../tgcloud/lib/chain.js';
import { setFetch } from './sdk-mock.js';

const receiver = `0:${'1'.repeat(64)}`;
const sender = `0:${'2'.repeat(64)}`;
const sourceWallet = `0:${'3'.repeat(64)}`;
const receiverJettonWallet = `0:${'4'.repeat(64)}`;
const createdAt = 1_790_000_000;
const order = {
  currency: 'TON', amountAtomic: '2500000000', walletAddress: receiver,
  memo: 'ORDER-1234', createdAt, expiresAt: createdAt + 900,
};
const proof = {
  currency: 'TON', amountAtomic: '2500000000', destination: receiver,
  memo: order.memo, timestamp: createdAt + 60, txHash: 'a'.repeat(64),
  confirmed: true, success: true, aborted: false,
};
const usdtOrder = { ...order, currency: 'USDT', amountAtomic: '2500000' };
const config = { receiverAddress: receiver, scanLimit: 2, scanMaxPages: 4 };

function tx(overrides = {}) {
  return {
    account: receiver, hash: 'a'.repeat(64), lt: '100', now: createdAt + 60,
    finality: 'finalized', emulated: false, mc_block_seqno: 1,
    description: {
      aborted: false, compute_ph: { success: true, skipped: false, exit_code: 0 },
      action: { success: true, valid: true, no_funds: false, result_code: 0 },
    },
    in_msg: {
      source: sender, destination: receiver, value: order.amountAtomic,
      bounced: false, opcode: '0x00000000',
      message_content: { decoded: { '@type': 'text_comment', text: order.memo } },
    }, out_msgs: [], ...overrides,
  };
}

function transfer(overrides = {}) {
  return {
    amount: usdtOrder.amountAtomic, destination: receiver, source: sender,
    source_wallet: sourceWallet, jetton_master: OFFICIAL_USDT_MASTER,
    query_id: '7', transaction_hash: 'a'.repeat(64), transaction_lt: '200',
    transaction_now: createdAt + 60, transaction_aborted: false,
    decoded_forward_payload: { '@type': 'text_comment', comment: order.memo },
    ...overrides,
  };
}

function usdtTrace() {
  const message = {
    hash: 'c'.repeat(64), source: sourceWallet, destination: receiverJettonWallet,
    opcode: '0x178d4519', bounced: false,
    message_content: {
      decoded: {
        '@type': 'jetton_internal_transfer', query_id: '7',
        amount: { '@type': 'var_uint', value: usdtOrder.amountAtomic },
        forward_payload: { '@type': 'second_from_either', value: { '@type': 'text_comment', text: order.memo } },
      },
    },
  };
  return {
    is_incomplete: false, warning: null,
    trace_info: { trace_state: 'complete', pending_messages: 0 },
    transactions: {
      debit: tx({ account: sourceWallet, hash: 'a'.repeat(64), lt: '200', out_msgs: [message] }),
      credit: tx({ account: receiverJettonWallet, hash: 'b'.repeat(64), lt: '201',
        now: createdAt + 61, in_msg: message }),
    },
  };
}

function installProvider({ rows = [], trace = usdtTrace(), wallets, status = 200, body } = {}) {
  const calls = [];
  setFetch(async (url, options) => {
    calls.push({ url: new URL(url), options });
    let data = body;
    if (!data) {
      if (url.includes('/jetton/wallets?')) data = { jetton_wallets: wallets ?? [{ address: receiverJettonWallet, owner: receiver, jetton: OFFICIAL_USDT_MASTER }] };
      else if (url.includes('/traces?')) data = { traces: [trace] };
      else if (url.includes('/jetton/transfers?')) data = { jetton_transfers: rows };
      else data = { transactions: rows };
    }
    return { ok: status >= 200 && status < 300, status, json: async () => data };
  });
  return calls;
}

test('decimal and atomic conversions preserve values beyond Number precision', () => {
  assert.equal(decimalToAtomic('9007199254740993.000000001', 'TON'), '9007199254740993000000001');
  assert.equal(formatAtomic('9007199254740993000000001', 'TON'), '9007199254740993.000000001');
  assert.equal(decimalToAtomic('2.5', 'USDT'), '2500000');
  assert.equal(formatAtomic(2500000n, 'USDT'), '2.5');
  assert.equal(formatAtomic('0', 'TON'), '0');
  for (const value of [2.5, '-1', '+1', '1e3', '1,2', '01', ' 1 ', '0.0000000001']) {
    assert.throws(() => decimalToAtomic(value, 'TON'));
  }
  assert.throws(() => decimalToAtomic('1.0000001', 'USDT'));
  assert.throws(() => formatAtomic(2500000, 'USDT'));
});

test('TON friendly forms require CRC16, known mainnet flags and full account ID', () => {
  const raw = '0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e';
  const bounceable = 'EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF';
  const nonbounceable = 'UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA';
  assert.equal(normalizeAddress(bounceable), raw);
  assert.equal(normalizeAddress(nonbounceable), raw);
  assert.equal(normalizeAddress(bounceable.replace(/-/g, '+')), raw);
  assert.ok(sameAddress(raw.toUpperCase(), bounceable));
  assert.equal(normalizeAddress(OFFICIAL_USDT_MASTER), '0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe');
  for (const invalid of [bounceable.slice(0, -1) + 'A', '0:abc', `128:${'a'.repeat(64)}`,
    `-129:${'a'.repeat(64)}`, `00:${'a'.repeat(64)}`, `+0:${'a'.repeat(64)}`,
    'kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP']) {
    assert.throws(() => normalizeAddress(invalid));
    assert.equal(sameAddress(invalid, invalid), false);
  }
});

test('base64 and UTF-8 decoders reject malformed or ambiguous text', () => {
  assert.deepEqual(decodeBase64('AQID'), [1, 2, 3]);
  assert.deepEqual(decodeBase64('AA=='), [0]);
  for (const invalid of ['A', 'AB==', 'AA=', 'AA===', 'AA\n==', '!!!!']) assert.throws(() => decodeBase64(invalid));
  assert.equal(decodeUtf8([0xd0, 0x9f, 0xd1, 0x80, 0xd0, 0xb8, 0xd0, 0xb2, 0xd0, 0xb5, 0xd1, 0x82]), 'Привет');
  for (const invalid of [[0xc0, 0x80], [0xe0, 0x80, 0x80], [0xed, 0xa0, 0x80], [0xf4, 0x90, 0x80, 0x80], [0xc2], [256]]) {
    assert.throws(() => decodeUtf8(invalid));
  }
});

test('payment matching requires exact amount, recipient, currency and memo', () => {
  assert.equal(matchesPayment(order, proof), true);
  for (const change of [
    { amountAtomic: '2499999999' }, { amountAtomic: '2500000001' }, { amountAtomic: 2500000000 },
    { destination: sender }, { destination: 'bad' }, { currency: 'USDT' },
    { memo: `${order.memo} ` }, { memo: '' }, { txHash: '' },
  ]) assert.equal(matchesPayment(order, { ...proof, ...change }), false);
  assert.equal(matchesPayment({ ...order, amountAtomic: '9007199254740993' }, { ...proof, amountAtomic: '9007199254740992' }), false);
});

test('unknown timestamps and payments outside the inclusive invoice window cannot match', () => {
  for (const value of [null, undefined, 0, NaN, '', createdAt - 1, order.expiresAt + 1]) {
    assert.equal(matchesPayment(order, { ...proof, timestamp: value }), false);
  }
  assert.equal(matchesPayment(order, { ...proof, timestamp: createdAt }), true);
  assert.equal(matchesPayment(order, { ...proof, timestamp: order.expiresAt }), true);
});

test('unconfirmed, failed, aborted or partially specified evidence is rejected', () => {
  for (const change of [{ confirmed: false }, { confirmed: undefined }, { confirmed: 'true' },
    { success: false }, { success: undefined }, { aborted: true }, { aborted: undefined }]) {
    assert.equal(matchesPayment(order, { ...proof, ...change }), false);
  }
  const usdt = { ...proof, currency: 'USDT', amountAtomic: usdtOrder.amountAtomic, jettonMaster: OFFICIAL_USDT_MASTER };
  assert.equal(matchesPayment(usdtOrder, usdt), true);
  assert.equal(matchesPayment(usdtOrder, { ...usdt, jettonMaster: sender }), false);
  assert.equal(matchesPayment(usdtOrder, { ...usdt, jettonMaster: undefined }), false);
});

test('TON scan uses indexed V3, exact memo and API key header', async () => {
  const calls = installProvider({ rows: [tx()] });
  const payment = await findPayment(order, { ...config, toncenterApiKey: 'test-secret' });
  assert.equal(payment.txHash, 'a'.repeat(64));
  assert.equal(payment.amountAtomic, order.amountAtomic);
  assert.equal(calls[0].url.pathname, '/api/v3/transactions');
  assert.equal(calls[0].url.searchParams.get('account'), receiver);
  assert.equal(calls[0].url.searchParams.get('start_utime'), String(createdAt - 1));
  assert.equal(calls[0].options.headers['X-API-Key'], 'test-secret');
  assert.equal(calls[0].url.searchParams.has('api_key'), false);
});

test('TON rejects pending/emulated/aborted/bounced and failed action transactions', async () => {
  const cases = [
    tx({ finality: 'pending' }), tx({ finality: undefined }), tx({ emulated: true }),
    tx({ description: { aborted: true, compute_ph: { success: true, skipped: false, exit_code: 0 } } }),
    tx({ description: { aborted: false, compute_ph: { success: false, skipped: false, exit_code: 0 } } }),
    tx({ description: { aborted: false, compute_ph: { success: true, skipped: false, exit_code: 0 },
      action: { success: false, valid: true, no_funds: false, result_code: 0 } } }),
    tx({ in_msg: { ...tx().in_msg, bounced: true } }),
    tx({ in_msg: { ...tx().in_msg, source: null } }),
  ];
  for (const row of cases) {
    installProvider({ rows: [row] });
    assert.equal(await findPayment(order, config), null);
  }
});

test('matching transaction from an incomplete bounded window is never credited', async () => {
  installProvider({ rows: [tx()] });
  await assert.rejects(findPayment(order, { ...config, scanLimit: 1, scanMaxPages: 1 }), { code: 'SCAN_INCOMPLETE' });
});

test('TON keyset scan reaches the end before returning and excludes cursor overlap', async () => {
  const calls = [];
  setFetch(async url => {
    const request = new URL(url); calls.push(request);
    const rows = calls.length === 1 ? [tx(), tx({ hash: 'b'.repeat(64), lt: '90', in_msg: { ...tx().in_msg, value: '1' } })] : [];
    return { ok: true, status: 200, json: async () => ({ transactions: rows }) };
  });
  assert.ok(await findPayment(order, config));
  assert.equal(calls.length, 2);
  assert.equal(calls[1].searchParams.get('end_lt'), '89');
  assert.equal(calls[1].searchParams.get('offset'), '0');
  installProvider({ rows: [tx(), tx({ lt: '90' })] });
  await assert.rejects(findPayment(order, config), { code: 'UNSTABLE_PAGINATION' });
});

test('provider errors and unknown timestamps fail closed without exposing the key', async () => {
  installProvider({ rows: [tx({ now: null })] });
  await assert.rejects(findPayment(order, config), { code: 'INVALID_RESPONSE' });
  installProvider({ body: {} });
  await assert.rejects(findPayment(order, config), { code: 'INVALID_RESPONSE' });
  installProvider({ status: 429 });
  await assert.rejects(findPayment(order, { ...config, toncenterApiKey: 'never-log-this' }), error => {
    assert.equal(error.code, 'PROVIDER_UNAVAILABLE');
    assert.equal(error.message.includes('never-log-this'), false);
    return true;
  });
});

test('testnet endpoints, unexpected receiver or a substituted USDT master are rejected before HTTP', async () => {
  const calls = installProvider();
  await assert.rejects(findPayment(order, { ...config, toncenterV3Url: 'https://testnet.toncenter.com/api/v3' }), { code: 'INVALID_CONFIG' });
  await assert.rejects(findPayment(order, { ...config, receiverAddress: sender }), { code: 'INVALID_ORDER' });
  await assert.rejects(findPayment(usdtOrder, { ...config, usdtMaster: sender }), { code: 'INVALID_CONFIG' });
  assert.equal(calls.length, 0);
});

test('USDT accepts only the successful linked recipient credit, with its own hash and time', async () => {
  const calls = installProvider({ rows: [transfer()] });
  const payment = await findPayment(usdtOrder, config);
  assert.equal(payment.txHash, 'b'.repeat(64));
  assert.equal(payment.sourceTxHash, 'a'.repeat(64));
  assert.equal(payment.timestamp, createdAt + 61);
  assert.equal(payment.amountAtomic, usdtOrder.amountAtomic);
  assert.equal(calls.length, 3);
  assert.equal(calls[0].url.searchParams.get('jetton_master'), normalizeAddress(OFFICIAL_USDT_MASTER));
  assert.equal(calls[1].url.searchParams.get('jetton_address'), normalizeAddress(OFFICIAL_USDT_MASTER));
});

test('sender debit alone or an aborted receiving USDT wallet cannot pay an order', async () => {
  const trace = usdtTrace();
  delete trace.transactions.credit;
  installProvider({ rows: [transfer()], trace });
  assert.equal(await findPayment(usdtOrder, config), null);
  const aborted = usdtTrace();
  aborted.transactions.credit.description.aborted = true;
  installProvider({ rows: [transfer()], trace: aborted });
  assert.equal(await findPayment(usdtOrder, config), null);
});

test('USDT receiving amount, query ID, memo and message link must all agree', async () => {
  for (const change of ['amount', 'query', 'memo', 'link', 'timestamp', 'finality']) {
    const trace = usdtTrace();
    const credit = trace.transactions.credit;
    if (change === 'amount') credit.in_msg.message_content.decoded.amount.value = '2499999';
    if (change === 'query') credit.in_msg.message_content.decoded.query_id = '8';
    if (change === 'memo') credit.in_msg.message_content.decoded.forward_payload.value.text = `${order.memo} `;
    if (change === 'link') trace.transactions.debit.out_msgs = [{ hash: 'd'.repeat(64) }];
    if (change === 'timestamp') credit.now = order.expiresAt + 1;
    if (change === 'finality') credit.finality = 'pending';
    installProvider({ rows: [transfer()], trace });
    assert.equal(await findPayment(usdtOrder, config), null, change);
  }
});

test('USDT requires a complete trace, known credit timestamp and authenticated receiving wallet', async () => {
  const incomplete = usdtTrace(); incomplete.trace_info.pending_messages = 1;
  installProvider({ rows: [transfer()], trace: incomplete });
  await assert.rejects(findPayment(usdtOrder, config), { code: 'TRACE_INCOMPLETE' });
  const unknown = usdtTrace(); unknown.transactions.credit.now = null;
  installProvider({ rows: [transfer()], trace: unknown });
  await assert.rejects(findPayment(usdtOrder, config), { code: 'INVALID_RESPONSE' });
  installProvider({ rows: [transfer()], wallets: [{ address: receiverJettonWallet, owner: receiver, jetton: sender }] });
  await assert.rejects(findPayment(usdtOrder, config), { code: 'WALLET_UNVERIFIED' });
});

test('fake-token and unproven-aborted-status transfer records never trigger credit lookup', async () => {
  for (const row of [transfer({ jetton_master: sender }), transfer({ transaction_aborted: undefined })]) {
    const calls = installProvider({ rows: [row] });
    assert.equal(await findPayment(usdtOrder, config), null);
    assert.equal(calls.length, 1);
  }
});

test('multiple exact TON payments require manual review instead of arbitrary selection', async () => {
  installProvider({ rows: [tx(), tx({ hash: 'b'.repeat(64), lt: '90' })] });
  await assert.rejects(findPayment(order, { ...config, scanLimit: 3 }), { code: 'AMBIGUOUS_PAYMENT' });
});
