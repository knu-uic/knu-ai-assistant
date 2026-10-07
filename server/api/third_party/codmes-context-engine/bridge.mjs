// One isolated process per request. JSONL over pipes, never a network listener.
// The host owns provider calls; credentials never cross this protocol.
import { createInterface } from 'node:readline';
import {
  prepareConversationContext, compactionTranscript, compactionInstructions,
  estimateMessagesTokens, contextBudgetForModel
} from './engine.mjs';

const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
const lines = reader[Symbol.asyncIterator]();
const write = value => process.stdout.write(JSON.stringify(value) + '\n');
let sequence = 0;
let options = {};
async function receive() {
  const line = await lines.next();
  if (line.done || line.value.length > 16 * 1024 * 1024) throw new Error('Invalid bridge frame');
  return JSON.parse(line.value);
}
async function invoke(mode, payload) {
  const id = ++sequence;
  const estimatedTokens = estimateMessagesTokens([
    { role: 'system', content: payload.instructions },
    { role: 'user', content: payload.transcript || JSON.stringify(payload.input) }
  ]);
  const inputBudget = contextBudgetForModel(options.model, { contextWindow: options.contextWindow }).inputBudget;
  write({ type: 'compact', id, mode, estimatedTokens, inputBudget, ...payload });
  const response = await receive();
  if (response.type !== 'compaction_result' || response.id !== id) throw new Error('Invalid bridge response');
  if (response.error) throw new Error('Provider compaction failed');
  return response.result;
}
try {
  const request = await receive();
  if (request.type === 'estimate') {
    write({ type: 'result', tokens: estimateMessagesTokens(request.messages),
      budget: contextBudgetForModel(request.model, request.overrides) });
  } else if (request.type === 'prepare') {
    options = request.options;
    const result = await prepareConversationContext(request.session, request.options, {
      native: request.nativeSupported ? plan => invoke('native', {
        input: [...(plan.existingState?.output || []), ...plan.messagesToCompact.map(m => ({ role: m.role, content: m.content }))],
        instructions: compactionInstructions()
      }) : null,
      summary: plan => invoke('summary', { transcript: compactionTranscript(plan), instructions: compactionInstructions() })
    });
    write({ type: 'result', ...result });
  } else throw new Error('Unknown bridge operation');
} catch {
  // Never expose transcript, provider errors or stack traces to logs.
  write({ type: 'error', detail: 'Context engine failed' });
  process.exitCode = 1;
} finally { reader.close(); }
