import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(path, 'utf8');

test('standard workflow promotes phase3_stability as the sole main strategy', () => {
  const workflow = read('docs/standard-workflow-v1.md');

  assert.match(workflow, /Standard Workflow 1\.3/);
  assert.match(workflow, /唯一有效主策略：`phase3_stability`/);
  assert.match(workflow, /phase3-screen/);
  assert.match(workflow, /maximumClosePosition = 0\.72/);
  assert.match(workflow, /maximumMomentum5Pct = 18/);
  assert.match(workflow, /read_only/);
  assert.match(workflow, /不得觸發真實下單 API/);
  assert.doesNotMatch(workflow, /phase3-demo-promotion|logistic|prediction threshold|walk-forward promotion/i);
  assert.doesNotMatch(workflow, /唯一有效 MVP：`R18H6_VOL_exit_only_WR3`/);
});

test('active workflow guidance no longer routes decisions through the replaced MVP strategy', () => {
  const activeGuidance = [
    'docs/standard-workflow-v1.md',
    'docs/line-session-handoff.md',
    'docs/gooaye-transcript-agent-handoff.md',
    'src/xiaoyu-etf.js',
  ].map((path) => `${path}\n${read(path)}`).join('\n---\n');

  assert.doesNotMatch(activeGuidance, /R18H6_VOL_exit_only_WR3/);
  assert.doesNotMatch(activeGuidance, /Standard Workflow 1\.01/);
  assert.doesNotMatch(activeGuidance, /active MVP/i);
});


test('line handoff includes phase3 as the main strategy step', () => {
  const handoff = read('docs/line-session-handoff.md');

  assert.match(handoff, /phase3_stability/);
  assert.match(handoff, /phase3-screen/);
  assert.match(handoff, /技術候選/);
  assert.match(handoff, /外部資訊.*信心加權/);
  assert.doesNotMatch(handoff, /phase3-demo-promotion|logistic|walk-forward/i);
});
