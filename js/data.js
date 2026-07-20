/* ============================================================
   Pramana — demo content & response-routing data
   Mirrors the 3 response tiers from the PRD (§6.2) and the
   answer surfaces drawn in the User Flow canvas.
   In production this comes from the FastAPI orchestrator
   (see PRD §7.5 response contract); here it is static demo data.
   ============================================================ */

/* Inline source pills used inside prose. `cite` links to a citation payload id. */
const PILL = {
  icmr:  { label:'ICMR',     cls:'',      cite:'icmr_dm_2023' },
  mohfw: { label:'MoHFW',    cls:'mohfw', cite:'mohfw_stg_2022' },
  icmrGov:{ label:'ICMR.GOV', cls:'web',  cite:null },
};

/* Citation payloads (Screen 5). Keyed by source_id. */
const CITATIONS = {
  icmr_dm_2023: {
    body:'ICMR',
    verified:true,
    passageHtml:'“In adults with type 2 diabetes mellitus without contraindications, <mark>metformin is recommended as the first-line pharmacological agent</mark>, initiated together with lifestyle modification.”',
    meta:[
      ['Source','Management of Type 2 Diabetes Mellitus'],
      ['Issuing body','Indian Council of Medical Research'],
      ['Published','May 2023'],
      ['Page','42'],
      ['Licence','Government publication · open'],
    ],
    sourceId:'icmr_dm_2023',
    page:42,
  },
  mohfw_stg_2022: {
    body:'MoHFW',
    verified:true,
    passageHtml:'“Glycaemic targets should be <mark>individualised</mark>; an HbA1c of ≤7% is appropriate for most non-pregnant adults, with relaxed targets in the elderly or those with comorbidity.”',
    meta:[
      ['Source','Standard Treatment Guidelines'],
      ['Issuing body','Ministry of Health & Family Welfare'],
      ['Published','2022'],
      ['Page','18'],
      ['Licence','Government publication · open'],
    ],
    sourceId:'mohfw_stg_2022',
    page:18,
  },
};

/* Staged-retrieval choreography per tier (Screen 3). */
const STAGES = {
  1:[
    {t:'Searching ICMR guidelines & MoHFW STG'},
    {t:'Retrieved 8 candidate passages'},
    {t:'Reading 4 relevant passages'},
    {t:'Checking groundedness'},
  ],
  2:[
    {t:'Searching corpus — confidence below threshold'},
    {t:'Extending to allowlisted Indian domains'},
    {t:'Reading icmr.gov.in result'},
    {t:'Checking groundedness'},
  ],
  3:[
    {t:'Searching curated corpus'},
    {t:'No grounded corpus passage found'},
    {t:'Extending to allowlisted web — no source'},
    {t:'Falling back to general model'},
  ],
};

