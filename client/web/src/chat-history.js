// Pure conversion helpers, shared by UI and import tests. No implicit upload.
export function conversationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (!globalThis.crypto?.getRandomValues) throw new Error('안전한 대화 ID를 생성할 수 없습니다. 최신 브라우저를 사용해주세요.');
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export function fromServer(c) {
  return { ...c, createdAt: Date.parse(c.created_at), updatedAt: Date.parse(c.updated_at),
    messages: c.messages?.map(m => m.role === 'user' ? m :
      { role: 'assistant', answer: { intro: m.content, outro: '', streaming: false } }) };
}
export function legacyImport(raw) {
  const conversations = JSON.parse(raw || '[]');
  if (!Array.isArray(conversations)) throw new Error('기존 브라우저 대화 기록의 형식을 확인해주세요.');
  return conversations.filter(c => c.messages?.length).map(c => {
    const messages = c.messages.filter(m => !m.answer?.streaming).map(m => {
      if (!['user', 'assistant'].includes(m.role)) throw new Error('가져올 수 없는 메시지 역할입니다.');
      const content = m.role === 'user' ? m.content :
        [m.answer?.intro || m.content, ...(m.answer?.bullets || []), m.answer?.outro].filter(Boolean).join('\n');
      return { role: m.role, content: String(content || '') };
    }).filter(m => m.content.trim());
    if (messages.length > 10000 || messages.some(m => m.content.length > 100000) ||
        messages.reduce((sum,m) => sum + m.content.length, 0) > 1000000)
      throw new Error('일부 기존 대화가 저장 한도를 초과합니다. 브라우저 원본은 그대로 유지됩니다.');
    if (!c.id || String(c.id).length > 128) throw new Error('기존 대화 ID를 확인해주세요.');
    return { legacy_key: String(c.id), title: String(c.title || messages[0]?.content || '이전 대화').slice(0,100),
      source: ['school','personal'].includes(c.source) ? c.source : 'personal', messages };
  }).filter(c => c.messages.length);
}

export function importBatches(items) {
  const batches = []; let batch = [], size = 0;
  for (const item of items) {
    const chars = item.messages.reduce((sum,m) => sum + m.content.length, 0);
    if (batch.length && (batch.length >= 20 || size + chars > 1000000)) { batches.push(batch); batch=[]; size=0; }
    batch.push(item); size += chars;
  }
  if (batch.length) batches.push(batch);
  return batches;
}
