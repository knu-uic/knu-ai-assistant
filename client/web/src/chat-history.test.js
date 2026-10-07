import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationId, fromServer, legacyImport, importBatches } from './chat-history.js';

test('new IDs are UUIDs accepted by the server',()=>{
  assert.match(conversationId(),/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
test('server messages render without lossy truncation',()=>{
  const content='가'.repeat(20000);
  const converted=fromServer({id:'one',created_at:'2026-10-07T01:00:00Z',updated_at:'2026-10-07T01:00:00Z',messages:[{role:'assistant',content}]});
  assert.equal(converted.messages[0].answer.intro,content);
});
test('explicit legacy conversion preserves original, drops unfinished streaming only',()=>{
  const raw=JSON.stringify([{id:'legacy',title:'기존',messages:[{role:'user',content:'질문'},
    {role:'assistant',answer:{intro:'답변',outro:'근거'}},{role:'assistant',answer:{intro:'미완료',streaming:true}}]}]);
  const items=legacyImport(raw);
  assert.equal(items[0].legacy_key,'legacy');
  assert.deepEqual(items[0].messages,[{role:'user',content:'질문'},{role:'assistant',content:'답변\n근거'}]);
  assert.equal(JSON.parse(raw)[0].messages.length,3);
});
test('imports batch by characters as well as count',()=>{
  const items=Array.from({length:25},(_,i)=>({legacy_key:String(i),messages:[{role:'user',content:'a'.repeat(60000)}]}));
  assert.deepEqual(importBatches(items).map(b=>b.length),[16,9]);
});
test('oversized imports are refused rather than silently truncated',()=>{
  assert.throws(()=>legacyImport(JSON.stringify([{id:'large',messages:[{role:'user',content:'a'.repeat(100001)}]}])),/한도/);
});
