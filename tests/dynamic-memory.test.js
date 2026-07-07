import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { main } from '../src/cli.js';
import { syncDynamicMemory } from '../src/dynamic-memory.js';

test('syncDynamicMemory records only allowed durable memory entries', async () => {
  const root = await mkdtemp(join(tmpdir(), 'trade-memory-allow-'));
  try {
    const memoryDir = join(root, '.omx', 'memory');
    const result = syncDynamicMemory({
      memoryDir,
      now: '2026-06-26T12:00:00+08:00',
      entries: [
        {
          date: '2026-06-26',
          category: 'decision',
          text: 'Standard Workflow 1.01 remains locked until a goal documents a verified process change.',
          source: 'docs/standard-workflow-v1.md',
        },
        {
          date: '2026-06-26',
          category: 'intraday-guess',
          text: '未驗證的盤中猜測：某檔看起來會噴。',
        },
        {
          date: '2026-06-26',
          category: 'verified-fix',
          text: 'Raw secret leaked: LINE userId U0123456789abcdef0123456789abcdef and FINANCIAL_DATASETS_API_KEY=abc.',
        },
      ],
    });

    assert.equal(result.accepted, 1);
    assert.equal(result.rejected, 2);
    assert.equal(result.layers.hot, 1);
    const hot = readFileSync(join(memoryDir, 'hot.md'), 'utf8');
    assert.match(hot, /Standard Workflow 1\.01 remains locked/);
    assert.doesNotMatch(hot, /盤中猜測/);
    assert.doesNotMatch(hot, /U0123456789abcdef/);
    assert.doesNotMatch(hot, /FINANCIAL_DATASETS_API_KEY/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('syncDynamicMemory rotates hot, warm, archive, and obsolete layers by age and cap', async () => {
  const root = await mkdtemp(join(tmpdir(), 'trade-memory-rotate-'));
  try {
    const memoryDir = join(root, '.omx', 'memory');
    const recentEntries = Array.from({ length: 21 }, (_, index) => ({
      date: '2026-06-26',
      category: 'milestone',
      text: `Delivered verified milestone ${index + 1}.`,
      source: 'tests',
    }));
    const result = syncDynamicMemory({
      memoryDir,
      now: '2026-06-26T12:00:00+08:00',
      maxHotEntries: 20,
      entries: [
        ...recentEntries,
        { date: '2026-05-20', category: 'failure-case', text: '2458 weak follower case kept for historical review.', source: 'retro' },
        { date: '2026-06-10', category: 'verified-fix', text: 'Shioaji NotReady session repair verified by health and quote checks.', source: 'ops' },
        { date: '2026-06-01', category: 'decision', text: 'Old R18H6 baseline replaced by WR3 standard.', obsolete: true, reason: 'Replaced by Standard Workflow 1.01' },
      ],
    });

    assert.equal(result.layers.hot, 20);
    assert.equal(result.layers.warm, 2);
    assert.equal(result.layers.archive, 1);
    assert.equal(result.layers.obsolete, 1);

    const hot = readFileSync(join(memoryDir, 'hot.md'), 'utf8');
    assert.match(hot, /Delivered verified milestone 21/);
    assert.doesNotMatch(hot, /Delivered verified milestone 1\./);

    const warm = readFileSync(join(memoryDir, 'warm.md'), 'utf8');
    assert.match(warm, /Delivered verified milestone 1\./);
    assert.match(warm, /Shioaji NotReady session repair/);

    const archive = readFileSync(join(memoryDir, 'archive.md'), 'utf8');
    assert.match(archive, /2458 weak follower case/);

    const obsolete = readFileSync(join(memoryDir, 'obsolete.md'), 'utf8');
    assert.match(obsolete, /Old R18H6 baseline replaced by WR3 standard/);
    assert.match(obsolete, /Replaced by Standard Workflow 1\.01/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('syncDynamicMemory drops invalid existing memory entries before rewriting', async () => {
  const root = await mkdtemp(join(tmpdir(), 'trade-memory-revalidate-'));
  try {
    const memoryDir = join(root, '.omx', 'memory');
    mkdirSync(memoryDir, { recursive: true });
    writeFileSync(join(memoryDir, 'hot.md'), [
      '# Dynamic Memory — Hot',
      '',
      '- 2026-06-25 | decision | Existing safe entry (source: docs; reason: stable)',
      '- 2026-06-25 | intraday-guess | Existing unsafe guess should be dropped',
      '',
    ].join('\n'));

    const result = syncDynamicMemory({
      memoryDir,
      now: '2026-06-26T12:00:00+08:00',
      entries: [
        { date: '2026-06-26', category: 'verified-fix', text: 'Fresh verified fix preserved.', source: 'tests' },
      ],
    });

    assert.equal(result.accepted, 1);
    assert.equal(result.layers.hot, 2);
    const hot = readFileSync(join(memoryDir, 'hot.md'), 'utf8');
    assert.match(hot, /Fresh verified fix preserved\./);
    assert.match(hot, /Existing safe entry/);
    assert.doesNotMatch(hot, /Existing unsafe guess/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('parseMemoryMarkdown preserves normal trailing parentheses that are not metadata', async () => {
  const root = await mkdtemp(join(tmpdir(), 'trade-memory-parentheses-'));
  try {
    const memoryDir = join(root, '.omx', 'memory');
    mkdirSync(memoryDir, { recursive: true });
    writeFileSync(join(memoryDir, 'hot.md'), [
      '# Dynamic Memory — Hot',
      '',
      '- 2026-06-25 | decision | Keep this note (Q2 update)',
      '',
    ].join('\n'));

    const result = syncDynamicMemory({
      memoryDir,
      now: '2026-06-26T12:00:00+08:00',
      entries: [],
    });

    assert.equal(result.accepted, 0);
    const hot = readFileSync(join(memoryDir, 'hot.md'), 'utf8');
    assert.match(hot, /Keep this note \(Q2 update\)/);
    assert.doesNotMatch(hot, /Keep this note\s*\)/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('CLI memory-sync reads JSON entries and reports layer counts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'trade-memory-cli-'));
  try {
    const memoryDir = join(root, '.omx', 'memory');
    const entryFile = join(root, 'entries.json');
    mkdirSync(root, { recursive: true });
    writeFileSync(entryFile, JSON.stringify([
      {
        date: '2026-06-26',
        category: 'decision',
        text: 'Dynamic memory hot/warm/archive layout accepted for repo-local runtime memory.',
        source: 'user-goal',
      },
    ]));

    const out = await main([
      'memory-sync',
      '--memory-dir', memoryDir,
      '--entry-file', entryFile,
      '--now', '2026-06-26T12:00:00+08:00',
      '--format', 'markdown',
    ]);

    assert.match(out, /# Dynamic memory sync/);
    assert.match(out, /Accepted: 1/);
    assert.match(out, /Hot: 1/);
    assert.match(readFileSync(join(memoryDir, 'hot.md'), 'utf8'), /Dynamic memory hot\/warm\/archive layout accepted/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
