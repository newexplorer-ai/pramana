/* ============================================================
   Pramana — marketing site (Home canvas)
   FAQ accordion + request-access flow. The hero ask input
   routes unauthenticated visitors to Request access — it never
   runs real queries (cost/abuse guard, PRD suggestion).
   ============================================================ */
(function(){
  'use strict';

  /* ---------- FAQ accordion ---------- */
  document.querySelectorAll('.faq-item').forEach(item =>
    item.addEventListener('click', () => item.classList.toggle('open')));

  /* ---------- request-access modal ---------- */
  const modal   = document.getElementById('accessModal');
  const formWrap= document.getElementById('accessFormWrap');
  const success = document.getElementById('accessSuccess');
  const form    = document.getElementById('accessForm');

  function openModal(){
    formWrap.hidden = false; success.hidden = true;
    modal.hidden = false;
    const first = document.getElementById('raName');
    if(first) setTimeout(()=>first.focus(), 60);
  }
  function closeModal(){ modal.hidden = true; }

  document.querySelectorAll('[data-open-access]').forEach(el =>
    el.addEventListener('click', openModal));
  document.querySelectorAll('[data-close-access]').forEach(el =>
    el.addEventListener('click', closeModal));
  document.addEventListener('keydown', e => { if(e.key==='Escape' && !modal.hidden) closeModal(); });

  /* Hero ask → request access (with the question preserved as context) */
  document.getElementById('heroAsk').addEventListener('submit', e => {
    e.preventDefault();
    openModal();
  });

  /* ---------- waitlist submit (stand-in for the waitlist table) ---------- */
  form.addEventListener('submit', e => {
    e.preventDefault();
    const fields = {
      name:  document.getElementById('raName'),
      reg:   document.getElementById('raReg'),
      spec:  document.getElementById('raSpec'),
      inst:  document.getElementById('raInst'),
      email: document.getElementById('raEmail'),
    };
    let ok = true;
    Object.values(fields).forEach(f => {
      const valid = f.id==='raEmail' ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.value.trim()) : !!f.value.trim();
      f.classList.toggle('invalid', !valid);
      if(!valid) ok = false;
    });
    if(!ok) return;
    // production: POST → waitlist table for manual approval (PRD §5).
    // Here it lands in the same store the admin portal's Beta access
    // queue reads, so request → approve → sign in is a closed loop.
    try {
      const d = new Date();
      const list = JSON.parse(localStorage.getItem('pramana_access_requests')||'[]');
      list.unshift({
        name: fields.name.value.trim(), reg: fields.reg.value.trim(),
        council: document.getElementById('raCouncil').value,
        specialty: fields.spec.value.trim(), institution: fields.inst.value.trim(),
        email: fields.email.value.trim().toLowerCase(),
        at: `${d.getDate()} ${d.toLocaleString('en',{month:'short'})} ${d.getFullYear()}`,
        status: 'pending',
      });
      localStorage.setItem('pramana_access_requests', JSON.stringify(list));
    } catch(err){ /* prototype storage only */ }
    formWrap.hidden = true; success.hidden = false;
  });
})();
