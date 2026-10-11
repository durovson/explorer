import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { DEFAULT_OPERATOR_CONFIG, OFFICIAL_USDT_MASTER, validateOperatorConfig, parseMainnetAddress, configureProject } from '../scripts/configure.mjs';

const copy = () => structuredClone(DEFAULT_OPERATOR_CONFIG);
const configuredSales = () => ({
  ...copy(), salesEnabled: true, pricingVerified: true,
  receiverAddress: OFFICIAL_USDT_MASTER, toncenterApiKey: 'private-indexer-key',
  stars: { ...copy().stars, TON: { basePerUnit: '0.01', markupBps: 200, providerFee: '0' } },
  fragment: { ...copy().fragment, jwt: 'private-provider-key' },
});

test('safe defaults keep sales disabled and do not mutate caller configuration', () => {
  const input = copy();
  const original = structuredClone(input);
  const config = validateOperatorConfig(input);
  assert.equal(config.salesEnabled, false);
  assert.equal(config.pricingVerified, false);
  assert.deepEqual(input, original);
  assert.deepEqual(DEFAULT_OPERATOR_CONFIG, copy());
});

test('sales require verified prices, address, API keys and a TON stars rate', () => {
  for (const field of ['pricingVerified', 'receiverAddress', 'toncenterApiKey', 'fragment.jwt', 'stars.TON.basePerUnit']) {
    const config = configuredSales();
    const keys = field.split('.');
    let cursor = config;
    for (const key of keys.slice(0, -1)) cursor = cursor[key];
    cursor[keys.at(-1)] = field === 'pricingVerified' ? false : '';
    assert.throws(() => validateOperatorConfig(config), /salesEnabled/u, field);
  }
  assert.equal(validateOperatorConfig(configuredSales()).salesEnabled, true);
});

test('decimal strings reject rounding, zero rates, negative values and exponent notation', () => {
  for (const rate of ['0', '-0.1', '1e-3', 'NaN', '0.0000000001', '9007199254']) {
    const config = copy(); config.stars.TON.basePerUnit = rate;
    assert.throws(() => validateOperatorConfig(config), /stars\.TON\.basePerUnit/u, rate);
  }
  const config = copy(); config.stars.USDT.providerFee = '0.0000001';
  assert.throws(() => validateOperatorConfig(config), /providerFee/u);
});

test('premium rates may be unavailable but a configured rate must be positive', () => {
  assert.equal(validateOperatorConfig(copy()).premium.TON[3], '');
  const config = copy(); config.premium.USDT[3] = '0';
  assert.throws(() => validateOperatorConfig(config), /premium\.USDT\.3/u);
});

test('mainnet addresses require a valid friendly checksum or complete raw address', () => {
  assert.equal(parseMainnetAddress(OFFICIAL_USDT_MASTER), '0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe');
  for (const address of ['', '0:abc', `${OFFICIAL_USDT_MASTER.slice(0, -1)}x`, `k${OFFICIAL_USDT_MASTER.slice(1)}`]) {
    assert.throws(() => parseMainnetAddress(address), /адрес/u);
  }
});

test('counterfeit USDT master is rejected even with a valid raw address', () => {
  const config = copy(); config.usdtMaster = `0:${'a'.repeat(64)}`;
  assert.throws(() => validateOperatorConfig(config), /официальный USDT/u);
});

test('URL settings reject HTTP and embedded credentials without echoing secrets', () => {
  for (const url of ['http://api.example.com', 'https://operator:never-print-this@example.com/v1', 'javascript:alert(1)']) {
    const config = copy(); config.fragment.baseUrl = url;
    assert.throws(() => validateOperatorConfig(config), error => {
      assert.ok(!error.message.includes('never-print-this'));
      return /fragment\.baseUrl/u.test(error.message);
    });
  }
});

test('invalid bounds, flags and unknown config keys fail closed', () => {
  for (const [field, value] of [['scanLimit', 0], ['scanMaxPages', 21], ['paymentTtlSeconds', 0], ['salesEnabled', 'false'], ['pricingVerified', 1], ['adminIds', ['42']]]) {
    assert.throws(() => validateOperatorConfig({ ...copy(), [field]: value }), new RegExp(field, 'u'));
  }
  assert.throws(() => validateOperatorConfig({ ...copy(), secrets: 'hidden' }), /неизвестное поле/u);
  const config = copy(); config.stars.TON.providerFfee = '1';
  assert.throws(() => validateOperatorConfig(config), /неизвестное поле/u);
});

test('payment scan configuration accepts only official mainnet v3 and matches chain bounds', () => {
  const config = validateOperatorConfig({ ...copy(), toncenterV3Url: 'https://toncenter.com/api/v3/', scanLimit: 1000, scanMaxPages: 20 });
  assert.equal(config.toncenterV3Url, 'https://toncenter.com/api/v3');
  assert.equal(config.scanMaxPages, 20);
  for (const url of ['https://testnet.toncenter.com/api/v3', 'https://toncenter.com/api/v2', 'https://api.example.com/v3', 'https://toncenter.com/api/v3?network=testnet']) {
    assert.throws(() => validateOperatorConfig({ ...copy(), toncenterV3Url: url }), /toncenterV3Url/u);
  }
});

