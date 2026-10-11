import test from 'node:test';
import assert from 'node:assert/strict';
import { quote, normalizeRecipient, markupPercent } from '../tgcloud/lib/pricing.js';

const settings = { stars: { USDT: {basePerUnit:'0.015',markupBps:300,providerFee:'0.1'} }, premium: { USDT: {3:'12.99'} } };
test('invoice contains exact base, markup and explicit fee', () => {
  assert.deepEqual(quote('STARS',100,'USDT',settings), {
    product:'STARS',quantity:100,currency:'USDT',baseAtomic:'1500000',markupAtomic:'45000',
    providerFeeAtomic:'100000',markupBps:300,amountAtomic:'1645000'
  });
});
test('markup rounds upwards by one atomic unit, never floating point', () => {
  const cfg = {stars:{USDT:{basePerUnit:'0.000001',markupBps:1,providerFee:'0'}}};
  assert.equal(quote('STARS',50,'USDT',cfg).amountAtomic,'51');
});
test('unconfigured, out of range, NaN and unknown products fail closed', () => {
  for (const n of [49,1000001,50.1,NaN]) assert.throws(()=>quote('STARS',n,'USDT',settings));
  assert.throws(()=>quote('STARS',100,'TON',settings));
  assert.throws(()=>quote('OTHER',100,'USDT',settings));
  assert.throws(()=>quote('PREMIUM',1,'USDT',settings));
});
test('recipient is validated before HTML and provider usage', () => {
  assert.equal(normalizeRecipient(' alice_123 '),'@alice_123');
  for (const s of ['<script>','https://t.me/alice','@a','@1234','@alice bob']) assert.throws(()=>normalizeRecipient(s));
});
test('Fragment comparison reproduces reference totals using exact effective markups', () => {
  const cfg={stars:{TON:{basePerUnit:'0.010229388',markupBps:0,markupRatio:{numerator:'539612',denominator:'10229388'},providerFee:'0'},USDT:{basePerUnit:'0.015',markupBps:0,markupRatio:{numerator:'19',denominator:'75'},providerFee:'0'}}};
  const ton=quote('STARS',100,'TON',cfg),usdt=quote('STARS',100,'USDT',cfg);
  assert.equal(ton.amountAtomic,'1076900000');assert.equal(usdt.amountAtomic,'1880000');
  assert.equal(markupPercent(ton.baseAtomic,ton.markupAtomic),'5.28');
  assert.equal(markupPercent(usdt.baseAtomic,usdt.markupAtomic),'25.33');
  assert.equal(quote('STARS',500,'USDT',cfg).amountAtomic,'9400000');
  cfg.stars.TON.basePerUnit='0.0105';
  assert.equal(quote('STARS',100,'TON',cfg).amountAtomic,'1105388710');
});
test('ratio markup rejects ambiguous double fees and malformed fractions',()=>{
  for(const ratio of [{numerator:'01',denominator:'10'},{numerator:'1',denominator:'0'},{numerator:'-1',denominator:'10'},{numerator:'11',denominator:'10'}]) {
    assert.throws(()=>quote('STARS',100,'USDT',{stars:{USDT:{basePerUnit:'0.015',markupRatio:ratio}}}));
  }
  assert.throws(()=>quote('STARS',100,'USDT',{stars:{USDT:{basePerUnit:'0.015',markupBps:500,markupRatio:{numerator:'1',denominator:'10'}}}}));
});
