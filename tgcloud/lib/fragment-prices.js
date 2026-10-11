import { fetch } from 'sdk';
import { decimalToAtomic, atomicInteger } from './amounts.js';

// This reads the official public quantity-price UI. It never invokes a purchase method.
// The UI endpoint is undocumented and changes must fail closed, without a static fallback.
const ORIGIN = 'https://fragment.com';
const PAGE_URL = `${ORIGIN}/stars/buy`;
const PROBE_QUANTITY = 10_000_000n;

export class FragmentPriceError extends Error {
  constructor(code, message) { super(message); this.name = 'FragmentPriceError'; this.code = code; }
}

async function http(url, options) {
  let response;
  try { response = await fetch(url, options); } catch {
    throw new FragmentPriceError('FRAGMENT_UNAVAILABLE', 'Official Fragment prices are temporarily unavailable');
  }
  if (response?.ok !== true || response.status !== 200) {
    throw new FragmentPriceError('FRAGMENT_UNAVAILABLE', 'Official Fragment returned an unexpected HTTP status');
  }
  // SDK fetch follows redirects. Do not accept an authentication or external page.
  if (typeof response.url !== 'string' || response.url !== url) {
    throw new FragmentPriceError('FRAGMENT_REDIRECT', 'Official Fragment price request was redirected');
  }
  return response;
}

function anonymousCookie(headers) {
  const value = headers?.get?.('set-cookie');
  if (typeof value !== 'string') throw new FragmentPriceError('FRAGMENT_COOKIE', 'Missing anonymous Fragment session cookie');
  // Use only the newly issued anonymous session; exclude any authentication cookies.
  const cookies = [...value.matchAll(/(?:^|,\s*)stel_ssid=([A-Za-z0-9_-]{16,200})(?=;|$)/g)];
  if (cookies.length !== 1) throw new FragmentPriceError('FRAGMENT_COOKIE', 'Invalid anonymous Fragment session cookie');
  return `stel_ssid=${cookies[0][1]}`;
}

function publicPriceUrl(html) {
  if (typeof html !== 'string' || html.length > 262_144) {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Invalid Fragment price page');
  }
  const initializers = [...html.matchAll(/\bajInit\(\s*(\{[\s\S]*?\})\s*\);/g)];
  if (initializers.length !== 1) throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Missing public Fragment price configuration');
  let config;
  try { config = JSON.parse(initializers[0][1]); } catch {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Malformed public Fragment price configuration');
  }
  if (config?.unauth !== true || typeof config.apiUrl !== 'string'
    || !/^\/api\?hash=[a-f0-9]{16,64}$/.test(config.apiUrl)) {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Unexpected public Fragment price endpoint');
  }
  return `${ORIGIN}${config.apiUrl}`;
}

function plainDecimal(html) {
  // Only the known fractional span is allowed. Extra tags or escaped values are rejected.
  const value = html.trim().replace(/<span\s+class=(['"])mini-frac\1\s*>(\.[0-9]+)<\/span>/g, '$2');
  if (value.length > 64 || !/^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?$/.test(value)) {
    throw new FragmentPriceError('FRAGMENT_PRICE', 'Malformed official Fragment price');
  }
  return value.replace(/,/g, '');
}

function priceBlocks(html) {
  if (typeof html !== 'string' || html.length > 8192) {
    throw new FragmentPriceError('FRAGMENT_PRICE', 'Missing official Fragment price HTML');
  }
  const blocks = [...html.matchAll(/<div\b[^>]*\bclass\s*=\s*(['"])([^'"]*)\1[^>]*>([\s\S]*?)<\/div>/g)];
  const usd = [];
  const ton = [];
  for (const block of blocks) {
    const classes = block[2].split(/\s+/);
    if (classes.includes('icon-usd')) usd.push(plainDecimal(block[3]));
    if (classes.includes('icon-ton')) ton.push(plainDecimal(block[3]));
  }
  if (usd.length !== 1 || ton.length !== 1) {
    throw new FragmentPriceError('FRAGMENT_PRICE', 'Official Fragment quote is missing or ambiguous');
  }
  return { USD: usd[0], TON: ton[0] };
}

function unitPrice(totalDecimal, currency) {
  let total;
  try { total = atomicInteger(decimalToAtomic(totalDecimal, currency)); } catch {
    throw new FragmentPriceError('FRAGMENT_PRECISION', 'Official Fragment quote has unsupported precision');
  }
  if (total <= 0n || total % PROBE_QUANTITY !== 0n) {
    throw new FragmentPriceError('FRAGMENT_PRECISION', 'Official Fragment quote cannot yield an exact positive unit price');
  }
  const amount = total / PROBE_QUANTITY;
  const places = currency === 'TON' ? 9 : 6;
  const scale = 10n ** BigInt(places);
  return `${amount / scale}.${(amount % scale).toString().padStart(places, '0')}`;
}

export async function getFragmentPrices() {
  const page = await http(PAGE_URL, { method: 'GET', headers: { Accept: 'text/html' } });
  const cookie = anonymousCookie(page.headers);
  let html;
  try { html = await page.text(); } catch {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Could not read the official Fragment price page');
  }
  const url = publicPriceUrl(html);
  const response = await http(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json', Cookie: cookie },
    body: 'method=updateStarsPrices&stars=0&quantity=10000000',
  });
  let quote;
  try { quote = await response.json(); } catch {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Official Fragment returned invalid price JSON');
  }
  if (!quote || typeof quote !== 'object' || Array.isArray(quote) || quote.ok !== true || quote.error) {
    throw new FragmentPriceError('FRAGMENT_SCHEMA', 'Official Fragment rejected the public price request');
  }
  const prices = priceBlocks(quote.cur_price);
  return {
    TON: unitPrice(prices.TON, 'TON'),
    // Fragment publishes a USD face value here, not a USDT-TON checkout quote.
    // This is the explicitly configured nominal USD proxy; route/network fees are separate.
    USDT: unitPrice(prices.USD, 'USDT'),
    checkedAt: Math.floor(Date.now() / 1000), source: 'fragment',
  };
}
