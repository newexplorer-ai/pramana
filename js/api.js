/* ============================================================
   Pramana — API client.
   When the FastAPI backend is reachable (same origin, /api/*),
   the app runs in LIVE mode: real auth, real answers, server
   allowlist. When it isn't (e.g. the GitHub Pages static demo),
   PRAMANA_API.on is false and the pages keep their local demo
   behaviour. Detection happens synchronously via a HEAD-start
   fetch resolved before app boot (each page awaits API.ready).
   ============================================================ */
const PRAMANA_API = (function(){
  'use strict';

  const TOKEN_KEY = 'pramana_token';
  const state = { on:false, health:null };

  const token = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch(e){ return ''; } };
  const setToken = t => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch(e){} };

  const ready = (async () => {
    try {
      const r = await fetch('/api/health', { cache:'no-store' });
      if (r.ok) { state.health = await r.json(); state.on = true; }
    } catch(e){ /* static hosting — demo mode */ }
    return state.on;
  })();

  async function call(method, path, body){
    const headers = { 'Content-Type':'application/json' };
    const t = token();
    if (t) headers['Authorization'] = 'Bearer ' + t;
    const r = await fetch(path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (r.status === 401) {
      // Session revoked or expired — sign out everywhere.
      setToken('');
      try { localStorage.removeItem('pramana_session'); } catch(e){}
      if (!location.pathname.endsWith('login.html')) {
        location.href = 'login.html?signedout=1';
      }
      throw new Error('unauthorized');
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.detail || r.statusText); e.detail = data.detail; e.status = r.status; throw e; }
    return data;
  }

  /* POST /api/ask and stream SSE stage/result/error events. */
  async function ask(query, conversationId, handlers){
    const headers = { 'Content-Type':'application/json', 'Authorization':'Bearer ' + token() };
    const r = await fetch('/api/ask', {
      method:'POST', headers,
      body: JSON.stringify({ query, conversation_id: conversationId || undefined }),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) { setToken(''); location.href = 'login.html?signedout=1'; return; }
      throw new Error(data.detail || ('ask_failed_' + r.status));
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for(;;){
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream:true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
        const ev = /^event: (.+)$/m.exec(chunk);
        const da = /^data: (.+)$/m.exec(chunk);
        if (!ev || !da) continue;
        const data = JSON.parse(da[1]);
        if (handlers[ev[1]]) handlers[ev[1]](data);
      }
    }
  }

  return {
    ready, state,
    get on(){ return state.on; },
    get health(){ return state.health; },
    token, setToken,
    get:    p => call('GET', p),
    post:   (p, b) => call('POST', p, b || {}),
    patch:  (p, b) => call('PATCH', p, b || {}),
    del:    p => call('DELETE', p),
    ask,
  };
})();
