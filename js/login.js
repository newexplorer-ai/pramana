/* ============================================================
   Pramana — login screen controller
   Real Google Sign-In when GOOGLE_CLIENT_ID is set; a clearly
   labelled demo picker otherwise so the flow stays testable.
   ============================================================ */
(function(){
  'use strict';

  const A          = PRAMANA_AUTH;
  const params     = new URLSearchParams(location.search);
  const next       = sanitizeNext(params.get('next'));
  const alertSlot  = document.getElementById('alertSlot');
  const gbtnSlot   = document.getElementById('gbtnSlot');
  const demoSlot   = document.getElementById('demoSlot');
  const demoBanner = document.getElementById('demoBanner');

  /* Only ever redirect to a local page — never to an attacker-supplied URL. */
  function sanitizeNext(v){
    const allowed = ['app.html','admin.html','mobile.html','index.html'];
    return allowed.includes(v) ? v : 'app.html';
  }

  const ICON = {
    warn:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    info:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>',
  };
  const esc = s => String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));

  function showAlert(kind, html){
    alertSlot.innerHTML = `<div class="login-alert ${kind}">${kind==='deny'?ICON.warn:ICON.info}<div>${html}</div></div>`;
  }

  /* Already signed in and still authorised → go straight through. */
  if(A.validate()){ location.replace(next); return; }

  /* Deep-linked denial reasons */
  if(params.get('denied') === 'role'){
    showAlert('deny', '<b>Admin access required.</b> Your account is signed in but does not have permission for that area. Ask an admin to raise your role.');
  } else if(params.get('signedout') === '1'){
    showAlert('info', 'You have been signed out.');
  }

  /* ---------- outcome handling ---------- */
  function handleClaims(claims){
    const result = A.verifyAndAuthorize(claims);
    if(result.ok){
      A.setSession(result.session);
      location.replace(next);
      return;
    }
    const email = esc(result.email || 'this account');
    if(result.reason === 'not_allowlisted'){
      showAlert('deny',
        `<b>Not on the beta allowlist.</b> <span class="mono">${email}</span> isn’t approved yet. ` +
        `Pramana is limited to verified clinicians during the closed beta. ` +
        `<a href="index.html#request">Request access →</a>`);
    } else if(result.reason === 'disabled'){
      showAlert('deny',
        `<b>Access suspended.</b> <span class="mono">${email}</span> is on the allowlist but currently disabled. ` +
        `Contact your Pramana administrator.`);
    } else if(result.reason === 'unverified'){
      showAlert('deny', `<b>Unverified Google account.</b> Verify your email with Google, then try again.`);
    } else {
      showAlert('deny', `<b>Sign-in failed.</b> Please try again.`);
    }
  }

  /* ---------- real Google Identity Services ---------- */
  function initGoogle(){
    google.accounts.id.initialize({
      client_id: A.GOOGLE_CLIENT_ID,
      callback: resp => {
        const claims = A.decodeIdToken(resp.credential);
        handleClaims(claims);
      },
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    google.accounts.id.renderButton(gbtnSlot, {
      theme:'outline', size:'large', text:'signin_with',
      shape:'rectangular', logo_alignment:'left', width:360,
    });
    google.accounts.id.prompt();   // One Tap for returning users
  }

  /* ---------- demo mode ---------- */
  function initDemo(){
    demoBanner.hidden = false;
    demoBanner.className = 'demo-banner';
    demoBanner.innerHTML =
      `<b>Demo mode — no Google client configured.</b> Sign-in is simulated so the flow can be tested. ` +
      `Set <code>GOOGLE_CLIENT_ID</code> in <code>js/auth.js</code> to enable real Google Sign-In.`;

    gbtnSlot.innerHTML =
      `<button class="gbtn" id="gDemo">
         <svg width="17" height="17" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.7 30.2.5 24 .5 14.6.5 6.5 5.9 2.6 13.7l7.8 6.1C12.3 13.7 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.2 5.3-4.7 7l7.6 5.9c4.4-4.1 6.8-10.755 6.8-17.4z"/><path fill="#FBBC05" d="M10.4 28.2c-.5-1.4-.8-2.9-.8-4.2s.3-2.8.8-4.2l-7.8-6.1C.9 16.7 0 20.2 0 24s.9 7.3 2.6 10.3l7.8-6.1z"/><path fill="#34A853" d="M24 47.5c6.2 0 11.5-2 15.3-5.6l-7.6-5.9c-2.1 1.4-4.8 2.3-7.7 2.3-6.4 0-11.7-4.2-13.6-9.9l-7.8 6.1C6.5 42.1 14.6 47.5 24 47.5z"/></svg>
         Sign in with Google
       </button>`;

    document.getElementById('gDemo').addEventListener('click', () => {
      demoSlot.innerHTML = `
        <div class="login-sep">choose a demo account</div>
        <div class="demo-list">
          ${A.users().map(u => `
            <button class="demo-acct" data-email="${esc(u.email)}">
              <span class="av">${esc(A.initials(u.name))}</span>
              <span class="who">
                <span class="nm">${esc(u.name)}</span>
                <span class="em">${esc(u.email)}</span>
              </span>
              <span class="role-tag ${u.enabled?'role-'+esc(u.role):'role-off'}">${u.enabled?esc(u.role):'disabled'}</span>
            </button>`).join('')}
          <button class="demo-acct" data-email="outsider@example.com">
            <span class="av">??</span>
            <span class="who">
              <span class="nm">Someone not on the list</span>
              <span class="em">outsider@example.com</span>
            </span>
            <span class="role-tag role-off">not listed</span>
          </button>
        </div>`;
      demoSlot.querySelectorAll('.demo-acct').forEach(el =>
        el.addEventListener('click', () => {
          const email = el.getAttribute('data-email');
          const known = A.findUser(email);
          // Simulates exactly what Google's ID token would carry.
          handleClaims({ email, email_verified:true, name: known ? known.name : 'Unlisted User', picture:'' });
        }));
    });
  }

  /* ---------- boot ---------- */
  if(A.isConfigured){
    // GIS script is async — wait for it.
    const start = Date.now();
    (function wait(){
      if(window.google && google.accounts && google.accounts.id) return initGoogle();
      if(Date.now() - start > 6000){
        showAlert('deny', '<b>Could not reach Google Sign-In.</b> Check your connection and reload.');
        return;
      }
      setTimeout(wait, 120);
    })();
  } else {
    initDemo();
  }
})();
