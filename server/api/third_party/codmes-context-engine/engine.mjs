import {
  createCompactionState, planConversationCompaction, promptContextFromPlan
} from './conversation-compaction.mjs';
export * from './conversation-compaction.mjs';
export * from './context-budget.mjs';

export function compactionInstructions() {
  return [
    "Compress the conversation for faithful continuation of the same task.",
    "Preserve the user's objective and constraints, decisions, completed actions, exact identifiers and file paths, tool outcomes, unresolved errors or blockers, and the next concrete work.",
    "Preserve unrelated side questions only when they changed requirements or state.",
    "Use the conversation's primary language. Do not invent facts, claim unverified work is complete, or include commentary about the compression process."
  ].join(' ');
}

// Extracted from OpenAICompatibleRuntime.prepareSessionContext. No credentials,
// workspace, storage, network or provider SDK dependency belongs in this module.
export async function prepareConversationContext(session, options, adapters) {
  const plan = planConversationCompaction(session, options);
  if (!plan.shouldCompact) return { ...promptContextFromPlan(plan), stateChanged: false };
  let compacted;
  const emit = (event) => adapters.onEvent?.(event);
  if ((!plan.existingState || plan.existingState.mode === 'native') && adapters.native) {
    try {
      compacted = await adapters.native(plan);
      // Invalid native responses also fall back to the semantic summarizer.
      createCompactionState(plan, compacted);
    } catch (error) {
      compacted = undefined;
      emit({ type: 'context.compaction.fallback', from: 'native', to: 'auxiliary_model',
        error: error?.message || 'Native compaction failed.', createdAt: new Date().toISOString() });
    }
  }
  if (!compacted) {
    try {
      compacted = await adapters.summary(plan);
      createCompactionState(plan, compacted);
    } catch (error) {
      emit({ type: 'context.compaction.failed', error: error?.message || 'Conversation compaction failed.',
        retainedOriginalMessages: true, createdAt: new Date().toISOString() });
      return { ...promptContextFromPlan({ ...plan, existingState: null }, null),
        stateChanged: false, compactionFailed: true };
    }
  }
  const state = createCompactionState(plan, compacted);
  emit({ type: 'context.compacted', reason: 'conversation_threshold', mode: state.mode,
    coveredMessageCount: state.coveredMessageCount,
    recentMessageCount: plan.messages.length - state.coveredMessageCount,
    compactionCount: state.compactionCount, contextWindow: plan.contextWindow,
    thresholdTokens: plan.thresholdTokens, createdAt: state.updatedAt });
  return { ...promptContextFromPlan(plan, state), stateChanged: true };
}
