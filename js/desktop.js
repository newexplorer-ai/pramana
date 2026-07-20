/* ============================================================
   Pramana — desktop app controller
   Canvases: App Ask · App Conversation (Tier 1/2/3).
   Views: ask · conversation · library · sources.
   PRD decisions applied: D1(c) high-stakes withhold, D2 library
   = saved conversations, D3/D4 single model chip, D5 follow-ups
   Tier 1 only.
   ============================================================ */
(function(){
  'use strict';

  const convo      = document.getElementById('convo');
  const convoScroll= document.getElementById('convoScroll');
  const mainTitle  = document.getElementById('mainTitle');
  const railTitle  = document.getElementById('railTitle');
  const railMode   = document.getElementById('railMode');
  const railBody   = document.getElementById('railBody');
  const recentsEl  = document.getElementById('recents');
  const qform      = document.getElementById('qform');
  const qinput     = document.getElementById('qinput');
  const tierStrip  = document.getElementById('tierStrip');
  const saveBtn    = document.getElementById('saveBtn');

  /* ---------- icons ---------- */
  const I = {
    file:'<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    chart:'<path d="M4 19V5m0 14h16M8 15l3-4 3 3 4-6"/>',
    plus:'<path d="M12 3v18M3 12h18"/>',
    globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
    list:'<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    like:'<path d="M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 3 2l-1 4h5a2 2 0 0 1 2 2l-2 7a2 2 0 0 1-2 1H7"/>',
    copy:'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    check:'<path d="M20 6L9 17l-5-5"/>',
    shield:'<path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    book:'<path d="M6 4h11a2 2 0 0 1 2 2v14l-7-4-6 4V4z"/>',
    src:'<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M6 3v16"/>',
  };
  const svg = (path, o={}) =>
    `<svg width="${o.w||13}" height="${o.h||o.w||13}" viewBox="0 0 24 24" fill="${o.fill||'none'}" stroke="${o.stroke||'currentColor'}" stroke-width="${o.sw||2}" ${o.style?`style="${o.style}"`:''}>${path}</svg>`;
  const sparkle = (fill='#6a5a86',w=12)=>`<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="${fill}"><path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"/></svg>`;

  /* ---------- recents ---------- */
  const RECENTS = [
    { id:'diabetes',  title:'Type 2 diabetes — first-line',  query:'First-line management of type 2 diabetes in adults per Indian guidelines?' },
    { id:'dengue',    title:'Dengue fluid management',       query:'Current ICMR advisory on dengue fluid management?' },
    { id:'cap',       title:'CAP empirical antibiotics',     query:'Empirical antibiotics for community-acquired pneumonia in India?' },
    { id:'crohns',    title:'Paediatric Crohn’s biologics',  query:'Preferred biologic sequencing for refractory paediatric Crohn’s in Indian practice?' },
    { id:'nlem',      title:'NLEM amoxicillin dosing',       query:'Adult amoxicillin dosing per the NLEM?' },
    { id:'ckd',       title:'Hypertension in CKD',           query:'First-line antihypertensive in CKD per Indian guidelines?' },
  ];
  let activeRecent = 'diabetes';
  let current = null;            // the conversation on screen (for Save)
  let timers = [];
  const clearTimers = () => { timers.forEach(clearTimeout); timers = []; };

  /* LIVE mode state (backend present): server-issued conversation id and
     this session's real recents. */
  const LIVE = { convId:null, recents:[], queryId:null };
  const isLive = () => PRAMANA_API.on;

  /* ---------- library persistence (D2: saved conversations only) ---------- */
  const LIB_KEY = 'pramana_library';
  const libRead  = () => { try { return JSON.parse(localStorage.getItem(LIB_KEY)) || []; } catch(e){ return []; } };
  const libWrite = list => localStorage.setItem(LIB_KEY, JSON.stringify(list));

  function renderRecents(){
    if(isLive()){
      recentsEl.innerHTML = LIVE.recents.length
        ? LIVE.recents.map((r,i) =>
            `<button class="recent ${r.convId===LIVE.convId?'active':''}" data-i="${i}" title="${esc(r.title)}">${esc(r.title)}</button>`).join('')
        : `<div class="rail-note" style="padding:4px 10px;">Questions you ask appear here.</div>`;
      recentsEl.querySelectorAll('.recent').forEach(el =>
        el.addEventListener('click', () => {
          const r = LIVE.recents[+el.getAttribute('data-i')];
          LIVE.convId = r.convId;
          renderLiveAnswer(r.result, r.query);
        }));
      return;
    }
    recentsEl.innerHTML = RECENTS.map(r =>
      `<button class="recent ${r.id===activeRecent?'active':''}" data-id="${r.id}" title="${esc(r.title)}">${esc(r.title)}</button>`).join('');
    recentsEl.querySelectorAll('.recent').forEach(el =>
      el.addEventListener('click', () => {
        const r = RECENTS.find(x => x.id === el.getAttribute('data-id'));
        activeRecent = r.id;
        openConversation(r.query, r.title, {animate:false});
      }));
  }

  function setNav(mode){
    document.querySelectorAll('#navAsk,#navLibrary').forEach(el=>el&&el.classList.remove('active'));
    const el = document.getElementById('nav'+mode.charAt(0).toUpperCase()+mode.slice(1));
    if(el) el.classList.add('active');
  }
  function setStrip(html){
    if(html){ tierStrip.innerHTML = html; tierStrip.hidden = false; }
    else tierStrip.hidden = true;
  }

  /* ============================================================
     Conversation
     ============================================================ */
  function openConversation(query, title, opts={}){
    clearTimers();
    const key = routeQuery(query);
    const a = Object.assign({}, ANSWERS[key], { query });
    current = { title: title || truncate(query,60), query };
    mainTitle.textContent = current.title;
    setNav('convo');
    if(opts.animate){ renderRetrieving(a); } else { renderAnswer(a); }
    if(!opts.animate) renderRail(a);
    renderRecents();
  }

  function renderRetrieving(a){
    setStrip(null);
    convoScroll.classList.remove('t3-bg');
    const stages = STAGES[a.tier] || STAGES[3];
    convo.innerHTML = `
      <div class="query-echo"><p>${esc(a.query)}</p></div>
      <div class="thinking"><span class="spinner"></span>Thinking…</div>
      <div class="retrieve-card">
        <h3>Finding grounded sources</h3>
        ${stages.map(s=>`<div class="rstep"><span class="dot"></span>${s.t}</div>`).join('')}
        <div class="progress-bar"></div>
      </div>
      <p class="retrieve-note">Usually 4–8 seconds · streaming as soon as the first line is ready</p>`;
    convoScroll.scrollTop = 0;
    railBody.innerHTML = `<div class="rail-note">Retrieving grounded sources…</div>`;
    railTitle.textContent = 'Sources';
    railMode.textContent = '…';

    const els = [...convo.querySelectorAll('.rstep')];
    let i = 0;
    const step = () => {
      if(i>0){ els[i-1].classList.remove('active'); els[i-1].classList.add('done');
               els[i-1].querySelector('.dot').innerHTML = svg(I.check,{w:9,sw:3.2}); }
      if(i < els.length){
        els[i].classList.add('active'); i++;
        timers.push(setTimeout(step, i===1?600:850));
      } else {
        timers.push(setTimeout(()=>{ renderAnswer(a); renderRail(a); }, 420));
      }
    };
    timers.push(setTimeout(step, 380));
  }

  function renderAnswer(a){
    if(a.tier === 3) return renderTier3(a);
    setStrip(null);
    convoScroll.classList.remove('t3-bg');
    const isWeb = a.tier === 2;
    const badge = isWeb
      ? `<span class="badge badge-t2">🌐 Grounded · Web allowlist <span class="t">Tier&nbsp;2</span></span>`
      : `<span class="badge badge-t1">✓ Grounded · Corpus <span class="t">Tier&nbsp;1</span></span>`;
    const g = a.group;
    const head = `<div class="src-head-l">${svg(isWeb?I.globe:I.file,{w:14,sw:1.9})}${g.label}</div><div class="src-head-r">${g.body}</div>`;
    const foot = g.kind==='gov'
      ? `<div class="src-issuer">${g.issuer}</div>
         <a class="src-title-link" data-cite="${g.citeId}">${g.titleLink}</a>
         <div class="src-cite">${g.cite}</div>`
      : `<a class="src-title-link">${g.titleLink} <span style="font-size:10px;">↗</span></a>
         <div class="src-cite">${g.cite}</div>`;

    let html = `
      <div class="query-echo"><p>${esc(a.query)}</p></div>
      ${isWeb ? `<div class="notice notice-blue">${svg(I.info,{w:11,stroke:'#3a5876'})}${a.notice}</div>`:''}
      <div class="answer-head">
        <div class="answer-meta">${badge}${a.stamp?`<span class="stamp">${a.stamp}</span>`:''}</div>
        <div class="finished">Finished thinking <span style="font-size:9px;">▾</span></div>
      </div>
      <div class="src-card ${isWeb?'web':''}">
        <div class="src-head">${head}</div>
        <div class="src-body">
          <div class="prose">${withPills(g.prose)}</div>
          <div class="src-foot">${foot}</div>
        </div>
      </div>
      <div class="act-row">
        ${svg(I.like,{w:16,sw:1.7,style:'cursor:pointer'})}
        ${svg(I.like,{w:16,sw:1.7,style:'transform:scaleY(-1);cursor:pointer'})}
        ${svg(I.copy,{w:16,sw:1.7,style:'cursor:pointer'})}
        <span class="spacer">${a.latestSource?`Latest source: ${a.latestSource}`:''}</span>
      </div>`;

    if(a.followups){
      html += `
      <div class="followups">
        <div class="block-title">${svg(I.list,{w:14})}Follow-up questions</div>
        ${a.followups.map(f=>`<div class="followup" data-q="${esc(f)}"><span>${f}</span><span class="chev">›</span></div>`).join('')}
      </div>`;
    }
    if(isWeb) html += `<div class="snapshot">${svg(I.clock,{w:11})}${a.snapshot}</div>`;
    html += `<div style="height:20px;"></div>`;
    convo.innerHTML = html;
    convoScroll.scrollTop = 0;
    wireConvo();
  }

  function renderTier3(a){
    convoScroll.classList.add('t3-bg');
    const withheld = !!a.notFound;
    setStrip(withheld
      ? `${svg(I.shield,{w:13,stroke:'#5a4b76'})}<span>High-stakes query — unverified answers are withheld</span>`
      : `${sparkle('#6a5a86',13)}<span>General model answer · no Indian-literature citation</span>`);

    const modelChip = (!withheld && a.model)
      ? `<span class="model-chip">${a.model}</span>` : '';

    convo.innerHTML = `
      <div class="query-echo" style="background:#fff;"><p>${esc(a.query)}</p></div>
      <div class="answer-head" style="margin-top:16px;">
        <div class="answer-meta">
          <span class="badge badge-t3">${sparkle('#6a5a86',11)}${withheld?'Not found · high-stakes':'General model'} <span class="t">Tier&nbsp;3</span></span>
          ${modelChip}
        </div>
        <div class="finished">Finished thinking <span style="font-size:9px;">▾</span></div>
      </div>
      <p class="t3-prose">${a.prose}</p>
      <div class="t3-warn">${a.warn}</div>
      <div class="act-row" style="margin-top:16px;">
        ${withheld?'':`
        ${svg(I.like,{w:16,sw:1.7,style:'cursor:pointer'})}
        ${svg(I.like,{w:16,sw:1.7,style:'transform:scaleY(-1);cursor:pointer'})}
        ${svg(I.copy,{w:16,sw:1.7,style:'cursor:pointer'})}`}
        <a class="suggest-src" id="suggestSrc">Suggest a source</a>
      </div>
      <div style="height:20px;"></div>`;
    convoScroll.scrollTop = 0;
    const sug = document.getElementById('suggestSrc');
    sug.addEventListener('click', () => {
      sug.textContent = '✓ Logged to the corpus-gap register — thank you';
      sug.classList.add('done');
    });
    wireConvo();
  }

  function wireConvo(){
    convo.querySelectorAll('.followup[data-q]').forEach(el =>
      el.addEventListener('click', () => submit(el.getAttribute('data-q'))));
    convo.querySelectorAll('[data-cite]').forEach(el =>
      el.addEventListener('click', () => flashRailCard(el.getAttribute('data-cite'))));
  }

  /* ============================================================
     Sources rail
     ============================================================ */
  function renderRail(a){
    if(a.tier === 3){
      railTitle.textContent = 'Sources · 0';
      railMode.textContent = a.notFound ? 'Withheld' : 'General model';
      railBody.innerHTML = `
        <div class="rail-t3-card">
          <div class="rail-t3-head">
            <span class="rail-t3-icon">${sparkle('#6a5a86',14)}</span>
            <span class="rail-t3-title">No grounded sources</span>
          </div>
          <p>${a.notFound
              ? 'This dosing/interaction question isn’t covered by the indexed Indian literature, so no unverified answer is shown.'
              : 'This question isn’t covered by the indexed Indian literature, so the answer comes from a frontier model.'}</p>
        </div>
        <div>
          <div class="rail-label">Sources checked</div>
          <div class="chip-row">${(a.sourcesChecked||[]).map(s=>`<span class="checked-chip">${esc(s)}</span>`).join('')}</div>
        </div>
        ${a.notFound?'':`
        <div>
          <div class="rail-label">Model</div>
          <div class="chip-row"><span class="model-chip">${sparkle('#6a5a86',9)}${esc(a.model||'Claude')}</span></div>
        </div>`}`;
      return;
    }
    if(a.tier === 2){
      railTitle.textContent = 'Sources · 1';
      railMode.textContent = 'Grounded';
      railBody.innerHTML = `
        <div class="rail-card web-card" data-cite="web">
          <div class="rail-card-head">
            <div class="rail-src blue">${svg('<circle cx="12" cy="12" r="9"/>',{w:7,sw:3,stroke:'#445f7a'})}ICMR.GOV.IN</div>
            <span class="rail-page">web page</span>
          </div>
          <div class="rail-card-body">
            <div class="rail-doc-title">${a.group.titleLink}</div>
            <div class="rail-doc-meta">icmr.gov.in · retrieved 18 Jul 2026</div>
            <button class="rail-open">Open source <span style="font-size:10px;">↗</span></button>
          </div>
        </div>
        <div class="rail-note">Web content is a snapshot we do not control. The retrieval date is stamped on the answer.</div>`;
      return;
    }
    const refs = a.references || [];
    railTitle.textContent = `Sources · ${refs.length}`;
    railMode.textContent = 'Grounded';
    railBody.innerHTML = refs.map((r,i)=>{
      const c = CITATIONS[r.cite];
      if(!c) return '';
      const pageLabel = c.page ? `p.${c.page}` : '';
      if(i === 0){
        return `
        <div class="rail-card featured" data-cite="${r.cite}">
          <div class="rail-card-head">
            <div class="rail-src">${svg('<circle cx="12" cy="12" r="9"/>',{w:7,sw:3,stroke:'#35694e'})}${c.body}</div>
            <span class="rail-page">${pageLabel}</span>
          </div>
          <div class="rail-card-body">
            <div class="rail-quote">${c.passageHtml}</div>
            <div class="rail-doc-title">${c.meta[0][1]}</div>
            <div class="rail-doc-meta">${c.body} · ${yearOf(c)} · open</div>
            <button class="rail-open">Open PDF at ${pageLabel} <span style="font-size:10px;">↗</span></button>
          </div>
        </div>`;
      }
      return `
        <div class="rail-card compact" data-cite="${r.cite}">
          <div class="rail-compact-head">
            <div class="rail-src ${c.body==='MoHFW'?'blue':''}">${svg('<circle cx="12" cy="12" r="9"/>',{w:7,sw:3,stroke:c.body==='MoHFW'?'#445f7a':'#35694e'})}${c.body}</div>
            <span class="chev">›</span>
          </div>
          <div class="rail-doc-title">${c.meta[0][1]}</div>
          <div class="rail-doc-meta">${c.body} · ${yearOf(c)} · ${pageLabel}</div>
        </div>`;
    }).join('') + `
      <div class="rail-note">Every grounded claim links to a passage here. Deep-links open the original PDF with the sentence highlighted.</div>`;

    railBody.querySelectorAll('.rail-card.compact').forEach(el =>
      el.addEventListener('click', () => promoteRailCard(a, el.getAttribute('data-cite'))));
  }

  function promoteRailCard(a, citeId){
    const refs = a.references.slice();
    refs.sort((x,y)=>(x.cite===citeId?-1:0)-(y.cite===citeId?-1:0));
    renderRail(Object.assign({}, a, {references:refs}));
    flashRailCard(citeId);
  }
  function flashRailCard(citeId){
    const card = railBody.querySelector(`.rail-card[data-cite="${citeId}"]`);
    if(!card) return;
    card.scrollIntoView({behavior:'smooth', block:'nearest'});
    card.classList.remove('flash');
    void card.offsetWidth;
    card.classList.add('flash');
    setTimeout(()=>card.classList.remove('flash'), 1200);
  }

  /* ============================================================
     Ask (App Ask canvas)
     ============================================================ */
  function renderAsk(){
    clearTimers();
    activeRecent = null; current = null;
    LIVE.convId = null;                     // New question = new conversation
    mainTitle.textContent = 'New question';
    setNav('ask'); setStrip(null);
    convoScroll.classList.remove('t3-bg');
    convo.innerHTML = `
      <div class="ask-state">
        <h2>Ask a question grounded<br>in Indian medical literature</h2>
        <div class="ask-sub">Every answer is traceable to ICMR, MoHFW, the NLEM, and peer-reviewed Indian journals.</div>
        <div class="home-privacy" style="margin-top:12px;">${svg(I.shield,{w:12,stroke:'#35694e'})}DPDP-conscious · do not enter patient-identifiable information</div>
        <div class="chips" style="margin-top:26px;">
          ${HOME.chips.map(c=>`<button class="chip" data-q="${esc(c.q)}">${svg(I[c.icon]||I.file,{w:13})}${c.label}</button>`).join('')}
        </div>
        <div class="section-label" style="margin-top:34px;text-align:left;">Try asking</div>
        <div class="suggests" style="margin-top:12px;text-align:left;">
          ${HOME.suggests.map(q=>`<button class="suggest" data-q="${esc(q)}"><span class="arrow">→</span>${q}</button>`).join('')}
        </div>
      </div>`;
    convoScroll.scrollTop = 0;
    railTitle.textContent = 'Sources';
    railMode.textContent = '—';
    railBody.innerHTML = `<div class="rail-note">Sources for your answer will appear here, with the exact cited passages.</div>`;
    renderRecents();
    convo.querySelectorAll('[data-q]').forEach(el =>
      el.addEventListener('click', () => submit(el.getAttribute('data-q'))));
    qinput.placeholder = 'Ask a clinical question…';
    qinput.focus();
  }

  /* ============================================================
     Library (D2: saved conversations only)
     ============================================================ */
  async function renderLibrary(){
    clearTimers();
    activeRecent = null; current = null;
    mainTitle.textContent = 'Library';
    setNav('library'); setStrip(null);
    convoScroll.classList.remove('t3-bg');
    let items;
    if(isLive()){
      try { items = await PRAMANA_API.get('/api/library'); } catch(e){ items = []; }
      items = items.map(it => ({ title: it.title, query: it.query, savedAt: it.saved_at, id: it.id }));
    } else {
      items = libRead();
    }
    convo.innerHTML = `
      <div class="page-title" style="margin-top:6px;">Library</div>
      <div class="page-lead">Conversations you saved with the <b style="font-weight:600;">Save</b> action. Saved answers keep their tier, citations, and dates.</div>
      ${items.length ? `
      <div class="lib-list">
        ${items.map((it,i)=>`
          <div class="lib-item" data-q="${esc(it.query)}" data-t="${esc(it.title)}">
            <div class="lib-main">
              <div class="lib-title">${esc(it.title)}</div>
              <div class="lib-meta">Saved ${esc(it.savedAt)}</div>
            </div>
            <button class="lib-remove" data-i="${i}" title="Remove from library">×</button>
          </div>`).join('')}
      </div>`
      : `
      <div class="lib-empty">
        ${svg(I.book,{w:20,sw:1.6,stroke:'#a5a29a'})}
        <div><b>Nothing saved yet.</b> Open a conversation and use <b>Save</b> in the top bar — it will appear here.</div>
      </div>`}`;
    convoScroll.scrollTop = 0;
    railTitle.textContent = 'Library';
    railMode.textContent = `${items.length} saved`;
    railBody.innerHTML = `<div class="rail-note">Saved conversations are private to your account and stored in-region (ap-south-1).</div>`;
    renderRecents();

    convo.querySelectorAll('.lib-item').forEach(el =>
      el.addEventListener('click', e => {
        if(e.target.classList.contains('lib-remove')) return;
        const query = el.getAttribute('data-q');
        if(isLive()){ LIVE.convId = null; askLive(query); }   // reopen = re-ask
        else openConversation(query, el.getAttribute('data-t'), {animate:false});
      }));
    convo.querySelectorAll('.lib-remove').forEach(el =>
      el.addEventListener('click', async () => {
        if(isLive()){
          const item = items[+el.getAttribute('data-i')];
          try { await PRAMANA_API.del('/api/library/' + item.id); } catch(e){}
        } else {
          const local = libRead(); local.splice(+el.getAttribute('data-i'),1); libWrite(local);
        }
        renderLibrary();
      }));
  }

  async function saveCurrent(){
    if(!current){ return; }
    if(isLive()){
      try {
        await PRAMANA_API.post('/api/library',
          { title: current.title, query: current.query, conversation_id: LIVE.convId });
        saveBtn.textContent = 'Saved ✓';
        setTimeout(()=>{ saveBtn.textContent = 'Save'; }, 1800);
      } catch(e){}
      return;
    }
    const items = libRead();
    if(items.some(it => it.query === current.query)){ saveBtn.textContent = 'Saved ✓'; return; }
    const d = new Date();
    items.unshift({ title: current.title, query: current.query,
      savedAt: `${d.getDate()} ${d.toLocaleString('en',{month:'short'})} ${d.getFullYear()}` });
    libWrite(items);
    saveBtn.textContent = 'Saved ✓';
    setTimeout(()=>{ saveBtn.textContent = 'Save'; }, 1800);
  }

  /* The Sources screen was removed from the v1 UI (product call, Jul 2026).
     The /api/sources endpoint and the admin allowlist remain untouched. */

  /* ============================================================
     LIVE mode — real answers from the orchestrator (SSE)
     ============================================================ */
  async function askLive(query){
    clearTimers();
    setNav('convo'); setStrip(null);
    convoScroll.classList.remove('t3-bg');
    current = { title: truncate(query,60), query };
    mainTitle.textContent = current.title;
    convo.innerHTML = `
      <div class="query-echo"><p>${esc(query)}</p></div>
      <div class="thinking"><span class="spinner"></span>Thinking…</div>
      <div class="retrieve-card">
        <h3>Finding grounded sources</h3>
        <div id="liveStages"></div>
        <div class="progress-bar"></div>
      </div>
      <p class="retrieve-note">Usually 4–8 seconds · answers stream as soon as they are ready</p>`;
    convoScroll.scrollTop = 0;
    railTitle.textContent = 'Sources'; railMode.textContent = '…';
    railBody.innerHTML = `<div class="rail-note">Searching allowlisted Indian domains…</div>`;
    renderRecents();

    const stagesEl = document.getElementById('liveStages');
    const addStage = label => {
      if(!stagesEl.isConnected) return;
      const prev = stagesEl.querySelector('.rstep.active');
      if(prev){ prev.classList.remove('active'); prev.classList.add('done');
                prev.querySelector('.dot').innerHTML = svg(I.check,{w:9,sw:3.2}); }
      const div = document.createElement('div');
      div.className = 'rstep active';
      div.innerHTML = `<span class="dot"></span>${esc(label)}`;
      stagesEl.appendChild(div);
    };

    try {
      await PRAMANA_API.ask(query, LIVE.convId, {
        stage:  d => addStage(d.label),
        error:  d => renderLiveError(query, d.detail),
        result: d => {
          LIVE.convId = d.conversation_id;
          LIVE.queryId = d.query_id;
          LIVE.recents = [{ title: truncate(query,40), query,
                            convId: d.conversation_id, result: d },
                          ...LIVE.recents.filter(r => r.convId !== d.conversation_id)].slice(0,8);
          renderLiveAnswer(d, query);
        },
      });
    } catch(e){ renderLiveError(query, e.message); }
  }

  function renderLiveError(query, detail){
    setStrip(null);
    const friendly = /anthropic_credentials|anthropic_sdk|authentication method|api_key/i.test(detail||'')
      ? 'The backend has no Anthropic credentials. Export ANTHROPIC_API_KEY and restart the server.'
      : /daily_cap/.test(detail||'') ? 'You have reached the daily query cap for the beta.'
      : 'Something went wrong answering this question.';
    convo.innerHTML = `
      <div class="query-echo"><p>${esc(query)}</p></div>
      <div class="notice notice-blue" style="margin-top:16px;">${svg(I.info,{w:11,stroke:'#3a5876'})}
        <span><b style="font-weight:600;">${esc(friendly)}</b><br>
        <span style="font-family:var(--mono);font-size:10px;">${esc(detail||'unknown')}</span></span></div>`;
    railTitle.textContent = 'Sources'; railMode.textContent = '—';
    railBody.innerHTML = `<div class="rail-note">No answer was produced.</div>`;
  }

  /* Render prose from contract segments: escaped text + one pill per citation. */
  function liveProse(res){
    return (res.segments||[]).map(seg => {
      const pills = (seg.citations||[]).map(i => {
        const c = res.citations[i];
        return `<span class="pill web" data-cite="c${i}"><span class="dotc"></span>${esc((c.domain||'web').toUpperCase())}</span>`;
      }).join('');
      return esc(seg.text).replace(/\n/g,'<br>') + pills;
    }).join(' ');
  }

  function renderLiveAnswer(res, query){
    clearTimers();
    setNav('convo');
    LIVE.queryId = res.query_id;
    current = { title: truncate(query,60), query };
    mainTitle.textContent = current.title;
    const withheld = res.tier === 3 && res.status === 'not_found';

    if(res.tier === 2){
      setStrip(null);
      convoScroll.classList.remove('t3-bg');
      const primary = res.citations[0] || {};
      convo.innerHTML = `
        <div class="query-echo"><p>${esc(query)}</p></div>
        <div class="answer-head">
          <div class="answer-meta">
            <span class="badge badge-t2">🌐 Grounded · Web allowlist <span class="t">Tier&nbsp;2</span></span>
            <span class="stamp">Answered ${esc(res.retrieved_at)}</span>
          </div>
        </div>
        <div class="src-card web">
          <div class="src-head">
            <div class="src-head-l">${svg(I.globe,{w:14,sw:1.9})}Web · allowlisted domain</div>
            <div class="src-head-r">${esc((primary.domain||'').toUpperCase())}</div>
          </div>
          <div class="src-body">
            <div class="prose">${liveProse(res)}</div>
            <div class="src-foot">
              <a class="src-title-link" href="${esc(primary.url||'#')}" target="_blank" rel="noopener">${esc(primary.title||primary.url||'Source')} <span style="font-size:10px;">↗</span></a>
              <div class="src-cite">${esc(primary.domain||'')} · web page</div>
            </div>
          </div>
        </div>
        <div class="act-row">
          <span class="act" data-fb="up">${svg(I.like,{w:16,sw:1.7})}</span>
          <span class="act" data-fb="down">${svg(I.like,{w:16,sw:1.7,style:'transform:scaleY(-1)'})}</span>
          <span class="act" data-copy>${svg(I.copy,{w:16,sw:1.7})}</span>
          <span class="spacer">${esc(res.model_used||'')} · ${res.latency_ms} ms</span>
        </div>
        ${res.followups && res.followups.length ? `
        <div class="followups">
          <div class="block-title">${svg(I.list,{w:14})}Follow-up questions</div>
          ${res.followups.map(f=>`<div class="followup" data-q="${esc(f)}"><span>${esc(f)}</span><span class="chev">›</span></div>`).join('')}
        </div>`:''}
        <div class="snapshot">${svg(I.clock,{w:11})}Retrieved from allowlisted domains on ${esc(res.retrieved_at)} · web content is a snapshot we do not control</div>
        <div style="height:20px;"></div>`;
    } else {
      convoScroll.classList.add('t3-bg');
      setStrip(withheld
        ? `${svg(I.shield,{w:13,stroke:'#5a4b76'})}<span>High-stakes query — unverified answers are withheld</span>`
        : `${sparkle('#6a5a86',13)}<span>General model answer · no Indian-literature citation</span>`);
      convo.innerHTML = `
        <div class="query-echo" style="background:#fff;"><p>${esc(query)}</p></div>
        <div class="answer-head" style="margin-top:16px;">
          <div class="answer-meta">
            <span class="badge badge-t3">${sparkle('#6a5a86',11)}${withheld?'Not found · high-stakes':'General model'} <span class="t">Tier&nbsp;3</span></span>
            ${!withheld && res.model_used ? `<span class="model-chip">${esc(res.model_used)}</span>`:''}
          </div>
        </div>
        <p class="t3-prose">${esc(res.answer_text||'').replace(/\n/g,'<br>')}</p>
        <div class="t3-warn">${withheld
          ? 'This query was logged to the corpus-gap register. For dosing and interaction questions Pramana only answers from a grounded Indian source.'
          : 'This answer is <b style="font-weight:600;">not grounded in Indian medical literature.</b> It carries no citation and has not passed the groundedness check. Verify against a primary source before any clinical use.'}</div>
        <div class="act-row" style="margin-top:16px;">
          ${withheld?'':`
          <span class="act" data-fb="up">${svg(I.like,{w:16,sw:1.7})}</span>
          <span class="act" data-fb="down">${svg(I.like,{w:16,sw:1.7,style:'transform:scaleY(-1)'})}</span>
          <span class="act" data-copy>${svg(I.copy,{w:16,sw:1.7})}</span>`}
          <a class="suggest-src" id="suggestSrc">Suggest a source</a>
        </div>
        <div style="height:20px;"></div>`;
      const sug = document.getElementById('suggestSrc');
      sug.addEventListener('click', async () => {
        try { await PRAMANA_API.post('/api/suggest-source', { query_id: res.query_id }); } catch(e){}
        sug.textContent = '✓ Logged to the corpus-gap register — thank you';
        sug.classList.add('done');
      });
    }
    convoScroll.scrollTop = 0;
    renderLiveRail(res);
    renderRecents();

    convo.querySelectorAll('.followup[data-q]').forEach(el =>
      el.addEventListener('click', () => submit(el.getAttribute('data-q'))));
    convo.querySelectorAll('.pill[data-cite]').forEach(el =>
      el.addEventListener('click', () => flashRailCard(el.getAttribute('data-cite'))));
    convo.querySelectorAll('[data-fb]').forEach(el =>
      el.addEventListener('click', async () => {
        try { await PRAMANA_API.post('/api/feedback',
          { query_id: res.query_id, feedback: el.getAttribute('data-fb') }); } catch(e){ return; }
        el.style.color = 'var(--t1)';
      }));
    const copyEl = convo.querySelector('[data-copy]');
    if(copyEl) copyEl.addEventListener('click', () => {
      try { navigator.clipboard.writeText(res.answer_text||''); copyEl.style.color='var(--t1)'; } catch(e){}
    });
  }

  function renderLiveRail(res){
    if(res.tier === 2 && res.citations.length){
      railTitle.textContent = `Sources · ${res.citations.length}`;
      railMode.textContent = 'Grounded';
      railBody.innerHTML = res.citations.map((c,i)=> i===0 ? `
        <div class="rail-card web-card featured" data-cite="c${i}">
          <div class="rail-card-head">
            <div class="rail-src blue">${svg('<circle cx="12" cy="12" r="9"/>',{w:7,sw:3,stroke:'#445f7a'})}${esc((c.domain||'').toUpperCase())}</div>
            <span class="rail-page">web page</span>
          </div>
          <div class="rail-card-body">
            ${c.cited_text?`<div class="rail-quote">“${esc(c.cited_text.slice(0,220))}${c.cited_text.length>220?'…':''}”</div>`:''}
            <div class="rail-doc-title">${esc(c.title||c.url)}</div>
            <div class="rail-doc-meta">${esc(c.domain||'')} · retrieved ${esc(res.retrieved_at)}</div>
            <a class="rail-open" href="${esc(c.url)}" target="_blank" rel="noopener" style="text-decoration:none;">Open source <span style="font-size:10px;">↗</span></a>
          </div>
        </div>` : `
        <div class="rail-card web-card compact" data-cite="c${i}">
          <div class="rail-compact-head">
            <div class="rail-src blue">${svg('<circle cx="12" cy="12" r="9"/>',{w:7,sw:3,stroke:'#445f7a'})}${esc((c.domain||'').toUpperCase())}</div>
            <a href="${esc(c.url)}" target="_blank" rel="noopener" class="chev" style="text-decoration:none;">↗</a>
          </div>
          <div class="rail-doc-title">${esc(c.title||c.url)}</div>
          ${c.cited_text?`<div class="rail-doc-meta">“${esc(c.cited_text.slice(0,110))}…”</div>`:''}
        </div>`).join('') + `
        <div class="rail-note">Every grounded claim links to a passage here. Links open the original page.</div>`;
      return;
    }
    const withheld = res.status === 'not_found';
    railTitle.textContent = 'Sources · 0';
    railMode.textContent = withheld ? 'Withheld' : 'General model';
    railBody.innerHTML = `
      <div class="rail-t3-card">
        <div class="rail-t3-head">
          <span class="rail-t3-icon">${sparkle('#6a5a86',14)}</span>
          <span class="rail-t3-title">No grounded sources</span>
        </div>
        <p>${withheld
            ? 'This dosing/interaction question isn’t covered by the allowlisted Indian sources, so no unverified answer is shown.'
            : 'The allowlisted Indian sources didn’t cover this question, so the answer comes from a general model.'}</p>
      </div>
      <div>
        <div class="rail-label">Sources checked</div>
        <div class="chip-row">${(res.sources_searched||[]).map(s=>`<span class="checked-chip">${esc(s.replace(/^web:/,''))}</span>`).join('')}</div>
      </div>
      ${withheld || !res.model_used ? '' : `
      <div>
        <div class="rail-label">Model</div>
        <div class="chip-row"><span class="model-chip">${sparkle('#6a5a86',9)}${esc(res.model_used)}</span></div>
      </div>`}`;
  }

  /* ============================================================
     flow glue
     ============================================================ */
  function submit(query){
    query = (query||'').trim();
    if(!query) return;
    qinput.value = '';
    qinput.placeholder = 'Ask a follow-up…';
    if(isLive()){ askLive(query); return; }
    const match = RECENTS.find(r => routeQuery(r.query) === routeQuery(query));
    activeRecent = match ? match.id : null;
    current = { title: truncate(query,60), query };
    openConversation(query, current.title, {animate:true});
  }

  qform.addEventListener('submit', e => { e.preventDefault(); submit(qinput.value); });
  document.getElementById('newQBtn').addEventListener('click', renderAsk);
  document.getElementById('navAsk').addEventListener('click', renderAsk);
  document.getElementById('navLibrary').addEventListener('click', renderLibrary);
  document.getElementById('brandBtn').addEventListener('click', renderAsk);
  saveBtn.addEventListener('click', saveCurrent);

  /* ---------- signed-in identity ---------- */
  (function renderMe(){
    const me = PRAMANA_AUTH.current();
    if(!me) return;
    document.getElementById('meAvatar').textContent = PRAMANA_AUTH.initials(me.name);
    document.getElementById('meName').textContent  = me.name;
    document.getElementById('meMeta').textContent  = 'Beta · ' + me.email;
    // Admins and editors get a way into the configuration portal.
    if(PRAMANA_AUTH.can('editor')){
      const nav = document.querySelector('.side-nav');
      const b = document.createElement('button');
      b.className = 'nav-item';
      b.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8M4.6 7a1.6 1.6 0 0 0 .3 1.8"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>Admin`;
      b.addEventListener('click', () => { window.location.href = 'admin.html'; });
      nav.appendChild(b);
    }
  })();
  document.getElementById('signOutBtn').addEventListener('click', () =>
    PRAMANA_AUTH.signOut('login.html?signedout=1'));

  /* ---------- utils ---------- */
  function esc(s){ return String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }
  function truncate(s,n){ return s.length>n ? s.slice(0,n-1)+'…' : s; }
  function yearOf(c){ const p=c.meta.find(m=>m[0]==='Published'); return p ? String(p[1]).replace(/^\D*/,'').slice(-4) : ''; }
  function withPills(html){
    return html.replace(/\{\{(\w+)\}\}/g, (_, key) => {
      const p = PILL[key]; if(!p) return '';
      const citeAttr = p.cite ? ` data-cite="${p.cite}"` : ' data-cite="web"';
      return `<span class="pill ${p.cls}"${citeAttr}><span class="dotc"></span>${p.label}</span>`;
    });
  }

  // boot — live mode starts at Ask (no seeded conversations exist)
  (async () => {
    await PRAMANA_API.ready;
    if(isLive()) renderAsk();
    else openConversation(RECENTS[0].query, RECENTS[0].title, {animate:false});
  })();
})();
