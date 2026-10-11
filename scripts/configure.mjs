import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const OFFICIAL_USDT_MASTER = 'EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs';
const OFFICIAL_USDT_RAW = '0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe';

export const DEFAULT_OPERATOR_CONFIG = {
  shopName: 'Stars & Premium', botUsername: '', supportUrl: '', miniAppUrl: '',
  receiverAddress: '', toncenterApiKey: '', toncenterV3Url: 'https://toncenter.com/api/v3',
  scanLimit: 50, scanMaxPages: 4, usdtMaster: OFFICIAL_USDT_MASTER,
  priceSource: 'fragment',
  stars: {
    TON: { basePerUnit: '', markupBps: 0, providerFee: '0' },
    USDT: { basePerUnit: '', markupBps: 0, providerFee: '0' },
  },
  premium: { TON: { 3: '', 6: '', 12: '' }, USDT: { 3: '', 6: '', 12: '' } },
  fragment: { baseUrl: 'https://api.fragment-api.com/v1', jwt: '' },
  adminIds: [], salesEnabled: false, pricingVerified: false, paymentTtlSeconds: 900,
};

function object(value, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${field}: ожидается объект.`);
  return value;
}

function unknownKeys(value, allowed, field) {
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) throw new Error(`${field}: неизвестное поле.`);
  }
}

function text(value, field, max = 2048) {
  if (typeof value !== 'string' || value.length > max || /[\u0000-\u001f\u007f]/u.test(value)) {
    throw new Error(`${field}: ожидается строка без управляющих символов.`);
  }
  return value.trim();
}

function httpsUrl(value, field, optional = false) {
  const result = text(value, field);
  if (!result && optional) return '';
  let url;
  try { url = new URL(result); } catch { throw new Error(`${field}: ожидается HTTPS URL.`); }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash) {
    throw new Error(`${field}: ожидается HTTPS URL без встроенных паролей и фрагмента.`);
  }
  return result.replace(/\/+$/u, '');
}

function integer(value, field, min, max) {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`${field}: недопустимое целое число.`);
  return value;
}

function flag(value, field) {
  if (typeof value !== 'boolean') throw new Error(`${field}: ожидается true или false.`);
  return value;
}

function decimal(value, field, scale, { optional = false, positive = false } = {}) {
  const result = text(value, field, 64);
  if (optional && result === '') return '';
  if (!new RegExp(`^(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,${scale}})?$`, 'u').test(result)) {
    throw new Error(`${field}: ожидается десятичная строка без знака, максимум ${scale} знаков после точки.`);
  }
  if (positive && !/[1-9]/u.test(result)) throw new Error(`${field}: значение должно быть положительным.`);
  const [whole, fraction = ''] = result.split('.');
  if (BigInt(whole + fraction.padEnd(scale, '0')) > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error(`${field}: сумма слишком велика.`);
  }
  return result;
}

function markupRatio(value, field) {
  object(value, field); unknownKeys(value, ['numerator', 'denominator'], field);
  for (const part of ['numerator', 'denominator']) {
    if (typeof value[part] !== 'string' || value[part].length > 30 || !/^(0|[1-9][0-9]*)$/u.test(value[part])) {
      throw new Error(`${field}.${part}: ожидается каноническая строка целого числа без знака.`);
    }
  }
  const numerator = BigInt(value.numerator), denominator = BigInt(value.denominator);
  if (denominator <= 0n || numerator > denominator) throw new Error(`${field}: знаменатель должен быть положительным, надбавка — от 0 до 100%.`);
  return { numerator: value.numerator, denominator: value.denominator };
}

function crc16(bytes) {
  let crc = 0;
  for (const byte of bytes) {
    crc ^= byte << 8;
    for (let bit = 0; bit < 8; bit += 1) crc = ((crc << 1) ^ ((crc & 0x8000) ? 0x1021 : 0)) & 0xffff;
  }
  return crc;
}

export function parseMainnetAddress(value, field = 'receiverAddress') {
  const result = text(value, field, 128);
  if (/^(?:0|-1):[a-fA-F0-9]{64}$/u.test(result)) return result.toLowerCase();
  if (!/^[A-Za-z0-9_\-/+]{48}$/u.test(result)) throw new Error(`${field}: неверный TON адрес.`);
  const bytes = Buffer.from(result.replace(/-/gu, '+').replace(/_/gu, '/'), 'base64');
  if (bytes.length !== 36 || ![0x11, 0x51].includes(bytes[0]) || ![0, 255].includes(bytes[1]) ||
      crc16(bytes.subarray(0, 34)) !== bytes.readUInt16BE(34)) {
    throw new Error(`${field}: нужен корректный адрес основной сети TON с контрольной суммой.`);
  }
  return `${bytes[1] === 255 ? -1 : 0}:${bytes.subarray(2, 34).toString('hex')}`;
}

export function validateOperatorConfig(input) {
  object(input, 'config');
  unknownKeys(input, Object.keys(DEFAULT_OPERATOR_CONFIG), 'config');
  const config = structuredClone({ ...DEFAULT_OPERATOR_CONFIG, ...input });
  config.shopName = text(config.shopName, 'shopName', 100);
  if (!config.shopName) throw new Error('shopName: название обязательно.');
  config.botUsername = text(config.botUsername, 'botUsername', 32).replace(/^@/u, '');
  if (config.botUsername && !/^[A-Za-z][A-Za-z0-9_]{4,31}$/u.test(config.botUsername)) throw new Error('botUsername: неверный Telegram username.');
  config.supportUrl = httpsUrl(config.supportUrl, 'supportUrl', true);
  config.miniAppUrl = httpsUrl(config.miniAppUrl, 'miniAppUrl', true);
  config.receiverAddress = text(config.receiverAddress, 'receiverAddress', 128);
  if (config.receiverAddress) parseMainnetAddress(config.receiverAddress);
  config.toncenterApiKey = text(config.toncenterApiKey, 'toncenterApiKey');
  config.toncenterV3Url = httpsUrl(config.toncenterV3Url, 'toncenterV3Url');
  if (config.toncenterV3Url !== 'https://toncenter.com/api/v3') throw new Error('toncenterV3Url: разрешен только официальный API v3 основной сети TON.');
  config.scanLimit = integer(config.scanLimit, 'scanLimit', 1, 1000);
  config.scanMaxPages = integer(config.scanMaxPages, 'scanMaxPages', 1, 20);
  config.usdtMaster = text(config.usdtMaster, 'usdtMaster', 128);
  if (parseMainnetAddress(config.usdtMaster, 'usdtMaster') !== OFFICIAL_USDT_RAW) throw new Error('usdtMaster: разрешен только официальный USDT в основной сети TON.');
  if (!['fragment', 'manual'].includes(config.priceSource)) throw new Error('priceSource: ожидается fragment или manual.');
  object(config.stars, 'stars'); unknownKeys(config.stars, ['TON', 'USDT'], 'stars');
  object(config.premium, 'premium'); unknownKeys(config.premium, ['TON', 'USDT'], 'premium');
  for (const currency of ['TON', 'USDT']) {
    const scale = currency === 'TON' ? 9 : 6;
    const rate = { ...DEFAULT_OPERATOR_CONFIG.stars[currency], ...object(config.stars[currency] ?? {}, `stars.${currency}`) };
    unknownKeys(rate, ['basePerUnit', 'markupBps', 'providerFee', 'markupRatio'], `stars.${currency}`);
    rate.basePerUnit = decimal(rate.basePerUnit, `stars.${currency}.basePerUnit`, scale, { optional: true, positive: true });
    rate.markupBps = integer(rate.markupBps, `stars.${currency}.markupBps`, 0, 10000);
    if (rate.markupRatio !== undefined) {
      rate.markupRatio = markupRatio(rate.markupRatio, `stars.${currency}.markupRatio`);
      if (rate.markupBps !== 0) throw new Error(`stars.${currency}: markupRatio нельзя сочетать с ненулевым markupBps.`);
    }
    rate.providerFee = decimal(rate.providerFee, `stars.${currency}.providerFee`, scale);
    config.stars[currency] = rate;
    const prices = { ...DEFAULT_OPERATOR_CONFIG.premium[currency], ...object(config.premium[currency] ?? {}, `premium.${currency}`) };
    unknownKeys(prices, ['3', '6', '12'], `premium.${currency}`);
    for (const months of [3, 6, 12]) prices[months] = decimal(prices[months], `premium.${currency}.${months}`, scale, { optional: true, positive: true });
    config.premium[currency] = prices;
  }
  config.fragment = { ...DEFAULT_OPERATOR_CONFIG.fragment, ...object(config.fragment, 'fragment') };
  unknownKeys(config.fragment, ['baseUrl', 'jwt'], 'fragment');
  config.fragment.baseUrl = httpsUrl(config.fragment.baseUrl, 'fragment.baseUrl');
  config.fragment.jwt = text(config.fragment.jwt, 'fragment.jwt', 8192);
  if (!Array.isArray(config.adminIds)) throw new Error('adminIds: ожидается массив Telegram ID.');
  config.adminIds = [...new Set(config.adminIds.map(id => integer(id, 'adminIds', 1, Number.MAX_SAFE_INTEGER)))];
  config.salesEnabled = flag(config.salesEnabled, 'salesEnabled');
  config.pricingVerified = flag(config.pricingVerified, 'pricingVerified');
  config.paymentTtlSeconds = integer(config.paymentTtlSeconds, 'paymentTtlSeconds', 60, 86400);
  if (config.salesEnabled) {
    if (!config.pricingVerified) throw new Error('salesEnabled: сначала подтвердите цены и комиссии через pricingVerified.');
    for (const [field, value] of [['receiverAddress', config.receiverAddress], ['toncenterApiKey', config.toncenterApiKey], ['fragment.jwt', config.fragment.jwt], ['stars.TON.basePerUnit', config.stars.TON.basePerUnit]]) {
      if (!value) throw new Error(`salesEnabled: обязательное поле ${field} не заполнено.`);
    }
  }
  return config;
}

export async function configureProject(projectRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))) {
  const sourcePath = path.join(projectRoot, 'config', 'operator.json');
  const outputPath = path.join(projectRoot, 'tgcloud', 'lib', 'operator-config.js');
  let input;
  try { input = JSON.parse(await readFile(sourcePath, 'utf8')); }
  catch (error) {
    if (error.code === 'ENOENT') throw new Error('Нет config/operator.json: скопируйте config/operator.example.json и заполните локальные настройки.');
    throw new Error('config/operator.json: не удалось прочитать корректный JSON.');
  }
  const config = validateOperatorConfig(input);
  const serialized = JSON.stringify(config, null, 2).replace(/\u2028/gu, '\\u2028').replace(/\u2029/gu, '\\u2029');
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `// GENERATED_OPERATOR_CONFIG: local operator settings; never commit this file.\nexport const operatorConfig = ${serialized};\n`, { mode: 0o600 });
  return { outputPath, salesEnabled: config.salesEnabled };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await configureProject();
    console.log(`Создан tgcloud/lib/operator-config.js. Продажи ${result.salesEnabled ? 'включены' : 'выключены'}. Значения ключей не выводятся.`);
  } catch (error) {
    console.error(`Настройка остановлена: ${error.message}`);
    process.exitCode = 1;
  }
}
