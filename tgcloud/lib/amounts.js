// Pure helpers: V8 primitives only, no Node or browser globals and no SDK.
export const OFFICIAL_USDT_MASTER = 'EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs';

function decimals(currency) {
  if (currency === 'TON') return 9;
  if (currency === 'USDT') return 6;
  throw new Error('Unsupported payment currency');
}

export function atomicInteger(value) {
  if (typeof value === 'bigint' && value >= 0n) return value;
  if (typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value)) return BigInt(value);
  throw new Error('Atomic amounts must be unsigned canonical integer strings or BigInt');
}

export function decimalToAtomic(value, currency) {
  const places = decimals(currency);
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(value)) {
    throw new Error('Use a decimal string, without signs, exponents or separators');
  }
  const [whole, fraction = ''] = value.split('.');
  if (fraction.length > places) throw new Error('Amount has excessive decimal precision');
  return (BigInt(whole) * (10n ** BigInt(places)) + BigInt(fraction.padEnd(places, '0'))).toString();
}

export function formatAtomic(value, currency) {
  const places = decimals(currency);
  const amount = atomicInteger(value);
  const scale = 10n ** BigInt(places);
  const fraction = (amount % scale).toString().padStart(places, '0').replace(/0+$/, '');
  return `${amount / scale}${fraction ? `.${fraction}` : ''}`;
}

// TEP-2, CRC16-XMODEM (polynomial 0x1021, initial value 0).
function crc16(bytes) {
  let crc = 0;
  for (const byte of bytes) {
    crc ^= byte << 8;
    for (let bit = 0; bit < 8; bit++) crc = ((crc << 1) ^ ((crc & 0x8000) ? 0x1021 : 0)) & 0xffff;
  }
  return crc;
}

export function decodeBase64(value) {
  if (typeof value !== 'string' || !value || !/^[A-Za-z0-9+/_-]*={0,2}$/.test(value)) {
    throw new Error('Malformed base64');
  }
  if ((/[+\/]/.test(value) && /[-_]/.test(value)) || value.length % 4 === 1) throw new Error('Malformed base64');
  const firstPadding = value.indexOf('=');
  const unpadded = firstPadding < 0 ? value : value.slice(0, firstPadding);
  const padding = value.length - unpadded.length;
  if (padding && (value.length % 4 !== 0 || padding !== (4 - unpadded.length % 4) % 4)) {
    throw new Error('Malformed base64 padding');
  }
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const bytes = [];
  let accumulator = 0;
  let bits = 0;
  for (const char of unpadded.replace(/-/g, '+').replace(/_/g, '/')) {
    accumulator = (accumulator << 6) | alphabet.indexOf(char);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((accumulator >> bits) & 0xff);
      accumulator &= (1 << bits) - 1;
    }
  }
  if (bits && accumulator !== 0) throw new Error('Noncanonical base64');
  return bytes;
}

export function normalizeAddress(address) {
  if (typeof address !== 'string') throw new Error('TON address must be a string');
  const value = address.trim();
  const raw = /^(0|-?[1-9][0-9]*):([0-9a-fA-F]{64})$/.exec(value);
  if (raw) {
    const workchain = Number(raw[1]);
    if (!Number.isInteger(workchain) || workchain < -128 || workchain > 127) throw new Error('Invalid workchain');
    return `${workchain}:${raw[2].toLowerCase()}`;
  }
  if (value.length !== 48) throw new Error('Invalid TON address length');
  const bytes = decodeBase64(value);
  if (bytes.length !== 36) throw new Error('Invalid TON address length');
  // This bot accepts mainnet only. Never erase the testnet-only flag.
  if (bytes[0] !== 0x11 && bytes[0] !== 0x51) throw new Error('Invalid or testnet TON address flags');
  const crc = crc16(bytes.slice(0, 34));
  if (bytes[34] !== (crc >> 8) || bytes[35] !== (crc & 0xff)) throw new Error('TON address checksum mismatch');
  const workchain = bytes[1] >= 128 ? bytes[1] - 256 : bytes[1];
  return `${workchain}:${bytes.slice(2, 34).map(byte => byte.toString(16).padStart(2, '0')).join('')}`;
}

export function sameAddress(left, right) {
  try { return normalizeAddress(left) === normalizeAddress(right); } catch { return false; }
}

export function unixSeconds(value) {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) return value;
  if (typeof value === 'string' && /^[1-9][0-9]*$/.test(value)) {
    const number = Number(value);
    if (Number.isSafeInteger(number)) return number;
  }
  throw new Error('A known positive Unix timestamp in seconds is required');
}

// Strict UTF-8 decoding: reject truncation, overlong encodings and surrogate code points.
export function decodeUtf8(bytes) {
  if (!Array.isArray(bytes) || bytes.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)) {
    throw new Error('Malformed UTF-8 byte array');
  }
  let result = '';
  for (let index = 0; index < bytes.length;) {
    const start = bytes[index++];
    let value;
    let more;
    let minimum;
    if (start <= 0x7f) { value = start; more = 0; minimum = 0; }
    else if (start >= 0xc2 && start <= 0xdf) { value = start & 0x1f; more = 1; minimum = 0x80; }
    else if (start >= 0xe0 && start <= 0xef) { value = start & 0x0f; more = 2; minimum = 0x800; }
    else if (start >= 0xf0 && start <= 0xf4) { value = start & 0x07; more = 3; minimum = 0x10000; }
    else throw new Error('Malformed UTF-8');
    while (more-- > 0) {
      const next = bytes[index++];
      if (next === undefined || (next & 0xc0) !== 0x80) throw new Error('Malformed UTF-8');
      value = (value << 6) | (next & 0x3f);
    }
    if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) throw new Error('Malformed UTF-8');
    result += String.fromCodePoint(value);
  }
  return result;
}

export function matchesPayment(order, payment) {
  try {
    decimals(order.currency);
    const created = unixSeconds(order.createdAt);
    const expires = unixSeconds(order.expiresAt);
    const timestamp = unixSeconds(payment.timestamp);
    return expires >= created
      && order.currency === payment.currency
      && atomicInteger(order.amountAtomic) > 0n
      && atomicInteger(order.amountAtomic) === atomicInteger(payment.amountAtomic)
      && sameAddress(order.walletAddress, payment.destination)
      && typeof order.memo === 'string' && order.memo.length > 0 && order.memo === payment.memo
      && timestamp >= created && timestamp <= expires
      && typeof payment.txHash === 'string' && payment.txHash.length > 0
      && payment.confirmed === true && payment.success === true && payment.aborted === false
      && (order.currency !== 'USDT' || sameAddress(payment.jettonMaster, OFFICIAL_USDT_MASTER));
  } catch { return false; }
}