test('admin IDs deduplicate and username can include a leading @', () => {
  const config = validateOperatorConfig({ ...copy(), adminIds: [42, 42, 123], botUsername: '@ExampleBot' });
  assert.deepEqual(config.adminIds, [42, 123]);
  assert.equal(config.botUsername, 'ExampleBot');
});

test('price source defaults to Fragment and accepts only explicit Fragment/manual modes', () => {
  assert.equal(validateOperatorConfig({}).priceSource, 'fragment');
  assert.equal(validateOperatorConfig({ ...copy(), priceSource: 'manual' }).priceSource, 'manual');
  for (const priceSource of ['', 'provider', 'FRAGMENT', null, 1]) assert.throws(() => validateOperatorConfig({ ...copy(), priceSource }), /priceSource/u);
});

test('exact markup ratios preserve canonical integers without floating point', () => {
  const config = copy();
  config.stars.TON.markupRatio = { numerator: '539612', denominator: '10229388' };
  config.stars.USDT = { basePerUnit: '0.015', markupRatio: { numerator: '19', denominator: '75' }, providerFee: '0' };
  const validated = validateOperatorConfig(config);
  assert.deepEqual(validated.stars.TON.markupRatio, { numerator: '539612', denominator: '10229388' });
  assert.deepEqual(validated.stars.USDT.markupRatio, { numerator: '19', denominator: '75' });
  assert.equal(validated.stars.USDT.markupBps, 0);
  const large = copy();
  large.stars.TON.markupRatio = { numerator: '90071992547409930001', denominator: '90071992547409930002' };
  assert.deepEqual(validateOperatorConfig(large).stars.TON.markupRatio, large.stars.TON.markupRatio);
});

test('markup ratio rejects signs, fractions, leading zeros, zero denominator, excess ratio and conflicting basis points', () => {
  for (const markupRatio of [
    { numerator: '-1', denominator: '2' }, { numerator: '+1', denominator: '2' },
    { numerator: '01', denominator: '2' }, { numerator: '1', denominator: '02' },
    { numerator: '1.0', denominator: '2' }, { numerator: '1e1', denominator: '20' },
    { numerator: 1, denominator: '2' }, { numerator: ' 1', denominator: '2' },
    { numerator: '1', denominator: '0' }, { numerator: '3', denominator: '2' },
    { numerator: '1' }, { numerator: '1', denominator: '2', hidden: true }, null,
  ]) {
    const config = copy(); config.stars.TON.markupRatio = markupRatio;
    assert.throws(() => validateOperatorConfig(config), /markupRatio/u);
  }
  const config = copy(); config.stars.TON.markupRatio = { numerator: '1', denominator: '2' }; config.stars.TON.markupBps = 1;
  assert.throws(() => validateOperatorConfig(config), /markupRatio/u);
  config.stars.TON.markupBps = 0;
  config.stars.TON.markupRatio = { numerator: '0', denominator: '1' };
  assert.equal(validateOperatorConfig(config).stars.TON.markupRatio.numerator, '0');
  config.stars.TON.markupRatio = { numerator: '1', denominator: '1' };
  assert.equal(validateOperatorConfig(config).stars.TON.markupRatio.numerator, '1');
});

test('configure creates only the backend module and exports exact local credentials', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'stars-config-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'config'));
  const input = configuredSales();
  await writeFile(path.join(root, 'config', 'operator.json'), JSON.stringify(input));
  const result = await configureProject(root);
  assert.equal(result.salesEnabled, true);
  const source = await readFile(result.outputPath, 'utf8');
  assert.match(source, /GENERATED_OPERATOR_CONFIG/u);
  const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  assert.equal(module.operatorConfig.fragment.jwt, input.fragment.jwt);
  assert.equal(module.operatorConfig.toncenterApiKey, input.toncenterApiKey);
  assert.equal(module.operatorConfig.stars.TON.markupBps, 200);
  assert.equal(result.outputPath, path.join(root, 'tgcloud', 'lib', 'operator-config.js'));
});

test('malformed or missing local JSON produces a redacted actionable error', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'stars-config-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await assert.rejects(configureProject(root), /config\/operator\.json/u);
  await mkdir(path.join(root, 'config'));
  await writeFile(path.join(root, 'config', 'operator.json'), '{"fragment":{"jwt":"never-print-this"}, broken');
  await assert.rejects(configureProject(root), error => {
    assert.ok(!error.message.includes('never-print-this'));
    return /корректный JSON/u.test(error.message);
  });
});

test('validation failure does not replace an already generated module', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'stars-config-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'config'));
  await mkdir(path.join(root, 'tgcloud', 'lib'), { recursive: true });
  const output = path.join(root, 'tgcloud', 'lib', 'operator-config.js');
  await writeFile(output, '// previous validated config\n');
  await writeFile(path.join(root, 'config', 'operator.json'), JSON.stringify({ ...copy(), salesEnabled: true }));
  await assert.rejects(configureProject(root), /salesEnabled/u);
  assert.equal(await readFile(output, 'utf8'), '// previous validated config\n');
});
