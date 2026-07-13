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
  assert.doesNotMatch(workflow, /run_gooaye_worker\.sh/);
  assert.doesNotMatch(workflow, /IC\.TPEX peer context.*排序/);
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
  assert.match(handoff, /唯一.*決策.*phase3-screen|phase3-screen.*唯一.*決策/);
  assert.match(handoff, /daily-decision-study.*歷史|歷史.*daily-decision-study/);
  assert.doesNotMatch(handoff, /Phase 3 技術結論.*daily-decision-study/);
  assert.doesNotMatch(handoff, /phase3-demo-promotion|logistic|walk-forward/i);
});

test('active guidance places independent DOM confidence after external research', () => {
  const workflow = read('docs/standard-workflow-v1.md');
  const handoff = read('docs/line-session-handoff.md');
  const readme = read('README.md');
  const combined = `${workflow}\n${handoff}\n${readme}`;

  for (const document of [workflow, handoff]) {
    assert.match(
      document,
      /phase3-dataset\s*(?:→|->).*phase3-screen\s*(?:→|->).*news\/earnings\/financial confidence\s*(?:→|->).*phase3-dom-confidence\s*(?:→|->).*manual decision/is,
    );
  }
  assert.match(combined, /DOM.*(?:不進入|不得進入).*Phase 3.*(?:資料|候選資格|eligibility)/is);
  for (const field of [
    'activeEntryLimit',
    'patientEntryPrice',
    'takeProfitPrice',
    'stopLossPrice',
  ]) {
    assert.match(combined, new RegExp(field));
  }
  assert.match(combined, /(?:等待|wait).*仍.*(?:四個|全部).*價格/is);
});

test('top-level guidance converges on Standard Workflow 1.3 and Phase 3', () => {
  const publicGuidance = [
    read('README.md'),
    read('workflows/taiwan-agent-team.md'),
    read('docs/line-bridge.md'),
    read('docs/diagrams/standard-workflow-v1.drawio'),
    read('docs/diagrams/standard-workflow-v1.svg'),
  ].join('\n');
  assert.match(publicGuidance, /Standard Workflow 1\.3/);
  assert.match(publicGuidance, /phase3_stability/);
  assert.doesNotMatch(publicGuidance, /Standard Workflow 1\.01|R18H6_VOL_exit_only_WR3|MVP backtest flows|MVP strategy/i);
  assert.doesNotMatch(publicGuidance, /runs both `daily-decision-study` plus `signal-study` before entry advice|daily-decision \+ signal/i);
  assert.match(publicGuidance, /phase3-dataset/);
  assert.match(publicGuidance, /phase3-screen/);
});