/* Response payloads keyed by tier. Prose uses {{pill}} tokens. */
const ANSWERS = {
  diabetes:{
    tier:1,
    query:'First-line management of type 2 diabetes in adults?',
    stamp:'Answered 19 Jul 2026',
    latestSource:'May 2023',
    group:{ kind:'gov', label:'Government Guideline', body:'ICMR', issuer:'Indian Council of Medical Research',
      titleLink:'Management of Type 2 Diabetes Mellitus — National Guidelines.',
      cite:'ICMR · 2023 · p.42 · icmr_dm_2023', citeId:'icmr_dm_2023',
      prose:'The ICMR recommends <b>metformin as first-line pharmacotherapy</b> for adults with type 2 diabetes and no contraindication, initiated alongside structured lifestyle modification.{{icmr}} Therapy should target an <b>individualised HbA1c</b>, with ≤7% appropriate for most non-pregnant adults.{{mohfw}} Where lifestyle measures and metformin are insufficient, a second agent is added on the basis of comorbidity, cost, and availability under the NLEM.{{icmr}}'
    },
    references:[
      {n:1, title:'Management of Type 2 Diabetes Mellitus.', meta:'ICMR. 2023.', tag:'Guideline', cite:'icmr_dm_2023'},
      {n:2, title:'Standard Treatment Guidelines.', meta:'MoHFW. 2022.', tag:'Guideline', cite:'mohfw_stg_2022'},
    ],
    followups:[
      'When is a sulfonylurea preferred as add-on therapy?',
      'What HbA1c target applies in elderly patients?',
    ],
  },

  dengue:{
    tier:2,
    query:'Current ICMR advisory on dengue fluid management?',
    stamp:'Answered 19 Jul 2026',
    notice:'Corpus confidence below threshold — extended to allowlisted domains.',
    group:{ kind:'web', label:'Web · allowlisted domain', body:'ICMR.GOV.IN',
      titleLink:'National Guidelines for Clinical Management of Dengue.',
      cite:'icmr.gov.in · web page', external:true,
      prose:'National guidelines advise <b>careful crystalloid fluid therapy titrated to the phase of illness</b>, with close haematocrit and urine-output monitoring during the critical phase.{{icmrGov}}'
    },
    snapshot:'Retrieved from <b>icmr.gov.in</b> on 18 Jul 2026 · web content is a snapshot we do not control',
  },

  // Tier-1 follow-up answers so the diabetes thread stays grounded and coherent.
  sulfonylurea:{
    tier:1,
    query:'When is a sulfonylurea preferred as add-on therapy?',
    stamp:'Answered 19 Jul 2026',
    latestSource:'2022',
    group:{ kind:'gov', label:'Government Guideline', body:'MoHFW', issuer:'Ministry of Health & Family Welfare',
      titleLink:'Standard Treatment Guidelines — Type 2 Diabetes.',
      cite:'MoHFW · 2022 · p.18 · mohfw_stg_2022', citeId:'mohfw_stg_2022',
      prose:'A <b>sulfonylurea (e.g. glimepiride)</b> is a preferred second-line add-on to metformin where affordability and availability are priorities, provided the patient is at low risk of hypoglycaemia.{{mohfw}} The ICMR notes the choice of add-on should be individualised to comorbidity, weight, and cost.{{icmr}}'
    },
    references:[
      {n:1, title:'Standard Treatment Guidelines.', meta:'MoHFW. 2022.', tag:'Guideline', cite:'mohfw_stg_2022'},
      {n:2, title:'Management of Type 2 Diabetes Mellitus.', meta:'ICMR. 2023.', tag:'Guideline', cite:'icmr_dm_2023'},
    ],
    followups:[
      'What HbA1c target applies in elderly patients?',
      'First-line management of type 2 diabetes in adults?',
    ],
  },

  hba1cElderly:{
    tier:1,
    query:'What HbA1c target applies in elderly patients?',
    stamp:'Answered 19 Jul 2026',
    latestSource:'2022',
    group:{ kind:'gov', label:'Government Guideline', body:'MoHFW', issuer:'Ministry of Health & Family Welfare',
      titleLink:'Standard Treatment Guidelines — Glycaemic Targets.',
      cite:'MoHFW · 2022 · p.18 · mohfw_stg_2022', citeId:'mohfw_stg_2022',
      prose:'In <b>elderly patients</b>, a <b>relaxed HbA1c target of 7.5–8%</b> is advised to limit hypoglycaemia risk, with targets loosened further in the presence of frailty or multiple comorbidities.{{mohfw}} Glycaemic goals remain individualised rather than uniform.{{icmr}}'
    },
    references:[
      {n:1, title:'Standard Treatment Guidelines.', meta:'MoHFW. 2022.', tag:'Guideline', cite:'mohfw_stg_2022'},
      {n:2, title:'Management of Type 2 Diabetes Mellitus.', meta:'ICMR. 2023.', tag:'Guideline', cite:'icmr_dm_2023'},
    ],
    followups:[
      'When is a sulfonylurea preferred as add-on therapy?',
      'First-line management of type 2 diabetes in adults?',
    ],
  },

  crohns:{
    tier:3,
    query:'Preferred biologic sequencing for refractory paediatric Crohn’s in Indian practice?',
    model:'Claude',
    prose:'Refractory paediatric Crohn’s disease is <b>generally</b> managed with escalation to anti-TNF biologics such as infliximab or adalimumab, with sequencing individualised to response, prior exposure, and tolerability. Where anti-TNF therapy fails, agents such as ustekinumab or vedolizumab may be considered. This reflects general practice and <b>may not match Indian guidelines, drug availability, or approved paediatric indications.</b>',
    warn:'This answer is <b>not grounded in Indian medical literature.</b> It carries no citation and has not passed the groundedness check. Verify against a primary source before any clinical use.',
    sourcesChecked:['ICMR corpus','MoHFW STG','icmr.gov.in','nmji.in','ijmr.org.in'],
  },

  // Query-agnostic Tier-3 fallback for anything the corpus & web can't ground.
  generic:{
    tier:3,
    query:'',
    model:'Claude',
    prose:'No passage in the indexed Indian literature or on an allowlisted Indian domain matched this question. A general model can offer background information, but it <b>may not reflect Indian guidelines, drug availability, dosing conventions, or approved indications.</b>',
    warn:'This answer is <b>not grounded in Indian medical literature.</b> Sources checked: curated corpus, allowlisted web. It carries no citation and has not passed the groundedness check — verify against a primary source before any clinical use.',
    sourcesChecked:['ICMR corpus','MoHFW STG','icmr.gov.in','nmji.in','ijmr.org.in'],
  },

  // D1 resolution (c): high-stakes queries with no grounded source get an
  // honest "not found" — never an unverified general answer.
  notfound:{
    tier:3,
    notFound:true,
    query:'',
    prose:'<b>Not found in the indexed Indian literature.</b> This looks like a dosing or interaction question, so no unverified general-model answer is shown — for high-stakes queries Pramana only answers from a grounded Indian source.',
    warn:'This query was logged to the corpus-gap register. When an Indian source covering it is added to the corpus, questions like this will return a grounded, cited answer.',
    sourcesChecked:['ICMR corpus','MoHFW STG','NLEM','icmr.gov.in','nmji.in','ijmr.org.in'],
  },
};

