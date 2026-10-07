import { useState, useRef, useEffect, useCallback } from 'react';
import * as api from './api.js';
import { conversationId, fromServer, legacyImport, importBatches } from './chat-history.js';

export function useConversations(authed) {
  const [conversations, setConversations] = useState([]);
  const [currentId, setCurrentId] = useState(conversationId);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [chatGenerating, setChatGenerating] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [historyNotice, setHistoryNotice] = useState('');
  const [historyCursor, setHistoryCursor] = useState(null);
  const [legacyAvailable, setLegacyAvailable] = useState(false);
  const [chatSource, setChatSource] = useState('personal');
  const items = useRef([]), selected = useRef(currentId), scope = useRef(0), busy = useRef(false), generating = useRef(false);
  function publish(next) { items.current = next; setConversations(next); }
  function select(id) { selected.current=id; setCurrentId(id); }
  const active = (epoch, token) => scope.current === epoch && api.getToken() === token;

  const operation = useCallback(async (fn) => {
    if (busy.current || generating.current) return false;
    const epoch = scope.current, token = api.getToken();
    busy.current=true; setHistoryBusy(true); setHistoryError('');
    try { await fn(() => active(epoch,token)); return active(epoch,token); }
    catch(e) { if(active(epoch,token)) setHistoryError(e.message); return false; }
    finally { if(scope.current === epoch) { busy.current=false; setHistoryBusy(false); } }
  }, []);

  const refreshConversations = useCallback((append=false) => operation(async valid => {
    const page = await api.conversationApi.list(append ? historyCursor : null);
    if(!valid()) return;
    // Summaries have no transcript. Reload the selected record too, so another
    // device's revision and the displayed messages cannot diverge after refresh.
    const loaded = page.items.map(c => ({ ...fromServer(c), messages: items.current.find(old => old.id === c.id)?.messages }));
    publish(append ? [...items.current, ...loaded.filter(c => !items.current.some(old=>old.id===c.id))] : loaded);
    setHistoryCursor(page.next_cursor);
    if(!append && items.current.some(c=>c.id===selected.current)) {
      const c=await api.conversationApi.get(selected.current);
      if(!valid()) return;
      publish(items.current.map(old=>old.id===c.id ? fromServer(c) : old)); setChatSource(c.source);
    }
  }), [historyCursor, operation]);

  useEffect(() => {
    const epoch = ++scope.current, token = api.getToken();
    publish([]); select(conversationId()); busy.current=false; generating.current=false;
    setChatGenerating(false); setHistoryBusy(false); setHistoryError(''); setHistoryNotice(''); setHistoryCursor(null);
    const username = api.currentUsername();
    setLegacyAvailable(Boolean(authed && username && api.getStoredItem(`knu_chat_${username}`)));
    setChatSource(api.getStoredItem(`knu_chat_source_${username}`) || 'personal');
    if (!authed) return;
    busy.current=true; setHistoryBusy(true);
    (async () => {
      try {
        const page=await api.conversationApi.list();
        if(!active(epoch,token)) return;
        publish(page.items.map(fromServer)); setHistoryCursor(page.next_cursor);
        if(page.items.length) {
          const c=await api.conversationApi.get(page.items[0].id);
          if(!active(epoch,token)) return;
          publish(items.current.map(item=>item.id===c.id ? fromServer(c) : item)); select(c.id); setChatSource(c.source);
        }
      } catch(e) { if(active(epoch,token)) setHistoryError(e.message); }
      finally { if(scope.current===epoch) { busy.current=false; setHistoryBusy(false); } }
    })();
    return () => { scope.current++; };
  }, [authed]);

  const newConversation = () => { if(busy.current || generating.current) return false; select(conversationId()); return true; };
  const loadConversation = id => operation(async valid => {
    const c=await api.conversationApi.get(id); if(!valid()) return;
    publish([fromServer(c), ...items.current.filter(old=>old.id!==id)]); select(id); setChatSource(c.source);
  });
  const deleteConversation = id => operation(async valid => {
    const c=items.current.find(c=>c.id===id); if(!c) return;
    await api.conversationApi.remove(id,c.revision); if(!valid()) return;
    publish(items.current.filter(c=>c.id!==id)); if(selected.current===id) select(conversationId());
  });
  const importConversations = () => operation(async valid => {
    const username=api.currentUsername();
    const batches=importBatches(legacyImport(api.getStoredItem(`knu_chat_${username}`)));
    for(const items of batches) { await api.conversationApi.import(items); if(!valid()) return; }
    const page=await api.conversationApi.list(); if(!valid()) return;
    const current=items.current.find(c=>c.id===selected.current);
    publish(page.items.map(c=>c.id===current?.id ? {...current,...fromServer(c),messages:current.messages} : fromServer(c)));
    setHistoryCursor(page.next_cursor); setLegacyAvailable(false);
    setHistoryNotice('기존 기록을 서버로 가져왔습니다. 브라우저 원본은 삭제하지 않았습니다.');
  });

  async function sendConversation(question, {onStep}={}) {
    if(busy.current || generating.current) return false;
    const id=selected.current, epoch=scope.current, token=api.getToken();
    const old=items.current.find(c=>c.id===id), before=old?.messages || [], source=chatSource;
    generating.current=true; setChatGenerating(true); setHistoryError(''); setHistoryNotice('');
    const draft={ ...old,id,title:old?.title || question.slice(0,20),source,
      messages:[...before,{role:'user',content:question},{role:'assistant',answer:{intro:'',streaming:true}}] };
    publish([draft,...items.current.filter(c=>c.id!==id)]);
    try {
      const result=await api.streamChatbot(question,[], {
        source,conversationId:id,revision:old?.revision || 0,requestId:conversationId(),
        onStep: label=>{ if(active(epoch,token)) onStep?.(label); },
        onToken: text=>{
          if(!active(epoch,token)) return;
          publish(items.current.map(c=>c.id===id ? {...c,messages:[...before,{role:'user',content:question},
            {role:'assistant',answer:{intro:text,streaming:true}}]} : c));
        }
      });
      if(!active(epoch,token)) return false;
      if(!result.conversation) throw new Error('서버가 대화 저장을 확인하지 못했습니다. 목록을 새로고침해주세요.');
      publish([fromServer(result.conversation),...items.current.filter(c=>c.id!==id)]);
      return true;
    } catch(e) {
      if(active(epoch,token)) {
        // A lost response may have been committed. Reload that UUID before retrying.
        try {
          const saved=await api.conversationApi.get(id);
          if(active(epoch,token)) {
            publish([fromServer(saved),...items.current.filter(c=>c.id!==id)]); setChatSource(saved.source);
            const lastQuestion=saved.messages?.at(-2);
            if(saved.revision > (old?.revision || 0) && lastQuestion?.role==='user' &&
              lastQuestion.content===question && saved.messages?.at(-1)?.role==='assistant') {
              setHistoryNotice('답변 연결은 끊겼지만 서버에 저장된 답변을 복원했습니다.');
              return true;
            }
          }
        } catch {
          if(active(epoch,token)) publish(old ? [old,...items.current.filter(c=>c.id!==id)] : items.current.filter(c=>c.id!==id));
        }
        if(active(epoch,token)) setHistoryError(e.message);
      }
      return false;
    } finally { if(scope.current===epoch) { generating.current=false; setChatGenerating(false); } }
  }
  function chooseChatSource(source) {
    if(busy.current || generating.current) return;
    setChatSource(source); api.setStoredItem(`knu_chat_source_${api.currentUsername()}`,source);
  }
  return { conversations,currentId,chatMsgs:conversations.find(c=>c.id===currentId)?.messages || [],
    historyBusy,chatGenerating,historyError,historyNotice,historyCursor,legacyAvailable,
    refreshConversations,newConversation,loadConversation,deleteConversation,importConversations,
    sendConversation,chatSource,chooseChatSource };
}
