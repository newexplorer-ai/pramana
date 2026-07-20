/* ============================================================
   Pramana — authentication & beta allowlist
   ------------------------------------------------------------
   Google Sign-In (GIS) proves identity; an admin-maintained
   allowlist decides who may enter. Roles: clinician < editor < admin.

   ⚠ SECURITY BOUNDARY — READ BEFORE SHIPPING REAL DATA
   This build enforces the allowlist IN THE BROWSER, which any
   technical user can bypass. It is a gate, not a security control,
   and is only acceptable while all content behind it is mock data.
   Before a real corpus, real API keys, or real users exist:
     1. Verify the Google ID token signature SERVER-SIDE
        (Supabase Auth or a FastAPI /auth/google endpoint).
     2. Move the allowlist to Postgres `allowed_users` + RLS,
        re-checked on every request (PRD §6.5).
     3. Delete DEMO_MODE and the localStorage stores below.
   The single swap point is `verifyAndAuthorize()`.
   ============================================================ */
const PRAMANA_AUTH = (function(){
  'use strict';

  /* ---------- configuration ----------
     Set GOOGLE_CLIENT_ID to a Web OAuth client ID from
     console.cloud.google.com → APIs & Services → Credentials.
     Add your site origin to "Authorised JavaScript origins":
       https://newexplorer-ai.github.io   (prod)
       http://localhost:4173              (local)
     While it is empty the app runs in DEMO MODE, which simulates
     sign-in without Google and is clearly labelled in the UI. */
  const GOOGLE_CLIENT_ID = '';

  const SESSION_KEY  = 'pramana_session';
  const USERS_KEY    = 'pramana_users';
  const REQUESTS_KEY = 'pramana_access_requests';

  const ROLES = { clinician:1, editor:2, admin:3 };

  /* ---------- storage helpers ---------- */
  const read  = (k, fallback) => { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch(e){ return fallback; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} };
  const today = () => { const d = new Date();
    return `${d.getDate()} ${d.toLocaleString('en',{month:'short'})} ${d.getFullYear()}`; };

  /* ---------- seed allowlist ----------
     Stands in for the `allowed_users` table. */
  // The owner is the ONLY admin; everyone else is a clinician.
  const SEED_USERS = [
    { email:'k.prasad.iitr@gmail.com', name:'Dr. K. Prasad', role:'admin',     enabled:true, by:'system',        date:'12 Jun 2026' },
    { email:'r.iyer@aiims.edu',        name:'Dr. R. Iyer',   role:'clinician', enabled:true, by:'Dr. K. Prasad', date:'02 Jul 2026' },
    { email:'p.nair@stjohns.in',       name:'Dr. P. Nair',   role:'clinician', enabled:false,by:'Dr. K. Prasad', date:'08 Jul 2026' },
  ];
  const SEED_REQUESTS = [
    { name:'Dr. M. Banerjee', email:'m.banerjee@ipgmer.ac.in', reg:'71204', council:'West Bengal',
      specialty:'Paediatrics', institution:'IPGMER Kolkata', at:'18 Jul 2026', status:'pending' },
  ];

  function users(){
    let u = read(USERS_KEY, null);
    if(!u){ u = SEED_USERS.slice(); write(USERS_KEY, u); }
    return u;
  }
  function saveUsers(u){ write(USERS_KEY, u); }

  function requests(){
    let r = read(REQUESTS_KEY, null);
    if(!r){ r = SEED_REQUESTS.slice(); write(REQUESTS_KEY, r); }
    return r;
  }
  function saveRequests(r){ write(REQUESTS_KEY, r); }

  const findUser = email =>
    users().find(u => u.email.toLowerCase() === String(email||'').toLowerCase().trim());

  /* ---------- JWT payload decode ----------
     Reads the claims for UX only. The signature is NOT verified
     here — that is exactly what must happen server-side. */
  function decodeIdToken(jwt){
    try {
      const part = jwt.split('.')[1].replace(/-/g,'+').replace(/_/g,'/');
      const json = decodeURIComponent(atob(part).split('').map(c =>
        '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
      return JSON.parse(json);
    } catch(e){ return null; }
  }

  /* ---------- the swap point ----------
     Today: decode locally + check the local allowlist.
     Later: POST the credential to the backend, which verifies the
     signature with Google's JWKS and answers from `allowed_users`.
     Returns {ok:true, session} | {ok:false, reason, email}. */
  function verifyAndAuthorize(claims){
    if(!claims || !claims.email) return { ok:false, reason:'invalid' };
    if(claims.email_verified === false) return { ok:false, reason:'unverified', email:claims.email };

    const allowed = findUser(claims.email);
    if(!allowed)          return { ok:false, reason:'not_allowlisted', email:claims.email };
    if(!allowed.enabled)  return { ok:false, reason:'disabled',        email:claims.email };

    // Allowlist name is authoritative for display; Google fills the gaps.
    const session = {
      email: allowed.email,
      name:  allowed.name || claims.name || allowed.email,
      role:  allowed.role,
      picture: claims.picture || '',
      at: new Date().toISOString(),
    };
    // record last login on the allowlist row
    const list = users();
    const row = list.find(u => u.email.toLowerCase() === allowed.email.toLowerCase());
    if(row){ row.lastLogin = today(); saveUsers(list); }
    return { ok:true, session };
  }

  /* ---------- session ---------- */
  const current  = () => read(SESSION_KEY, null);
  function setSession(s){ write(SESSION_KEY, s); }
  const hasServerToken = () => { try { return !!localStorage.getItem('pramana_token'); } catch(e){ return false; } };
  function signOut(next){
    // Best-effort server sign-out; the redirect must not wait on it.
    try {
      const t = localStorage.getItem('pramana_token');
      if(t) fetch('/api/auth/signout', { method:'POST',
        headers:{ 'Authorization':'Bearer ' + t } }).catch(()=>{});
      localStorage.removeItem('pramana_token');
    } catch(e){}
    try { localStorage.removeItem(SESSION_KEY); } catch(e){}
    if(window.google && google.accounts && google.accounts.id){
      try { google.accounts.id.disableAutoSelect(); } catch(e){}
    }
    window.location.href = next || 'login.html';
  }

  /* A signed-in session is only valid while its allowlist row still
     permits it — so revoking access in admin takes effect immediately.
     LIVE mode (server token present): the backend re-validates every API
     call and 401s revoked sessions; the local copy is display state only.
     DEMO mode (static hosting): check the local allowlist as before. */
  function validate(){
    const s = current();
    if(!s) return null;
    if(hasServerToken()) return s;
    const row = findUser(s.email);
    if(!row || !row.enabled){ try{ localStorage.removeItem(SESSION_KEY); }catch(e){} return null; }
    if(row.role !== s.role){ s.role = row.role; setSession(s); }   // role changes apply live
    return s;
  }

  const can = role => {
    const s = validate();
    return !!s && ROLES[s.role] >= ROLES[role || 'clinician'];
  };

  /* ---------- route guard ----------
     Call synchronously in <head> so protected content never flashes. */
  function guard(minRole){
    const s = validate();
    const here = window.location.pathname.split('/').pop() || 'index.html';
    if(!s){
      window.location.replace('login.html?next=' + encodeURIComponent(here));
      return false;
    }
    if(ROLES[s.role] < ROLES[minRole || 'clinician']){
      window.location.replace('login.html?denied=role&next=' + encodeURIComponent(here));
      return false;
    }
    return true;
  }

  const initials = name => String(name||'?').replace(/^Dr\.?\s*/i,'')
    .split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase() || '?';

  /* Where a role lands when it signs in without an explicit destination.
     Admins run the configuration portal; everyone else answers questions. */
  const landingFor = role => role === 'admin' ? 'admin.html' : 'app.html';

  return {
    GOOGLE_CLIENT_ID,
    isConfigured: !!GOOGLE_CLIENT_ID,
    ROLES,
    decodeIdToken, verifyAndAuthorize,
    current, validate, setSession, signOut, can, guard, initials, today, landingFor,
    users, saveUsers, findUser,
    requests, saveRequests,
  };
})();
