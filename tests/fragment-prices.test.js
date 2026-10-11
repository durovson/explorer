import test from 'node:test';
import assert from 'node:assert/strict';
import { setFetch } from './sdk-mock.js';
import { getFragmentPrices } from '../tgcloud/lib/fragment-prices.js';

// Captured public Fragment markup, 2026-10-11. No order or payment was created.
const pageHtml = '<script>ajInit({"version":627,"apiUrl":"\\/api?hash=d7c6d98ffffa64b92b","unauth":true,"state":{"mode":"new","lastDh":237726011,"needUpdate":true,"tonRate":1.4663379390926}});</script>';
const cookie = 'stel_ssid=0a120b1f192738c814_7705376613626783979; expires=Sat, 09 Oct 2027 10:18:11 GMT; path=/; samesite=None; secure; HttpOnly';
const actualPriceHtml = '        <div class="tm-value icon-before icon-usd">150,000</div>\n        <div class="tm-radio-desc wide-only icon-before icon-ton">102,293<span class="mini-frac">.88</span></div>';

function provider(overrides = {}) {
  const calls = [];
  setFetch(async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) {
      if (overrides.getThrows) throw new Error('Network failure');
      return {
        ok: true, status: 200, url, headers: { get: name => name === 'set-cookie' ? cookie : null },
        text: async () => pageHtml, ...overrides.page,
      };
    }
    if (overrides.postThrows) throw new Error('Network failure');
    return {
      ok: true, status: 200, url,
      json: async () => ({ ok: true, cur_price: actualPriceHtml }), ...overrides.price,
    };
  });
  return calls;
}

test('official public quote yields exact fixed precision prices without floating point arithmetic', async () => {
  provider();
  const before = Math.floor(Date.now() / 1000);
  const prices = await getFragmentPrices();
  assert.equal(prices.TON, '0.010229388');
  assert.equal(prices.USDT, '0.015000');
  assert.equal(prices.source, 'fragment');
  assert.ok(Number.isSafeInteger(prices.checkedAt) && prices.checkedAt >= before);
});

test('only official anonymous price endpoints and method are invoked', async () => {
  const calls = provider();
  await getFragmentPrices();
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'https://fragment.com/stars/buy');
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[0].options.headers.Cookie, undefined);
  assert.equal(calls[1].url, 'https://fragment.com/api?hash=d7c6d98ffffa64b92b');
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(calls[1].options.headers.Cookie, 'stel_ssid=0a120b1f192738c814_7705376613626783979');
  assert.equal(calls[1].options.headers['Content-Type'], 'application/x-www-form-urlencoded');
  assert.equal(calls[1].options.body, 'method=updateStarsPrices&stars=0&quantity=10000000');
  assert.equal(calls[1].options.body.includes('recipient'), false);
});

test('missing or malformed fresh session cookie fails before the price request', async () => {
  for (const value of [null, '', 'stel_token=some-login-token; path=/', 'stel_ssid=short; path=/',
    'stel_ssid=valid_long_cookie_value; path=/, stel_ssid=another_valid_cookie_value; path=/',
    'stel_ssid=invalid_long_cookie_value\r\nCookie: auth=1; path=/']) {
    const calls = provider({ page: { headers: { get: () => value } } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_COOKIE' });
    assert.equal(calls.length, 1);
  }
  provider({ page: { headers: undefined } });
  await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_COOKIE' });
});

test('fresh anonymous cookie extraction excludes authentication cookies', async () => {
  const calls = provider({ page: { headers: { get: () => `stel_token=unused; path=/, ${cookie}` } } });
  await getFragmentPrices();
  assert.equal(calls[1].options.headers.Cookie, 'stel_ssid=0a120b1f192738c814_7705376613626783979');
});

test('nonce cannot replace the host, path or price method', async () => {
  for (const endpoint of ['https://evil.example/api?hash=012345678901234567',
    '//evil.example/api?hash=012345678901234567', '/auth', '/api?hash=abcd',
    '/api?hash=012345678901234567&method=initBuyStarsRequest', '/api?hash=ABCDEFABCDEFABCDEF']) {
    const initializer = `<script>ajInit(${JSON.stringify({ apiUrl: endpoint, unauth: true })});</script>`;
    const calls = provider({ page: { text: async () => initializer } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_SCHEMA' });
    assert.equal(calls.length, 1);
  }
});

test('missing, duplicate, malformed or authenticated initializer fails closed', async () => {
  for (const html of ['', `${pageHtml}${pageHtml}`, 'ajInit({broken});', pageHtml.replace('"unauth":true', '"unauth":false')]) {
    provider({ page: { text: async () => html } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_SCHEMA' });
  }
});

test('HTTP or network errors cannot return static prices', async () => {
  for (const overrides of [{ getThrows: true }, { postThrows: true },
    { page: { ok: false, status: 403 } }, { price: { ok: false, status: 429 } },
    { price: { ok: true, status: 201 } }]) {
    provider(overrides);
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_UNAVAILABLE' });
  }
});

test('redirected or missing final response URLs are rejected', async () => {
  for (const overrides of [{ page: { url: 'https://fragment.com/auth' } },
    { price: { url: 'https://other.example/api' } }, { price: { url: undefined } }]) {
    provider(overrides);
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_REDIRECT' });
  }
});

test('malformed JSON, nonboolean ok or reported method errors are rejected', async () => {
  for (const quote of [null, [], { ok: 'true', cur_price: actualPriceHtml },
    { ok: false, error: 'Unknown method' }, { ok: true, error: 'Unsupported method', cur_price: actualPriceHtml }]) {
    provider({ price: { json: async () => quote } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_SCHEMA' });
  }
  provider({ price: { json: async () => { throw new Error('Bad JSON'); } } });
  await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_SCHEMA' });
});

test('missing or duplicate currency blocks cannot silently supply a quote', async () => {
  for (const html of ['', actualPriceHtml.replace('icon-ton', 'icon-unknown'),
    actualPriceHtml + '<div class="icon-usd">150,000</div>']) {
    provider({ price: { json: async () => ({ ok: true, cur_price: html }) } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_PRICE' });
  }
});

test('HTML formatting and number grouping are parsed strictly', async () => {
  for (const html of [actualPriceHtml.replace('150,000', '15,00,00'),
    actualPriceHtml.replace('150,000', '1e5'), actualPriceHtml.replace('150,000', '0150000'),
    actualPriceHtml.replace('.88</span>', '.88</span><script>bad()</script>')]) {
    provider({ price: { json: async () => ({ ok: true, cur_price: html }) } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_PRICE' });
  }
});

test('zero prices and a quote that loses unit precision cannot be used', async () => {
  for (const html of [actualPriceHtml.replace('150,000', '0'),
    actualPriceHtml.replace('150,000', '150,000.01'),
    actualPriceHtml.replace('.88</span>', '.880000001</span>'),
    actualPriceHtml.replace('150,000', '150000.0000001')]) {
    provider({ price: { json: async () => ({ ok: true, cur_price: html }) } });
    await assert.rejects(getFragmentPrices(), { code: 'FRAGMENT_PRECISION' });
  }
});

test('exact quantities beyond Number precision remain exact when represented in HTML', async () => {
  const html = '<div class="icon-usd">90,071,992,547,409,930</div><div class="icon-ton">90,071,992,547,409,930<span class="mini-frac">.88</span></div>';
  provider({ price: { json: async () => ({ ok: true, cur_price: html }) } });
  const prices = await getFragmentPrices();
  assert.equal(prices.TON, '9007199254.740993088');
  assert.equal(prices.USDT, '9007199254.740993');
});
