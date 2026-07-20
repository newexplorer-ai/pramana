/* ============================================================
   Pramana — admin portal controller (Admin Portal canvas)
   Four views: allowlist · config · keys · audit.
   Mutations (toggle, add domain, rotate) append audit rows,
   mirroring the Postgres-trigger audit design read-only in v1.
   ============================================================ */
(function(){
  'use strict';

  const navEl   = document.getElementById('adminNav');
  const titleEl = document.getElementById('adminTitle');
  const subEl   = document.getElementById('adminSub');
  const viewEl  = document.getElementById('adminView');
  const scroll  = document.getElementById('adminScroll');

  /* ---------- icons ---------- */
  const ICONS = {
    allowlist:'<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M6 3v16"/>',
    config:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 7"/>',
    keys:'<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9 2 2M16 7l2 2"/>',
    audit:'<path d="M9 5h9v14H6V5h3z"/><path d="M9 3h6v4H9zM9 11h6M9 15h4"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    search:'<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
    warn:'<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    rotate:'<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  };
  const svg = (name,o={}) =>
    `<svg width="${o.w||15}" height="${o.h||o.w||15}" viewBox="0 0 24 24" fill="none" stroke="${o.stroke||'currentColor'}" stroke-width="${o.sw||1.8}" ${o.style?`style="${o.style}"`:''}>${ICONS[name]}</svg>`;

  /* ---------- state (content from the canvas logic spec) ---------- */
  const state = {
    view:'allowlist',
    search:'',
    domains:[
      { domain:'icmr.gov.in',          note:'Indian Council of Medical Research — apex national research & guideline body.', by:'Dr. A. Rao',   date:'12 Jun 2026', on:true  },
      { domain:'main.mohfw.gov.in',    note:'Ministry of Health & Family Welfare — official policy & STGs.',                 by:'Dr. A. Rao',   date:'12 Jun 2026', on:true  },
      { domain:'ijmr.org.in',          note:'Indian Journal of Medical Research — ICMR peer-reviewed journal.',              by:'Dr. S. Menon', date:'14 Jun 2026', on:true  },
      { domain:'nmji.in',              note:'National Medical Journal of India — peer-reviewed, AIIMS-affiliated.',          by:'Dr. S. Menon', date:'14 Jun 2026', on:true  },
      { domain:'indianpediatrics.net', note:'Indian Pediatrics — IAP official journal.',                                     by:'Dr. S. Menon', date:'20 Jun 2026', on:true  },
      { domain:'cdsco.gov.in',         note:'Central Drugs Standard Control Organisation — drug approvals & safety.',        by:'Dr. A. Rao',   date:'02 Jul 2026', on:false },
    ],
    config:[
      { key:'model.generation',       value:'claude-sonnet-4.5', def:'claude-sonnet-4', desc:'Model ID for Tier 1/2/3 generation.',     who:'A. Rao', when:'18 Jul 2026', critical:true  },
      { key:'model.judge',            value:'claude-haiku-4',    def:'claude-haiku-4',  desc:'Model for the groundedness check.',        who:'A. Rao', when:'18 Jul 2026', critical:false },
      { key:'retrieval.threshold',    value:'0.78',              def:'0.75',            desc:'Tier 1 vs Tier 2 routing (cosine).',       who:'A. Rao', when:'19 Jul 2026', critical:false },
      { key:'retrieval.min_chunks',   value:'2',                 def:'2',               desc:'Stray-match guard.',                       who:'system', when:'default',     critical:false },
      { key:'retrieval.top_k',        value:'8',                 def:'8',               desc:'Chunks retrieved per query.',              who:'system', when:'default',     critical:false },
      { key:'websearch.max_uses',     value:'3',                 def:'5',               desc:'Tier 2 search cap per query.',             who:'A. Rao', when:'15 Jul 2026', critical:false },
      { key:'cost.per_query_ceiling', value:'$0.12',             def:'$0.15',           desc:'Budget guardrail per query.',              who:'A. Rao', when:'15 Jul 2026', critical:false },
      { key:'cost.daily_user_cap',    value:'40',                def:'50',              desc:'Per-doctor query cap per day.',            who:'A. Rao', when:'15 Jul 2026', critical:false },
      { key:'context.max_turns',      value:'6',                 def:'6',               desc:'Conversation depth resent per request.',   who:'system', when:'default',     critical:false },
    ],
    keys:[
      { provider:'Anthropic', use:'Generation + groundedness judge', hint:'sk-ant-··········a91f', rotated:'02 Jul 2026' },
      { provider:'Voyage AI', use:'Embeddings (retrieval)',          hint:'pa-··········7c20',     rotated:'11 Jun 2026' },
    ],
    audit:[
      { actor:'A. Rao',   action:'update',  change:'model.generation: sonnet-4 → sonnet-4.5',   when:'18 Jul, 14:22' },
      { actor:'A. Rao',   action:'update',  change:'retrieval.threshold: 0.75 → 0.78',          when:'19 Jul, 09:10' },
      { actor:'A. Rao',   action:'disable', change:'domain cdsco.gov.in → enabled:false',       when:'19 Jul, 09:40' },
      { actor:'S. Menon', action:'create',  change:'domain indianpediatrics.net added',         when:'20 Jun, 16:05' },
      { actor:'A. Rao',   action:'rotate',  change:'key anthropic rotated (value redacted)',    when:'02 Jul, 11:30' },
      { actor:'S. Menon', action:'create',  change:'domain nmji.in added',                      when:'14 Jun, 10:12' },
    ],
  };

  const TITLES = {
    allowlist:['Allowed websites','Tier 2 citation allowlist'],
    config:['Models & parameters','Runtime config-as-data'],
    keys:['API keys','Provider secrets & rotation'],
    audit:['Audit log','All configuration mutations'],
  };

  /* Audit rows for new mutations, stamped with the current time. */
  function logAudit(action, change){
    const d = new Date();
    const when = `${d.getDate()} ${d.toLocaleString('en',{month:'short'})}, ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    state.audit.unshift({ actor:'A. Rao', action, change, when });
  }
  function today(){
    const d = new Date();
    return `${d.getDate()} ${d.toLocaleString('en',{month:'short'})} ${d.getFullYear()}`;
  }

  /* ============================================================
     nav
     ============================================================ */
  function renderNav(){
    const items = [
      ['allowlist','Allowed websites', String(state.domains.length)],
      ['config','Models & config',''],
      ['keys','API keys',''],
      ['audit','Audit log',''],
    ];
    navEl.innerHTML = items.map(([id,label,count])=>`
      <button class="nav-item spread ${state.view===id?'active':''}" data-view="${id}">
        <span class="nav-l">${svg(id)}${label}</span>
        ${count?`<span class="nav-count">${count}</span>`:''}
      </button>`).join('');
    navEl.querySelectorAll('[data-view]').forEach(el =>
      el.addEventListener('click', () => { state.view = el.getAttribute('data-view'); state.search=''; render(); }));
  }

  /* ============================================================
     views
     ============================================================ */
  function render(){
    renderNav();
    const [t,s] = TITLES[state.view];
    titleEl.textContent = t; subEl.textContent = s;
    ({allowlist:renderAllowlist, config:renderConfig, keys:renderKeys, audit:renderAudit})[state.view]();
    scroll.scrollTop = 0;
  }

  /* ---------- allowlist ---------- */
  function renderAllowlist(){
    const q = state.search.trim().toLowerCase();
    const rows = state.domains.filter(r => !q || r.domain.toLowerCase().includes(q) || r.note.toLowerCase().includes(q));
    viewEl.innerHTML = `
      <div class="page-title">Allowed websites</div>
      <div class="page-lead">Single source of truth for the <code>allowed_domains</code> parameter on every Tier&nbsp;2 web-search call. This list is the entire quality gate on what the product may cite from the web.</div>

      <form class="add-form" id="addForm" autocomplete="off">
        <div class="field f-domain">
          <span class="field-label">Domain</span>
          <input class="mono" id="fDomain" type="text" placeholder="e.g. nhp.gov.in" spellcheck="false">
        </div>
        <div class="field f-note">
          <span class="field-label">Trust note <span class="opt">— required</span></span>
          <input id="fNote" type="text" placeholder="Why this source is authoritative">
        </div>
        <button class="add-btn" type="submit">${svg('plus',{w:13,sw:2.2,stroke:'#fff'})}Add domain</button>
      </form>

      <div class="list-meta">
        <div class="list-meta-note">Showing the effective list <b>exactly as sent to the API</b> — enabled domains only are live.</div>
        <div class="search-box">${svg('search',{w:12,sw:2,stroke:'#a5a29a'})}<input id="fSearch" type="text" placeholder="Search" value="${esc(state.search)}"></div>
      </div>

      <div class="tbl">
        <div class="tbl-head cols-domains"><div>Domain</div><div>Trust note</div><div class="cell-by-wrap">Added by</div><div style="text-align:right;">Enabled</div></div>
        ${rows.length ? rows.map(r=>{
          const i = state.domains.indexOf(r);
          return `
          <div class="tbl-row cols-domains ${r.on?'':'dim'}">
            <div class="cell-domain">${esc(r.domain)}</div>
            <div class="cell-note">${esc(r.note)}</div>
            <div class="cell-by-wrap"><div class="cell-by">${esc(r.by)}</div><div class="cell-date">${esc(r.date)}</div></div>
            <div class="cell-end"><button class="toggle ${r.on?'on':''}" data-i="${i}" role="switch" aria-checked="${r.on}" aria-label="Enable ${esc(r.domain)}"><span class="knob"></span></button></div>
          </div>`;}).join('')
        : `<div class="tbl-empty">No domains match “${esc(state.search)}”.</div>`}
      </div>`;

    viewEl.querySelectorAll('.toggle').forEach(el =>
      el.addEventListener('click', () => {
        const r = state.domains[+el.getAttribute('data-i')];
        r.on = !r.on;
        logAudit(r.on?'enable':'disable', `domain ${r.domain} → enabled:${r.on}`);
        render();
      }));

    const search = viewEl.querySelector('#fSearch');
    search.addEventListener('input', () => {
      state.search = search.value;
      renderAllowlist();                       // re-render list only, keep focus
      const s2 = viewEl.querySelector('#fSearch');
      s2.focus(); s2.setSelectionRange(s2.value.length, s2.value.length);
    });

    viewEl.querySelector('#addForm').addEventListener('submit', e => {
      e.preventDefault();
      const dEl = viewEl.querySelector('#fDomain'), nEl = viewEl.querySelector('#fNote');
      const domain = dEl.value.trim().toLowerCase(), note = nEl.value.trim();
      let ok = true;
      // loose hostname check + required trust note (the editorial gate)
      if(!/^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$/.test(domain) || state.domains.some(r=>r.domain===domain)){ dEl.classList.add('invalid'); ok=false; } else dEl.classList.remove('invalid');
      if(!note){ nEl.classList.add('invalid'); ok=false; } else nEl.classList.remove('invalid');
      if(!ok) return;
      state.domains.push({ domain, note, by:'Dr. A. Rao', date:today(), on:true });
      logAudit('create', `domain ${domain} added`);
      state.search = '';
      render();
    });
  }

  /* ---------- config ---------- */
  function renderConfig(){
    viewEl.innerHTML = `
      <div class="page-title">Models &amp; parameters</div>
      <div class="page-lead">Config-as-data. The orchestrator reads these with a ~60&nbsp;s cache — changes take effect on the next query, no deploy.</div>

      <div class="warn-banner">
        ${svg('warn',{w:15,sw:2,stroke:'#8a5a3c'})}
        <p>Changes apply <b>globally and immediately</b> — there is no staged rollout in v1. Editing <code>model.generation</code> requires confirmation.</p>
      </div>

      <div class="tbl" style="margin-top:16px;">
        <div class="tbl-head cols-config"><div>Key</div><div>Value</div><div class="cell-default">Default</div><div>Description</div><div class="cell-who-wrap">Last changed</div></div>
        ${state.config.map(r=>`
          <div class="tbl-row cols-config">
            <div class="cell-key">${esc(r.key)}${r.critical?'<span class="confirm-chip">CONFIRM</span>':''}</div>
            <div class="cell-value" title="${esc(r.value)}">${esc(r.value)}</div>
            <div class="cell-default">${esc(r.def)}</div>
            <div class="cell-desc">${esc(r.desc)}</div>
            <div class="cell-who-wrap"><div class="cell-who">${esc(r.who)}</div><div class="cell-when">${esc(r.when)}</div></div>
          </div>`).join('')}
      </div>`;
  }

  /* ---------- keys ---------- */
  function renderKeys(){
    viewEl.innerHTML = `
      <div class="page-title">API keys</div>
      <div class="page-lead">Key material lives in the secrets manager only — never in the database or this UI. Rotating writes a new value and hot-reloads the orchestrator. Admin only.</div>

      <div class="keys-list">
        ${state.keys.map((k,i)=>`
          <div class="key-card">
            <div class="key-info">
              <div class="key-provider">${esc(k.provider)}</div>
              <div class="key-use">${esc(k.use)}</div>
            </div>
            <div class="key-hint">${esc(k.hint)}</div>
            <div class="key-rotated">Rotated<b>${esc(k.rotated)}</b></div>
            <button class="rotate-btn" data-i="${i}">${svg('rotate',{w:12,sw:2})}Rotate</button>
          </div>`).join('')}
      </div>`;

    // Two-step rotate: first click arms a confirm, second performs it.
    viewEl.querySelectorAll('.rotate-btn').forEach(el =>
      el.addEventListener('click', () => {
        const i = +el.getAttribute('data-i');
        if(!el.classList.contains('confirming')){
          el.classList.add('confirming');
          el.innerHTML = `${svg('warn',{w:12,sw:2})}Confirm rotate?`;
          setTimeout(()=>{ if(el.isConnected && el.classList.contains('confirming')){ el.classList.remove('confirming'); el.innerHTML = `${svg('rotate',{w:12,sw:2})}Rotate`; } }, 4000);
          return;
        }
        const k = state.keys[i];
        k.rotated = today();
        logAudit('rotate', `key ${k.provider.toLowerCase().split(' ')[0]} rotated (value redacted)`);
        renderKeys();
      }));
  }

  /* ---------- audit ---------- */
  function renderAudit(){
    viewEl.innerHTML = `
      <div class="page-title">Audit log</div>
      <div class="page-lead">Every mutation across both modules writes a row via Postgres trigger — actor, action, before/after. Read-only from the app.</div>

      <div class="tbl" style="margin-top:16px;">
        <div class="tbl-head cols-audit"><div>Actor</div><div>Action</div><div>Change</div><div class="cell-when">When</div></div>
        ${state.audit.map(r=>`
          <div class="tbl-row cols-audit">
            <div class="cell-actor">${esc(r.actor)}</div>
            <div><span class="action-chip action-${esc(r.action)}">${esc(r.action)}</span></div>
            <div class="cell-change">${esc(r.change)}</div>
            <div class="cell-when">${esc(r.when)}</div>
          </div>`).join('')}
      </div>`;
  }

  /* ---------- glue ---------- */
  document.getElementById('backApp').addEventListener('click', () => { window.location.href = 'app.html'; });
  function esc(s){ return String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }

  render();
})();
