import test from 'node:test';
import assert from 'node:assert/strict';
import { getIcTpexCategory, getIcTpexCompanyChain } from '../src/ic-tpex.js';

test('getIcTpexCategory parses industry-chain company groups from official HTML', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      assert.equal(String(url), 'https://ic.tpex.org.tw/introduce.php?ic=5300');
      return new Response(`<!doctype html><html><body>
        <h3>人工智慧產業鏈簡介</h3>
        <div>運算資源</div><div>運算設備</div>
        本國上市公司(2家) <a href="company_basic.php?stk_code=2308">台達電</a> <a href="company_basic.php?stk_code=6112">邁達特</a>
        本國上櫃公司(1家) <a href="company_basic.php?stk_code=6690">安碁資訊</a>
        知名外國企業(1家) <a href="https://example.com">Google</a>
        共4家
      </body></html>`, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } });
    };

    const result = await getIcTpexCategory({ ic: '5300' });

    assert.equal(result.source, 'ic.tpex');
    assert.equal(result.ic, '5300');
    assert.equal(result.title, '人工智慧產業鏈簡介');
    assert.deepEqual(result.companies.slice(0, 3), [
      { code: '2308', name: '台達電' },
      { code: '6112', name: '邁達特' },
      { code: '6690', name: '安碁資訊' },
    ]);
    assert.equal(result.companies.some((row) => row.name === 'Google'), false);
    assert.match(result.disclaimer, /classification only/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('getIcTpexCompanyChain follows stock code page and reports chain code', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      assert.equal(String(url), 'https://ic.tpex.org.tw/company_chain.php?stk_code=2330');
      return new Response(`<!doctype html><html><body>
        <a href="introduce.php?ic=D000&stk_code=2330">產業鏈簡介</a>
        <h3>半導體產業鏈簡介</h3>
        <div>台積電</div>
        <div>IC/晶圓製造</div>
      </body></html>`, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } });
    };

    const result = await getIcTpexCompanyChain({ ticker: '2330' });

    assert.equal(result.ticker, '2330');
    assert.equal(result.ic, 'D000');
    assert.equal(result.title, '半導體產業鏈簡介');
    assert.match(result.text, /IC\/晶圓製造/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