/* High-stakes guard (PRD D1 → option c): dosing/interaction queries must
   never receive an unverified Tier 3 answer. Conservative lexicon match —
   the production version is a server-side classifier. */
function isHighStakes(q){
  return /\b(dos(e|es|ing|age)|mg\/kg|interaction|contraindicat|overdose|titrat)/i.test(q);
}

/* Corpus catalogue for the user-facing Sources screen (PRD §4.4). */
const CORPUS_SOURCES = [
  { title:'Management of Type 2 Diabetes Mellitus — National Guidelines', body:'ICMR',  year:'2023', type:'Guideline', id:'icmr_dm_2023' },
  { title:'Standard Treatment Guidelines',                                body:'MoHFW', year:'2022', type:'Guideline', id:'mohfw_stg_2022' },
  { title:'National Guidelines for Clinical Management of Dengue',        body:'MoHFW', year:'2023', type:'Guideline', id:'mohfw_dengue_2023' },
  { title:'National Essential Medicines List',                            body:'MoHFW', year:'2022', type:'Formulary', id:'nlem_2022' },
  { title:'Guidelines for Management of Community-Acquired Pneumonia',    body:'ICMR',  year:'2024', type:'Guideline', id:'icmr_cap_2024' },
  { title:'Hypertension Screening & Management in Primary Care',          body:'MoHFW', year:'2023', type:'Guideline', id:'mohfw_htn_2023' },
  { title:'Antimicrobial Resistance Surveillance Report',                 body:'ICMR',  year:'2025', type:'Report',    id:'icmr_amr_2025' },
  { title:'IAP Consensus on Paediatric Immunisation',                     body:'Indian Pediatrics', year:'2024', type:'Position statement', id:'iap_imm_2024' },
];

const ALLOWLIST_DOMAINS = [
  { domain:'icmr.gov.in',          note:'Indian Council of Medical Research' },
  { domain:'main.mohfw.gov.in',    note:'Ministry of Health & Family Welfare' },
  { domain:'ijmr.org.in',          note:'Indian Journal of Medical Research' },
  { domain:'nmji.in',              note:'National Medical Journal of India' },
  { domain:'indianpediatrics.net', note:'Indian Pediatrics' },
  { domain:'cdsco.gov.in',         note:'CDSCO — drug approvals & safety' },
];

/* Query router (PRD §7.3–7.4) — maps a raw question to an answer key.
   Real system: embed → vector_search → threshold → tier. Here: keyword match. */
function routeQuery(raw){
  const q = (raw||'').toLowerCase();
  if(/sulfonylurea|add-on|glimepiride/.test(q)) return 'sulfonylurea';
  if(/hba1c|elderly|glycaemic|glycemic target/.test(q)) return 'hba1cElderly';
  if(/diabet|metformin|first-line therapy|nlem dosing/.test(q)) return 'diabetes';
  if(/dengue|fluid|crystalloid|advisory|icmr guideline/.test(q)) return 'dengue';
  if(/crohn|refractory|biologic|infliximab|adalimumab|ustekinumab/.test(q)) return 'crohns';
  // No grounded source: high-stakes queries are withheld (D1 → c),
  // everything else honestly falls through to the unverified tier.
  if(isHighStakes(q)) return 'notfound';
  return 'generic';
}

/* Home screen affordances (Screen 2). */
const HOME = {
  chips:[
    {icon:'file', label:'Ask about first-line therapy', q:'First-line management of type 2 diabetes in adults?'},
    {icon:'chart', label:'Check NLEM dosing', q:'First-line management of type 2 diabetes in adults?'},
    {icon:'plus', label:'Find the ICMR guideline', q:'Current ICMR advisory on dengue fluid management?'},
  ],
  suggests:[
    'First-line management of type 2 diabetes in adults?',
    'Empirical antibiotics for community-acquired pneumonia in India',
    'NLEM recommended dosing for oral amoxicillin in children',
  ],
};
