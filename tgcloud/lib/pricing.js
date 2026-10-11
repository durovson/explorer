import { decimalToAtomic } from './amounts.js';

export function quote(product, quantity, currency, config) {
  if (!['TON', 'USDT'].includes(currency)) throw new Error('Неизвестная валюта');
  if (!Number.isSafeInteger(quantity)) throw new Error('Введите целое количество');
  let base, markupBps = 0, providerFee, ratio;
  if (product === 'STARS') {
    if (quantity < 50 || quantity > 1000000) throw new Error('Количество Stars: от 50 до 1 000 000');
    const rate = config.stars[currency];
    if (!rate?.basePerUnit) throw new Error('Цена пока не настроена');
    markupBps = rate.markupBps ?? 0;
    if (!Number.isSafeInteger(markupBps) || markupBps < 0 || markupBps > 10000) throw new Error('Некорректная комиссия');
    if (rate.markupRatio) {
      const { numerator, denominator } = rate.markupRatio;
      if (!/^(0|[1-9]\d{0,29})$/.test(numerator) || !/^[1-9]\d{0,29}$/.test(denominator)) throw new Error('Некорректная комиссия');
      ratio = { n: BigInt(numerator), d: BigInt(denominator) };
      if (ratio.n > ratio.d || markupBps !== 0) throw new Error('Некорректная комиссия');
    }
    base = BigInt(decimalToAtomic(rate.basePerUnit, currency)) * BigInt(quantity);
    providerFee = BigInt(decimalToAtomic(rate.providerFee || '0', currency));
  } else if (product === 'PREMIUM') {
    if (![3, 6, 12].includes(quantity)) throw new Error('Premium: 3, 6 или 12 месяцев');
    const rate = config.premium[currency][quantity];
    if (!rate) throw new Error('Цена пока не настроена');
    base = BigInt(decimalToAtomic(rate, currency));
    providerFee = 0n;
  } else throw new Error('Неизвестный товар');
  const markup = ratio ? (base * ratio.n + ratio.d - 1n) / ratio.d : (base * BigInt(markupBps) + 9999n) / 10000n;
  const total = base + markup + providerFee;
  if (total <= 0n) throw new Error('Некорректная сумма');
  return {
    product, quantity, currency, baseAtomic: String(base), markupAtomic: String(markup),
    providerFeeAtomic: String(providerFee), markupBps, amountAtomic: String(total)
  };
}

// A display percentage only; all charged amounts above use exact integers.
export function markupPercent(baseAtomic, markupAtomic) {
  const base = BigInt(baseAtomic), markup = BigInt(markupAtomic);
  if (base <= 0n || markup < 0n) throw new Error('Некорректная комиссия');
  const hundredths = (markup * 10000n + base / 2n) / base;
  return `${hundredths / 100n}.${String(hundredths % 100n).padStart(2,'0')}`.replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

export function normalizeRecipient(value) {
  const recipient = String(value || '').trim().replace(/^@/, '');
  if (!/^[A-Za-z][A-Za-z0-9_]{3,31}$/.test(recipient)) throw new Error('Введите корректный @username получателя');
  return '@' + recipient;
}
