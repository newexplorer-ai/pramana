/* ============================================================
   Pramana — login screen controller
   Real Google Sign-In when GOOGLE_CLIENT_ID is set.

   The allowlist is NEVER enumerated here. A login screen is
   public, so listing approved accounts would leak every beta
   clinician's name and email to anyone who opens the page.
   Demo mode therefore asks for an email rather than offering
   a menu of accounts.

   After sign-in the user goes to whatever they were trying to
   reach, or to their role's landing page (admins → the portal).
   ============================================================ */
(function(){
  'use strict';

  const A          = PRAMANA_AUTH;
  const params     = new URLSearchParams(location.search);
  const wanted     = sanitizeNext(params.get('next'));   // null when not specified
  const alertSlot  = document.getElementById('alertSlot');
  const gbtnSlot   = document.getElementById('gbtnSlot');
  const demoSlot   = document.getElementById('demoSlot');
  const demoBanner = document.getElementById('demoBanner');

  /* Only ever redirect to a known local page — never to a supplied URL. */
  function sanitizeNext(v){
    const allowed = ['app.html','admin.html','mobile.html','index.html'];
    return allowed.includes(v) ? v : null;
  }
  const destinationFor = session => wanted || A.landingFor(session.role);

  const ICON = {
    warn:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    info:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>',
  };
  const esc = s => String(s).replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));

  function showAlert(kind, html){
    alertSlot.innerHTML = `<div class="login-alert ${kind}">${kind==='deny'?ICON.warn:ICON.info}<div>${html}</div></div>`;
  }

  /* Already signed in and still authorised → straight through. */
  const live = A.validate();
  if(live){ location.replace(destinationFor(live)); return; }

  if(params.get('denied') === 'role'){
    showAlert('deny', '<b>Admin access required.</b> Your account is signed in but does not have permission for that area. Ask an admin to raise your role.');
  } else if(params.get('signedout') === '1'){
    showAlert('info', 'You have been signed out.');
  }

  /* ---------- outcome handling ---------- */

  /* LIVE mode: the server verifies the token and owns the allowlist. */
  async function serverLogin(path, body, emailForErrors){
    try {
      const res = await PRAMANA_API.post(path, body);
      PRAMANA_API.setToken(res.token);
      A.setSession(res.user);
      location.replace(destinationFor(res.user));
    } catch(err){
      showDenied(err.detail || 'failed', emailForErrors);
    }
  }

  function showDenied(reason, email){
    email = esc(email || 'this account');
    if(reason === 'not_allowlisted'){
      showAlert('deny',
        `<b>Not on the beta allowlist.</b> <span class="mono">${email}</span> isn’t approved yet. ` +
        `Pramana is limited to verified clinicians during the closed beta. ` +
        `<a href="index.html#request">Request access →</a>`);
    } else if(reason === 'disabled'){
      showAlert('deny',
        `<b>Access suspended.</b> <span class="mono">${email}</span> is on the allowlist but currently disabled. ` +
        `Contact your Pramana administrator.`);
    } else if(reason === 'unverified'){
      showAlert('deny', '<b>Unverified Google account.</b> Verify your email with Google, then try again.');
    } else if(reason === 'demo_password_required'){
      showAlert('deny', '<b>Wrong access code.</b> Ask your Pramana administrator for the beta access code.');
    } else {
      showAlert('deny', '<b>Sign-in failed.</b> Please try again.');
    }
  }

  function handleClaims(claims){
    // LIVE mode never trusts client-side claims — it posts to the server.
    if(PRAMANA_API.on){
      const pw = document.getElementById('demoPassword');
      serverLogin('/api/auth/demo',
        { email: claims.email, password: pw ? pw.value : undefined }, claims.email);
      return;
    }
    const result = A.verifyAndAuthorize(claims);
    if(result.ok){
      A.setSession(result.session);
      location.replace(destinationFor(result.session));
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
      showAlert('deny', '<b>Unverified Google account.</b> Verify your email with Google, then try again.');
    } else {
      showAlert('deny', '<b>Sign-in failed.</b> Please try again.');
    }
  }

  /* ---------- real Google Identity Services ---------- */
  function initGoogle(){
    google.accounts.id.initialize({
      client_id: A.GOOGLE_CLIENT_ID,
      callback: resp => {
        if(PRAMANA_API.on){
          // Signature verified SERVER-side; client never decides authenticity.
          const claims = A.decodeIdToken(resp.credential) || {};
          serverLogin('/api/auth/google', { credential: resp.credential }, claims.email);
        } else {
          handleClaims(A.decodeIdToken(resp.credential));
        }
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

  /* ---------- demo mode (no Google client configured) ----------
     Asks which account to simulate. It does not reveal who is on
     the allowlist — you must already know the address. */
  function initDemo(){
    demoBanner.hidden = false;
    demoBanner.className = 'demo-banner';
    // A public deployment gates demo sign-in behind a shared access code.
    const needsCode = PRAMANA_API.on && PRAMANA_API.health.demo_password;

    demoBanner.hidden = false;
    demoBanner.className = 'demo-banner';
    demoBanner.innerHTML = needsCode
      ? '<b>Closed beta — access code required.</b> Sign in with your approved ' +
        'email and the code your administrator gave you. Google Sign-In arrives once ' +
        'the OAuth client is configured.'
      : '<b>Demo mode — no Google client configured.</b> Sign-in is simulated. ' +
        'Set <code>GOOGLE_CLIENT_ID</code> to enable real Google Sign-In.';

    gbtnSlot.innerHTML =
      `<button class="gbtn" id="gDemo">
         <svg width="17" height="17" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.7 30.2.5 24 .5 14.6.5 6.5 5.9 2.6 13.7l7.8 6.1C12.3 13.7 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.2 5.3-4.7 7l7.6 5.9c4.4-4.1 6.8-10.755 6.8-17.4z"/><path fill="#FBBC05" d="M10.4 28.2c-.5-1.4-.8-2.9-.8-4.2s.3-2.8.8-4.2l-7.8-6.1C.9 16.7 0 20.2 0 24s.9 7.3 2.6 10.3l7.8-6.1z"/><path fill="#34A853" d="M24 47.5c6.2 0 11.5-2 15.3-5.6l-7.6-5.9c-2.1 1.4-4.8 2.3-7.7 2.3-6.4 0-11.7-4.2-13.6-9.9l-7.8 6.1C6.5 42.1 14.6 47.5 24 47.5z"/></svg>
         Sign in with Google
       </button>`;

    document.getElementById('gDemo').addEventListener('click', () => {
      demoSlot.innerHTML = `
        <form class="demo-form" id="demoForm" autocomplete="off">
          <label for="demoEmail">Continue as</label>
          <input id="demoEmail" type="email" placeholder="you@hospital.in" spellcheck="false" autocomplete="off">
          ${needsCode ? `
          <label for="demoPassword" style="margin-top:6px;">Beta access code</label>
          <input id="demoPassword" type="password" placeholder="Shared code" autocomplete="off">` : ''}
          <button class="cta-mini" type="submit">Continue</button>
        </form>`;
      const input = document.getElementById('demoEmail');
      input.focus();
      document.getElementById('demoForm').addEventListener('submit', e => {
        e.preventDefault();
        const email = input.value.trim().toLowerCase();
        if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){ input.classList.add('invalid'); return; }
        input.classList.remove('invalid');
        const known = A.findUser(email);
        // Mirrors exactly what a Google ID token would carry.
        handleClaims({ email, email_verified:true, name: known ? known.name : email, picture:'' });
      });
    });
  }

  /* ---------- boot ---------- */
  (async function boot(){
    await PRAMANA_API.ready;
    // LIVE mode: the server says whether Google auth is configured.
    const googleConfigured = PRAMANA_API.on
      ? PRAMANA_API.health.google_auth : A.isConfigured;
    if(PRAMANA_API.on && !PRAMANA_API.health.anthropic){
      showAlert('info', '<b>Backend is up but no Anthropic credentials are set.</b> ' +
        'Sign-in works; asking questions will fail until <span class="mono">ANTHROPIC_API_KEY</span> is exported.');
    }
    if(googleConfigured){
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
})();
