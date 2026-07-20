/* ============================================================
   Pramana — flow controller
   State machine over the 7 canvas screens:
   consent → home → retrieving → answer(tier 1/2/3) → citation
   ============================================================ */
(function(){
  'use strict';

  const viewport   = document.getElementById('viewport');
  const composer   = document.getElementById('composer');
  const qform      = document.getElementById('qform');
  const qinput     = document.getElementById('qinput');
  const topbarRight= document.getElementById('topbarRight');
  const overlay    = document.getElementById('overlay');
  const citePanel  = document.getElementById('citationPanel');
  const newChatBtn = document.getElementById('newChatBtn');

  /* ---------- tiny SVG icon set ---------- */
  const I = {
    shield:'<path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    shieldSm:'<path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
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
    tick:'✓',
  };
  const svg = (path, o={}) =>
    `<svg width="${o.w||13}" height="${o.h||o.w||13}" viewBox="0 0 24 24" fill="${o.fill||'none'}" stroke="${o.stroke||'currentColor'}" stroke-width="${o.sw||2}" ${o.style?`style="${o.style}"`:''}>${path}</svg>`;
  const sparkle = (fill='#6a5a86',w=12)=>`<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="${fill}"><path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"/></svg>`;

  /* ---------- state ---------- */
  let state = 'consent';
  let timers = [];
  const clearTimers = () => { timers.forEach(clearTimeout); timers = []; };

  /* ---------- render helpers ---------- */
  function setComposer(mode){
    // mode: 'hidden' | 'home' | 'answer'
    if(mode === 'hidden'){ composer.hidden = true; return; }
    composer.hidden = false;
    qinput.value = '';
    if(mode === 'home'){
      qinput.placeholder = 'Ask a clinical question…';
      qform.classList.add('hero');
    } else {
      qinput.placeholder = 'Ask a follow-up…';
      qform.classList.remove('hero');
    }
  }
  const show = (html, cls='') => { viewport.innerHTML = `<section class="screen ${cls}">${html}</section>`; viewport.scrollTop = 0; };

  /* ============================================================
     SCREEN 1 — First run / consent
     ============================================================ */
  function screenConsent(){
    state = 'consent';
    setComposer('hidden');
    topbarRight.hidden = true;
    show(`
      <div class="consent">
        <div class="consent-badge">${svg(I.shield,{w:22,sw:1.7})}</div>
        <h1>Before you begin</h1>
        <p class="consent-lead">Pramana is a <b>literature reference tool</b> for healthcare professionals. It surfaces answers grounded in Indian medical literature with sentence-level citations. It is <b>not a diagnostic or treatment-decision tool</b> and does not replace clinical judgment.</p>
        <ul class="consent-list">
          <li><span class="tick">${I.tick}</span>For English-literate healthcare professionals</li>
          <li><span class="tick">${I.tick}</span>Every claim links to its exact source passage</li>
          <li><span class="tick">${I.tick}</span>Do not enter patient-identifiable information</li>
        </ul>
        <div class="consent-check" id="consentCheck" role="checkbox" aria-checked="false" tabindex="0">
          <span class="checkbox">${svg(I.check,{w:12,sw:3})}</span>
          I understand and accept these terms
        </div>
        <button class="btn btn-dark" id="continueBtn" disabled>Continue to Pramana</button>
      </div>`);

    const check = document.getElementById('consentCheck');
    const cont  = document.getElementById('continueBtn');
    const toggle = () => {
      const on = check.getAttribute('aria-checked') !== 'true';
      check.setAttribute('aria-checked', String(on));
      cont.disabled = !on;
    };
    check.addEventListener('click', toggle);
    check.addEventListener('keydown', e => { if(e.key===' '||e.key==='Enter'){ e.preventDefault(); toggle(); }});
    cont.addEventListener('click', () => { if(!cont.disabled) screenHome(); });
  }

  /* ============================================================
     SCREEN 2 — Empty home
     ============================================================ */
  function screenHome(){
    state = 'home';
    topbarRight.hidden = true;
    const chips = HOME.chips.map((c,i)=>
      `<button class="chip" data-q="${esc(c.q)}">${svg(I[c.icon],{w:12})}${c.label}</button>`).join('');
    const suggests = HOME.suggests.map(q=>
      `<button class="suggest" data-q="${esc(q)}"><span class="arrow">→</span>${q}</button>`).join('');
    show(`
      <div class="home-hero">
        <h2>Ask a question grounded<br>in Indian medical literature</h2>
        <div class="home-privacy">${svg(I.shieldSm,{w:12,stroke:'#35694e'})}DPDP-conscious · no patient-identifiable information</div>
      </div>
      <div class="chips">${chips}</div>
      <div class="section-label">Try asking</div>
      <div class="suggests">${suggests}</div>
      <div class="home-foot">Grounded in 50–200 curated Indian sources · ICMR · MoHFW · NLEM · open-access journals</div>
    `);
    setComposer('home');
    qinput.focus();
    viewport.querySelectorAll('[data-q]').forEach(el =>
      el.addEventListener('click', () => submit(el.getAttribute('data-q'))));
  }

  /* ============================================================
     SCREEN 3 — Retrieving (staged progress)
     ============================================================ */
  function screenRetrieving(query, answerKey){
    state = 'retrieving';
    topbarRight.hidden = false;
    setComposer('hidden');
    const tier = ANSWERS[answerKey].tier;
    const stages = STAGES[tier];
    const rows = stages.map((s,i)=>
      `<div class="rstep" data-i="${i}"><span class="dot"></span>${s.t}</div>`).join('');
    show(`
      <div class="query-echo"><p>${esc(query)}</p></div>
      <div class="thinking"><span class="spinner"></span>Thinking…</div>
      <div class="retrieve-card">
        <h3>Finding grounded sources</h3>
        ${rows}
        <div class="progress-bar"></div>
      </div>
      <p class="retrieve-note">Usually 4–8 seconds · streaming as soon as the first line is ready</p>
    `);

    // choreograph the stages
    const els = [...viewport.querySelectorAll('.rstep')];
    let i = 0;
    const step = () => {
      if(i>0){ els[i-1].classList.remove('active'); els[i-1].classList.add('done');
               els[i-1].querySelector('.dot').innerHTML = svg(I.check,{w:9,sw:3.2}); }
      if(i < els.length){
        els[i].classList.add('active');
        i++;
        timers.push(setTimeout(step, i===1?650:900));
      } else {
        timers.push(setTimeout(()=>screenAnswer(answerKey), 480));
      }
    };
    timers.push(setTimeout(step, 420));
  }

  /* ============================================================
     SCREENS 4 / 6 / 7 — Answers by tier
     ============================================================ */
  function screenAnswer(key){
    state = 'answer';
    clearTimers();
    topbarRight.hidden = false;
    const a = ANSWERS[key];
    if(a.tier === 3) return renderTier3(a);
    return renderGrounded(a);
  }

  // Tier 1 (corpus) & Tier 2 (web) share the source-grouped surface.
  function renderGrounded(a){
    const isWeb = a.tier === 2;
    const badge = isWeb
      ? `<span class="badge badge-t2">🌐 Grounded · Web allowlist <span class="t">Tier&nbsp;2</span></span>`
      : `<span class="badge badge-t1">✓ Grounded · Corpus <span class="t">Tier&nbsp;1</span></span>`;

    const g = a.group;
    const head = isWeb
      ? `<div class="src-head-l">${svg(I.globe,{w:14,sw:1.9})}${g.label}</div><div class="src-head-r">${g.body}</div>`
      : `<div class="src-head-l">${svg(I.file,{w:14,sw:1.9})}${g.label}</div><div class="src-head-r">${g.body}</div>`;

    const foot = g.kind==='gov'
      ? `<div class="src-issuer">${g.issuer}</div>
         <a class="src-title-link" data-cite="${g.citeId}">${g.titleLink}</a>
         <div class="src-cite">${g.cite}</div>`
      : `<a class="src-title-link" ${g.external?'':''}>${g.titleLink}${g.external?' <span style="font-size:10px;">↗</span>':''}</a>
         <div class="src-cite">${g.cite}</div>`;

    let html = `
      <div class="query-echo"><p>${esc(a.query)}</p></div>
      ${isWeb ? `<div class="notice notice-blue">${svg(I.info,{w:11,stroke:'#3a5876'})}${a.notice}</div>`:''}
      <div class="answer-head">
        <div class="answer-meta">${badge}${a.stamp?`<span class="stamp">${a.stamp}</span>`:''}</div>
        ${!isWeb?`<div class="finished">Finished thinking <span style="font-size:9px;">▾</span></div>`:''}
      </div>
      <div class="src-card ${isWeb?'web':''}">
        <div class="src-head">${head}</div>
        <div class="src-body">
          <div class="prose">${withPills(g.prose)}</div>
          <div class="src-foot">${foot}</div>
        </div>
      </div>`;

    if(!isWeb){
      html += `
      <div class="act-row">
        ${svg(I.like,{w:15,sw:1.7,style:'cursor:pointer'})}
        ${svg(I.like,{w:15,sw:1.7,style:'transform:scaleY(-1);cursor:pointer'})}
        ${svg(I.copy,{w:15,sw:1.7,style:'cursor:pointer'})}
        <span class="spacer">Latest source: ${a.latestSource}</span>
      </div>
      <div class="block">
        <div class="block-title">${svg(I.list,{w:13})}References</div>
        ${a.references.map(r=>`
          <div class="ref"><span style="color:var(--ink)">${r.n}. </span><a data-cite="${r.cite}">${r.title}</a>
            <div class="ref-meta">${r.meta} <span class="tag">${r.tag}</span></div></div>`).join('')}
      </div>
      <div class="followups">
        <div class="block-title">${svg(I.list,{w:13})}Follow-up questions</div>
        ${a.followups.map(f=>`<div class="followup" data-q="${esc(f)}"><span>${f}</span><span class="chev">›</span></div>`).join('')}
      </div>`;
    } else {
      html += `<div class="snapshot">${svg(I.clock,{w:11})}${a.snapshot}</div>`;
    }

    show(html);
    setComposer('answer');
    wireAnswer();
  }

  function renderTier3(a){
    show(`
      <div class="t3-banner">${sparkle('#6a5a86',13)}<span>General model answer · no Indian-literature citation</span></div>
      <div class="query-echo" style="margin-top:16px"><p>${esc(a.query)}</p></div>
      <div style="margin-top:14px">
        <span class="badge badge-t3">${sparkle('#6a5a86',11)}General model · Claude <span class="t">Tier&nbsp;3</span></span>
      </div>
      <p class="t3-prose">${a.prose}</p>
      <div class="t3-warn">${a.warn}</div>
      <div class="t3-actions">
        <button class="btn btn-ghost">Copy answer</button>
        <button class="btn btn-ghost">Suggest a source</button>
      </div>
    `, 't3');
    setComposer('answer');
    wireAnswer();
  }

  function wireAnswer(){
    viewport.querySelectorAll('[data-cite]').forEach(el =>
      el.addEventListener('click', () => openCitation(el.getAttribute('data-cite'))));
    viewport.querySelectorAll('.pill[data-cite]').forEach(el =>
      el.addEventListener('click', () => openCitation(el.getAttribute('data-cite'))));
    viewport.querySelectorAll('.followup[data-q]').forEach(el =>
      el.addEventListener('click', () => submit(el.getAttribute('data-q'))));
  }

  /* ============================================================
     SCREEN 5 — Citation card (overlay)
     ============================================================ */
  function openCitation(id){
    const c = CITATIONS[id];
    if(!c) return;
    citePanel.innerHTML = `
      <div class="cite-top">
        <div class="cite-top-l">
          <button class="cite-back" data-close aria-label="Back">${svg('<path d="M15 18l-6-6 6-6"/>',{w:18,sw:1.8})}</button>
          Citation <span class="badge badge-t1" style="padding:1px 6px 1px 5px;font-size:9px;"><span class="dotc" style="width:7px;height:7px;"></span>${c.body}</span>
        </div>
        <button class="cite-close" data-close aria-label="Close">×</button>
      </div>
      <div class="cite-body">
        <div class="verified-chip">${I.tick} Verbatim from source · groundedness verified</div>
        <div class="cite-eyebrow">Cited passage</div>
        <div class="cite-quote">${c.passageHtml}</div>
        <dl class="cite-grid">
          ${c.meta.map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('')}
          <dt>Source ID</dt><dd class="mono">${c.sourceId}</dd>
        </dl>
        <div class="cite-actions">
          <button class="btn btn-dark">Open PDF at p.${c.page} <span style="font-size:11px;">↗</span></button>
          <button class="btn btn-ghost">Copy</button>
        </div>
        <div class="cite-hint">${svg(I.info,{w:12,stroke:'#9a9892'})}The deep-link opens the original PDF and highlights this passage on the page, so you can verify it in context.</div>
      </div>`;
    overlay.hidden = false;
    citePanel.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', closeCitation));
  }
  function closeCitation(){ overlay.hidden = true; }
  overlay.querySelector('.overlay-scrim').addEventListener('click', closeCitation);
  document.addEventListener('keydown', e => { if(e.key==='Escape' && !overlay.hidden) closeCitation(); });

  /* ============================================================
     flow glue
     ============================================================ */
  function submit(query){
    query = (query||'').trim();
    if(!query) return;
    closeCitation();
    const key = routeQuery(query);
    // echo the user's own wording, but keep canonical query for known routes
    const a = ANSWERS[key];
    const echoed = Object.assign({}, a, { query });
    ANSWERS['_live'] = echoed;
    screenRetrieving(query, '_live');
  }

  qform.addEventListener('submit', e => { e.preventDefault(); submit(qinput.value); });
  newChatBtn.addEventListener('click', () => { clearTimers(); closeCitation(); screenHome(); });

  /* ---------- utils ---------- */
  function esc(s){ return String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }
  function withPills(html){
    return html.replace(/\{\{(\w+)\}\}/g, (_, key) => {
      const p = PILL[key]; if(!p) return '';
      const citeAttr = p.cite ? ` data-cite="${p.cite}"` : '';
      return `<span class="pill ${p.cls}"${citeAttr}><span class="dotc"></span>${p.label}</span>`;
    });
  }

  // boot
  screenConsent();
})();
