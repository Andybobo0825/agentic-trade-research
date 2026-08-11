import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(path, 'utf8');

test('standard workflow promotes phase3_stability as the sole main strategy', () => {
  const workflow = read('docs/standard-workflow-v1.md');

  assert.match(workflow, /Standard Workflow 1\.4/);
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
  assert.match(handoff, /唯一.*篩選.*phase3-screen|phase3-screen.*唯一.*篩選/);
  assert.match(handoff, /daily-decision-study.*歷史|歷史.*daily-decision-study/);
  assert.doesNotMatch(handoff, /Phase 3 技術結論.*daily-decision-study/);
  assert.doesNotMatch(handoff, /phase3-demo-promotion|logistic|walk-forward/i);
});

test('active guidance places Gooaye after other external research and before independent DOM confidence', () => {
  const workflow = read('docs/standard-workflow-v1.md');
  const handoff = read('docs/line-session-handoff.md');
  const readme = read('README.md');
  const combined = `${workflow}\n${handoff}\n${readme}`;

  for (const document of [workflow, handoff]) {
    assert.match(
      document,
      /phase3-dataset\s*(?:→|->).*phase3-screen\s*(?:→|->).*company\/industry\/ETF research\s*(?:→|->).*gooaye-topic-research\s*(?:→|->).*phase3-dom-confidence\s*(?:→|->).*manual decision/is,
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

test('top-level guidance converges on Standard Workflow 1.4 and the official agent-team entry', () => {
  const publicGuidance = [
    read('README.md'),
    read('workflows/taiwan-agent-team.md'),
    read('docs/line-bridge.md'),
    read('docs/diagrams/standard-workflow-v1.drawio'),
    read('docs/diagrams/standard-workflow-v1.svg'),
  ].join('\n');
  assert.match(publicGuidance, /Standard Workflow 1\.4/);
  assert.match(publicGuidance, /taiwan-agent-team/);
  assert.match(publicGuidance, /phase3_stability/);
  assert.doesNotMatch(publicGuidance, /Standard Workflow 1\.01|R18H6_VOL_exit_only_WR3|MVP backtest flows|MVP strategy/i);
  assert.doesNotMatch(publicGuidance, /runs both `daily-decision-study` plus `signal-study` before entry advice|daily-decision \+ signal/i);
  assert.match(publicGuidance, /phase3-dataset/);
  assert.match(publicGuidance, /phase3-screen/);
});

test('README introduces all seven Standard Workflow 1.4 agent lanes and both public modes', () => {
  const readme = read('README.md');
  for (const agent of [
    'planner',
    'data-agent',
    'strategy-agent',
    'market-agent',
    'external-confidence-agent',
    'dom-agent',
    'verifier',
  ]) {
    assert.match(readme, new RegExp(`\\b${agent}\\b`));
  }
  assert.match(readme, /--mode screen/);
  assert.match(readme, /--mode analyze/);
  assert.match(readme, /只有.*(?:選股|篩選).*Phase 3|Phase 3.*只有.*(?:選股|篩選)/s);
});

test('active guidance skips Phase 3 for direct ticker analysis and keeps screen candidates eligible-only', () => {
  const combined = [
    read('README.md'),
    read('docs/standard-workflow-v1.md'),
    read('docs/line-session-handoff.md'),
    read('workflows/taiwan-agent-team.md'),
  ].join('\n');
  assert.match(combined, /analyze.*(?:不執行|跳過).*Phase 3/is);
  assert.match(combined, /(?:only|只).*eligible.*(?:外部|research|DOM)|eligible.*(?:only|只).*downstream/is);
  assert.match(combined, /零.*(?:候選|eligible).*(?:停止|不執行).*DOM/is);
});
