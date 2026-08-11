import test from 'node:test';
import assert from 'node:assert/strict';
import { runGooayeTopicResearch } from '../src/gooaye-topic-research.js';

const RSS = `<?xml version="1.0"?><rss><channel>
  <item><title><![CDATA[EP678 | 🎮]]></title><guid>ep678-guid</guid><pubDate>Sat, 11 Jul 2026 07:59:57 GMT</pubDate><enclosure url="https://example.test/678.mp3" /></item>
  <item><title><![CDATA[EP677 | 🐎]]></title><guid>ep677-guid</guid><pubDate>Wed, 08 Jul 2026 08:03:15 GMT</pubDate><enclosure url="https://example.test/677.mp3" /></item>
</channel></rss>`;

const MANIFEST = {
  generatedAt: '2026-07-11T14:42:11.468Z',
  items: [{
    id: 'research-gooaye-ep678-kami-report',
    title: '股癌 Gooaye EP678 AI供應鏈輪動研究報告',
    description: '整理股癌 EP678 的 AI 供應鏈輪動、資金偏好與風控重點',
    date: '2026-07-11',
    tags: ['股癌', 'Podcast', 'AI供應鏈', '被動元件', '光通訊', '記憶體', '半導體'],
    url: 'research/gooaye-ep678-kami/report.html',
  }],
};

test('uses official RSS as episode authority and returns matching read-only research metadata', async () => {
  const seen = [];
  const fetchFn = async (url) => {
    seen.push(String(url));
    if (String(url).includes('soundon.fm')) return new Response(RSS, { status: 200 });
    return new Response(JSON.stringify(MANIFEST), { status: 200 });
  };

  const result = await runGooayeTopicResearch({ date: '2026-07-14', tickers: '2330,2303' }, { fetchFn });

  assert.equal(result.status, 'ready');
  assert.equal(result.episode.number, 678);
  assert.equal(result.research.title, MANIFEST.items[0].title);
  assert.deepEqual(result.research.themes, ['AI供應鏈', '被動元件', '光通訊', '記憶體', '半導體']);
  assert.deepEqual(result.requestedTickers, ['2330', '2303']);
  assert.equal(result.readOnly, true);
  assert.match(result.research.url, /^https:\/\/gooaye\.teamtaiwan\.win\//);
  assert.match(seen[0], /soundon\.fm/);
});

test('honors an as-of date instead of leaking a newer episode into historical research', async () => {
  const fetchFn = async (url) => String(url).includes('soundon.fm')
    ? new Response(RSS, { status: 200 })
    : new Response(JSON.stringify({ ...MANIFEST, items: [
      MANIFEST.items[0],
      { ...MANIFEST.items[0], id: 'ep677', title: '股癌 EP677 研究', date: '2026-07-08', url: 'research/ep677.html' },
    ] }), { status: 200 });

  const result = await runGooayeTopicResearch({ date: '2026-07-09' }, { fetchFn });

  assert.equal(result.episode.number, 677);
  assert.equal(result.research.title, '股癌 EP677 研究');
  assert.equal(result.pointInTime, true);
});
