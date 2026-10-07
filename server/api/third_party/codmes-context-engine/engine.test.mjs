import test from 'node:test';
import assert from 'node:assert/strict';
import { prepareConversationContext, contextBudgetForModel } from './engine.mjs';

const session = { messages: Array.from({ length: 40 }, (_, i) => ({
  id: `m${i}`, role: i % 2 ? 'assistant' : 'user', content: '가'.repeat(600)
})) };
const options = { provider: 'test', model: 'test', contextWindow: 4000 };
test('small context windows still reserve output room',()=>{
  const budget=contextBudgetForModel('small',{contextWindow:2048});
  assert.ok(budget.inputBudget < 2048);
  assert.ok(budget.reservedTokenBudget > 0);
});
test('new question, instructions and schemas count toward compaction pressure',async()=>{
  let called=false;
  const result=await prepareConversationContext({messages:[{role:'user',content:'가'.repeat(1800)}]},
    {...options,promptOverheadTokens:1000},{summary:async()=>{called=true;return {mode:'summary',summary:'old facts'};}});
  assert.equal(called,true);
  assert.equal(result.stateChanged,true);
});
test('shared engine is lossless in storage and summary-based only in the request', async () => {
  const original = JSON.stringify(session);
  const result = await prepareConversationContext(session, options, {
    summary: async () => ({ mode: 'summary', summary: '목표와 결정 사항' })
  });
  assert.equal(JSON.stringify(session), original);
  assert.equal(result.stateChanged, true);
  assert.equal(result.summary.content, '목표와 결정 사항');
  assert.ok(result.history.length < 12);
  assert.equal(result.fallbackHistory.length, 40);
});
test('native failure falls back; empty summaries preserve all original messages', async () => {
  let summaryCalls = 0;
  const result = await prepareConversationContext(session, options, {
    native: async () => { throw new Error('unsupported'); },
    summary: async () => { summaryCalls++; return { mode: 'summary', summary: '' }; }
  });
  assert.equal(summaryCalls, 1);
  assert.equal(result.compactionFailed, true);
  assert.equal(result.history.length, 40);
  assert.equal(result.state, null);
});
test('a checkpoint is never reused for a different credential scope', async () => {
  const first = await prepareConversationContext(session, options, {
    summary: async () => ({ mode: 'summary', summary: 'first' })
  });
  let called = false;
  await prepareConversationContext({ ...session, contextCompaction: first.state },
    { ...options, provider: 'another-student' }, {
      summary: async plan => { called = true; assert.equal(plan.existingState, null);
        return { mode: 'summary', summary: 'separate' }; }
    });
  assert.equal(called, true);
});
