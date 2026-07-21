"""Pramana — curated Indian medical domain allowlist.

Three bands, from the editorial review:

  A (enabled)   Live-ready. Apex bodies, national programmes, ICMR journals.
  B (disabled)  Plausible but unverified — ICMR institutes, specialty journals
                and societies. Enable individually after checking the site
                actually hosts citable guidance.
  C (disabled)  Unvetted. State health departments, institutional protocols,
                smaller societies. High failure rate expected; several may not
                resolve at all.

Only `enabled` domains are sent to the search API, so B and C are recorded
here for one-click enabling in Admin → Allowed websites without widening what
the product can cite today.

AYUSH domains are deliberately DISABLED: the PRD scopes the corpus to
modern/allopathic sources and excludes traditional medicine from the MVP
(mixing evidentiary traditions on one answer surface is a trust problem).
Enable only if an explicitly-labelled AYUSH mode ships.
"""

STATE_NOTE = "State health department — state guidance; may differ from national policy."
INST_NOTE = "Institutional protocol; local practice, not national policy."

# (domain, trust_note, enabled) — region is attached below.
_INDIAN: list[tuple[str, str, bool]] = [
    # ---------------- Band A — live-ready ----------------
    ("icmr.gov.in", "Indian Council of Medical Research — apex national research & guideline body.", True),
    ("main.icmr.nic.in", "ICMR legacy host — Standard Treatment Workflows & guideline archive.", True),
    ("mohfw.gov.in", "Ministry of Health & Family Welfare — primary ministry domain.", True),
    ("main.mohfw.gov.in", "MoHFW — official policy & Standard Treatment Guidelines.", True),
    ("clinicalestablishments.mohfw.gov.in", "MoHFW Clinical Establishments Act — STGs by specialty.", True),
    ("dghs.mohfw.gov.in", "Directorate General of Health Services — apex technical advisory body.", True),
    ("cdsco.gov.in", "Central Drugs Standard Control Organisation — drug approvals & safety.", True),
    ("nhm.gov.in", "National Health Mission — programme guidelines & training modules.", True),
    ("ncdc.gov.in", "National Centre for Disease Control — outbreak, AMR & communicable disease.", True),
    ("ncdc.mohfw.gov.in", "NCDC under DGHS — surveillance & outbreak documentation.", True),
    ("ihip.mohfw.gov.in", "Integrated Health Information Platform — national disease surveillance.", True),
    ("tbcindia.gov.in", "National TB Elimination Programme — TB diagnosis & treatment guidelines.", True),
    ("ncdirindia.org", "National Centre for Disease Informatics & Research — cancer registry.", True),
    ("ijmr.org.in", "Indian Journal of Medical Research — ICMR peer-reviewed journal.", True),
    ("nmji.in", "National Medical Journal of India — peer-reviewed, AIIMS-affiliated.", True),
    ("indianpediatrics.net", "Indian Pediatrics — IAP official journal.", True),
    ("niirncd.icmr.org.in", "ICMR National Institute of Health Research, Jodhpur — NCD research.", True),
    ("jiaps.com", "Journal of Indian Association of Pediatric Surgeons.", True),
    ("ncahp.abdm.gov.in", "National Commission for Allied & Healthcare Professions.", True),
    ("nmc.org.in", "National Medical Commission — medical education & practice regulation.", True),
    ("pharmacopoeia.org.in", "Indian Pharmacopoeia Commission — IP monographs & pharmacovigilance.", True),
    ("naco.gov.in", "National AIDS Control Organisation — HIV testing & ART guidelines.", True),
    ("nvbdcp.gov.in", "National Centre for Vector Borne Diseases Control — malaria, dengue, kala-azar.", True),
    ("nhp.gov.in", "National Health Portal — MoHFW health information.", True),
    ("nin.res.in", "National Institute of Nutrition (ICMR) — dietary guidelines & RDA.", True),
    ("nihfw.ac.in", "National Institute of Health & Family Welfare — public health training.", True),
    ("ctri.nic.in", "Clinical Trials Registry — India.", True),
    ("nppaindia.nic.in", "National Pharmaceutical Pricing Authority — drug price control.", True),
    ("fssai.gov.in", "Food Safety & Standards Authority of India.", True),
    ("notto.mohfw.gov.in", "National Organ & Tissue Transplant Organisation.", True),
    ("nabh.co", "NABH — hospital accreditation standards.", True),
    ("nhsrcindia.org", "National Health Systems Resource Centre — health systems guidance.", True),
    ("nha.gov.in", "National Health Authority — Ayushman Bharat implementation.", True),
    ("pmjay.gov.in", "PM-JAY — treatment package guidelines & rates.", True),
    ("cghs.gov.in", "Central Government Health Scheme — protocols & formulary.", True),
    ("rchiips.org", "IIPS — National Family Health Survey reports.", True),
    ("iipsindia.ac.in", "International Institute for Population Sciences — health demography.", True),
    ("abdm.gov.in", "Ayushman Bharat Digital Mission — health data standards.", True),
    ("nbe.edu.in", "National Board of Examinations — postgraduate medical standards.", True),
    ("indiannursingcouncil.org", "Indian Nursing Council — nursing practice standards.", True),

    # ---------------- Band B — verify, then enable ----------------
    ("niv.co.in", "National Institute of Virology, Pune (ICMR) — virology reference.", True),
    ("nirt.res.in", "National Institute for Research in Tuberculosis (ICMR).", True),
    ("nirrch.res.in", "National Institute for Research in Reproductive & Child Health (ICMR).", True),
    ("nimr.org.in", "National Institute of Malaria Research (ICMR).", True),
    ("nicpr.res.in", "National Institute of Cancer Prevention & Research (ICMR).", True),
    ("nie.gov.in", "National Institute of Epidemiology (ICMR).", True),
    ("nariindia.org", "National AIDS Research Institute (ICMR).", True),
    ("rmrims.org.in", "Rajendra Memorial Research Institute of Medical Sciences (ICMR).", True),
    ("niohenv.res.in", "National Institute of Occupational Health (ICMR).", True),
    ("nirth.res.in", "National Institute of Research in Tribal Health (ICMR).", True),
    ("japi.org", "Journal of the Association of Physicians of India.", True),
    ("ijp-online.com", "Indian Journal of Pharmacology — IPS journal.", True),
    ("ijmm.org", "Indian Journal of Medical Microbiology — IAMM journal.", True),
    ("ijdvl.com", "Indian Journal of Dermatology, Venereology & Leprology.", True),
    ("ijo.in", "Indian Journal of Ophthalmology — AIOS journal.", True),
    ("ijccm.org", "Indian Journal of Critical Care Medicine — ISCCM journal.", True),
    ("ijem.in", "Indian Journal of Endocrinology & Metabolism.", True),
    ("ijaweb.org", "Indian Journal of Anaesthesia — ISA journal.", True),
    ("neurologyindia.com", "Neurology India — Neurological Society of India.", True),
    ("cancerjournal.net", "Journal of Cancer Research & Therapeutics.", True),
    ("indianjnephrol.org", "Indian Journal of Nephrology — ISN journal.", True),
    ("indianjpsychiatry.org", "Indian Journal of Psychiatry — IPS journal.", True),
    ("lungindia.com", "Lung India — Indian Chest Society journal.", True),
    ("jpgmonline.com", "Journal of Postgraduate Medicine — KEM Hospital, Mumbai.", True),
    ("jcdr.net", "Journal of Clinical & Diagnostic Research.", True),
    ("ijri.org", "Indian Journal of Radiology & Imaging — IRIA journal.", True),
    ("ijcm.org.in", "Indian Journal of Community Medicine — IAPSM journal.", True),
    ("jfmpc.com", "Journal of Family Medicine & Primary Care.", True),
    ("ijpmonline.org", "Indian Journal of Pathology & Microbiology.", True),
    ("jogi.co.in", "Journal of Obstetrics & Gynaecology of India — FOGSI.", True),
    ("ijhg.com", "Indian Journal of Human Genetics.", True),
    ("jgid.org", "Journal of Global Infectious Diseases.", True),
    ("ijstd.org", "Indian Journal of Sexually Transmitted Diseases & AIDS.", True),
    ("e-ijd.org", "Indian Journal of Dermatology.", True),
    ("ijmpo.org", "Indian Journal of Medical & Paediatric Oncology.", True),
    ("jpn.co.in", "Journal of Pediatric Neurosciences.", True),
    ("iapindia.org", "Indian Academy of Pediatrics — immunisation schedule & guidelines.", True),
    ("csi.org.in", "Cardiological Society of India — consensus statements.", True),
    ("rssdi.in", "RSSDI — diabetes guidelines (consensus, not statutory).", True),
    ("apiindia.org", "Association of Physicians of India — internal medicine guidance.", True),
    ("fogsi.org", "FOGSI — obstetric & gynaecological good practice recommendations.", True),
    ("isnindia.org", "Indian Society of Nephrology — specialty guidance.", True),
    ("indianchestsociety.org", "Indian Chest Society — respiratory consensus guidelines.", True),
    ("isccm.org", "Indian Society of Critical Care Medicine — ICU guidelines.", True),
    ("isaweb.in", "Indian Society of Anaesthesiologists — perioperative guidance.", True),
    ("iria.org.in", "Indian Radiological & Imaging Association — imaging standards.", True),
    ("asiindia.org", "Association of Surgeons of India — surgical guidance.", True),
    ("indianpsychiatricsociety.org", "Indian Psychiatric Society — clinical practice guidelines.", True),
    ("iansindia.org", "Indian Academy of Neurology — consensus guidance.", True),
    ("isgindia.org", "Indian Society of Gastroenterology — GI practice guidance.", True),
    ("inasl.org.in", "INASL — hepatology consensus statements.", True),
    ("iadvl.org", "IADVL — dermatology practice guidance.", True),
    ("aios.org", "All India Ophthalmological Society.", True),
    ("ioaindia.org", "Indian Orthopaedic Association.", True),
    ("usiindia.org", "Urological Society of India.", True),
    ("endocrinesocietyindia.org", "Endocrine Society of India — consensus statements.", True),
    ("nsi.org.in", "Neurological Society of India.", True),
    ("dciindia.gov.in", "Dental Council of India.", True),
    ("censusindia.gov.in", "Registrar General — Sample Registration System vital statistics.", True),
    ("ipc.gov.in", "Indian Pharmacopoeia Commission — alternate host.", True),

    # ---------------- Band C — unvetted: state health departments ----------------
    ("hmfw.ap.gov.in", f"Andhra Pradesh — {STATE_NOTE}", True),
    ("health.arunachal.gov.in", f"Arunachal Pradesh — {STATE_NOTE}", True),
    ("nhm.assam.gov.in", f"Assam — {STATE_NOTE}", True),
    ("shsb.bihar.gov.in", f"Bihar — {STATE_NOTE}", True),
    ("cghealth.nic.in", f"Chhattisgarh — {STATE_NOTE}", True),
    ("health.goa.gov.in", f"Goa — {STATE_NOTE}", True),
    ("gujhealth.gujarat.gov.in", f"Gujarat — {STATE_NOTE}", True),
    ("haryanahealth.nic.in", f"Haryana — {STATE_NOTE}", True),
    ("nrhmhp.gov.in", f"Himachal Pradesh — {STATE_NOTE}", True),
    ("jrhms.jharkhand.gov.in", f"Jharkhand — {STATE_NOTE}", True),
    ("karunadu.karnataka.gov.in", f"Karnataka — {STATE_NOTE}", True),
    ("dhs.kerala.gov.in", f"Kerala — {STATE_NOTE}", True),
    ("arogyakeralam.gov.in", f"Kerala (NHM) — {STATE_NOTE}", True),
    ("health.mp.gov.in", f"Madhya Pradesh — {STATE_NOTE}", True),
    ("arogya.maharashtra.gov.in", f"Maharashtra — {STATE_NOTE}", True),
    ("manipurhealthdirectorate.mn.gov.in", f"Manipur — {STATE_NOTE}", True),
    ("meghealth.gov.in", f"Meghalaya — {STATE_NOTE}", True),
    ("health.mizoram.gov.in", f"Mizoram — {STATE_NOTE}", True),
    ("nagahealth.nagaland.gov.in", f"Nagaland — {STATE_NOTE}", True),
    ("health.odisha.gov.in", f"Odisha — {STATE_NOTE}", True),
    ("nhm.punjab.gov.in", f"Punjab — {STATE_NOTE}", True),
    ("rajswasthya.nic.in", f"Rajasthan — {STATE_NOTE}", True),
    ("health.sikkim.gov.in", f"Sikkim — {STATE_NOTE}", True),
    ("tnhealth.tn.gov.in", f"Tamil Nadu — {STATE_NOTE}", True),
    ("hmfw.telangana.gov.in", f"Telangana — {STATE_NOTE}", True),
    ("health.tripura.gov.in", f"Tripura — {STATE_NOTE}", True),
    ("upnrhm.gov.in", f"Uttar Pradesh — {STATE_NOTE}", True),
    ("health.uk.gov.in", f"Uttarakhand — {STATE_NOTE}", True),
    ("wbhealth.gov.in", f"West Bengal — {STATE_NOTE}", True),
    ("health.delhi.gov.in", f"Delhi — {STATE_NOTE}", True),

    # ---------------- Band C — institutional protocols ----------------
    ("aiims.edu", f"AIIMS New Delhi — {INST_NOTE}", True),
    ("pgimer.edu.in", f"PGIMER Chandigarh — {INST_NOTE}", True),
    ("cmch-vellore.edu", f"CMC Vellore — {INST_NOTE}", True),
    ("sctimst.ac.in", f"SCTIMST Trivandrum — {INST_NOTE}", True),
    ("tmc.gov.in", f"Tata Memorial Centre — {INST_NOTE}", True),
    ("actrec.gov.in", f"ACTREC, Tata Memorial — {INST_NOTE}", True),
    ("nimhans.ac.in", f"NIMHANS Bengaluru — {INST_NOTE}", True),
    ("jipmer.edu.in", f"JIPMER Puducherry — {INST_NOTE}", True),
    ("sgpgi.ac.in", f"SGPGI Lucknow — {INST_NOTE}", True),
    ("rgcirc.org", f"Rajiv Gandhi Cancer Institute — {INST_NOTE}", True),
    ("aiimsbhopal.edu.in", f"AIIMS Bhopal — {INST_NOTE}", True),
    ("aiimsjodhpur.edu.in", f"AIIMS Jodhpur — {INST_NOTE}", True),
    ("aiimsbhubaneswar.nic.in", f"AIIMS Bhubaneswar — {INST_NOTE}", True),
    ("aiimsrishikesh.edu.in", f"AIIMS Rishikesh — {INST_NOTE}", True),
    ("aiimspatna.edu.in", f"AIIMS Patna — {INST_NOTE}", True),
    ("aiimsraipur.edu.in", f"AIIMS Raipur — {INST_NOTE}", True),
    ("aiimsnagpur.edu.in", f"AIIMS Nagpur — {INST_NOTE}", True),
    ("kgmu.org", f"King George's Medical University, Lucknow — {INST_NOTE}", True),
    ("bhu.ac.in", f"IMS-BHU Varanasi — {INST_NOTE}", True),
    ("maulanaazadmedicalcollege.in", f"Maulana Azad Medical College — {INST_NOTE}", True),
    ("grantmedicalcollege.org", f"Grant Medical College, Mumbai — {INST_NOTE}", True),
    ("mgims.ac.in", f"MGIMS Sevagram — {INST_NOTE}", True),
    ("stjohns.in", f"St John's Medical College, Bengaluru — {INST_NOTE}", True),
    ("kasturbahospital.org", f"Kasturba Medical College, Manipal — {INST_NOTE}", True),
    ("amrita.edu", f"Amrita Institute of Medical Sciences — {INST_NOTE}", True),

    # ---------------- Band C — further societies & bodies ----------------
    ("nbtc.naco.gov.in", "National Blood Transfusion Council.", True),
    ("pcindia.org", "Poison Control network (verify).", True),
    ("ipsindia.org", "Indian Pharmacological Society.", True),
    ("iapsmindia.org", "Indian Association of Preventive & Social Medicine.", True),
    ("iamrindia.org", "Indian Association of Medical Microbiologists.", True),
    ("ihsindia.org", "Indian Headache Society.", True),
    ("rheumatologyindia.org", "Indian Rheumatology Association.", True),
    ("ihsociety.org", "Indian Hepatology / related society.", True),
    ("apiindia-journal.org", "API journal properties.", True),
    ("icogonline.org", "Indian College of Obstetricians & Gynaecologists.", True),
    ("nnfi.org", "National Neonatology Forum of India.", True),
    ("iapneocon.org", "IAP Neonatology chapter.", True),
    ("pediatriconcall.com", "Paediatric clinical reference (commercial — review carefully).", True),
    ("ipsn.org.in", "Indian Paediatric Nephrology group.", True),
    ("isham-india.org", "Indian medical mycology society.", True),
    ("tsi-india.org", "Transplantation Society of India.", True),
    ("issindia.org", "Indian Society of Surgeons / related.", True),
    ("vsi-india.org", "Vascular Society of India.", True),
    ("cardiologysocietyindia.org", "Cardiology society alternate host.", True),
    ("iheartindia.org", "Cardiac society (verify).", True),
    ("isvsindia.org", "Indian Society for Vascular Surgery.", True),
    ("iabsindia.org", "Indian Association of Biomedical Scientists.", True),
    ("acbindia.org", "Association of Clinical Biochemists of India.", True),
    ("ismrindia.org", "Indian Society for Magnetic Resonance.", True),
    ("aroi.org", "Association of Radiation Oncologists of India.", True),
    ("ismpoindia.org", "Indian Society of Medical & Paediatric Oncology.", True),
    ("ihcs.org.in", "Indian Haematology / cancer society.", True),
    ("isdindia.org", "Indian Society of Diabetology.", True),
    ("esiendocrine.org", "Endocrine society alternate host.", True),
    ("iosindia.org", "Indian Osteoporosis Society.", True),
    ("igsindia.org", "Indian Geriatrics Society.", True),
    ("ipaindia.org", "Indian Psychiatric / palliative association (verify which).", True),
    ("palliativecare.in", "Indian Association of Palliative Care.", True),
    ("painsocietyindia.org", "Indian Society for Study of Pain.", True),
    ("sleepindia.org", "Indian Society for Sleep Research.", True),
    ("epilepsyindia.org", "Indian Epilepsy Society.", True),
    ("strokeindia.org", "Indian Stroke Association.", True),
    ("mnjinstitute.org", "MNJ Institute of Oncology, Hyderabad.", True),
    ("cancerindia.org.in", "Indian Cancer Society.", True),
    ("tbassociation.org", "Tuberculosis Association of India.", True),
    ("lepraindia.org", "Leprosy programme / association.", True),

    # ---------------- AYUSH — out of MVP scope, keep disabled ----------------
    ("ayush.gov.in", "Ministry of Ayush — OUT OF SCOPE: corpus is modern/allopathic only. Enable only if a labelled AYUSH mode ships.", False),
    ("ccras.nic.in", "Central Council for Research in Ayurvedic Sciences — OUT OF SCOPE, same exclusion as ayush.gov.in.", False),
    ("ccrhindia.nic.in", "Central Council for Research in Homoeopathy — OUT OF SCOPE, same exclusion as ayush.gov.in.", False),
]

# Entry 157 in the source list, "aiims.edu/aiims/departments/poison", is a page
# path rather than a domain; allowed_domains takes hosts only, and aiims.edu is
# already present above, so it is intentionally not repeated here.


# ============================================================================
# INTERNATIONAL — searched only when Indian sources do not answer.
#
# Pramana's promise is that an answer is traceable to Indian literature, and
# the PRD's premise is that general models wrongly default to Western guidance
# whose dosing, drug availability and epidemiology may not match Indian
# practice. These sources are therefore a labelled fallback, never mixed
# silently into an "Indian" answer: every citation carries its region, and an
# answer grounded here is badged International.
# ============================================================================
_INTERNATIONAL: list[tuple[str, str, bool]] = [
    # --- literature aggregators (the workhorses) ---
    ("pmc.ncbi.nlm.nih.gov", "PubMed Central — open-access full-text biomedical literature.", True),
    ("pubmed.ncbi.nlm.nih.gov", "PubMed — indexed biomedical abstracts.", True),
    ("cochranelibrary.com", "Cochrane — systematic reviews & meta-analyses.", True),
    ("ncbi.nlm.nih.gov", "NCBI — StatPearls, Bookshelf, GeneReviews.", True),
    ("clinicaltrials.gov", "US trial registry.", True),
    ("crd.york.ac.uk", "PROSPERO — systematic review registry.", True),
    ("epistemonikos.org", "Evidence synthesis database.", True),
    ("tripdatabase.com", "Clinical evidence search.", True),
    ("guidelinecentral.com", "Guideline aggregator.", True),
    ("magicevidence.org", "MAGIC — living guidelines.", True),

    # --- global & national public health bodies ---
    ("who.int", "World Health Organization — global guidance & essential medicines.", True),
    ("cdc.gov", "US CDC — infectious disease & prevention guidance.", True),
    ("ecdc.europa.eu", "European CDC.", True),
    ("nih.gov", "US National Institutes of Health.", True),
    ("nhs.uk", "UK NHS — clinical information.", True),
    ("gov.uk", "UK government — UKHSA guidance.", True),
    ("paho.org", "Pan American Health Organization.", True),
    ("unaids.org", "UNAIDS — HIV policy & guidance.", True),
    ("theunion.org", "International Union Against TB and Lung Disease.", True),
    ("globalfund.org", "Global Fund — programme guidance.", True),

    # --- guideline development bodies ---
    ("nice.org.uk", "NICE (UK) — evidence-based clinical guidelines.", True),
    ("sign.ac.uk", "SIGN (Scotland) — clinical guidelines.", True),
    ("uspreventiveservicestaskforce.org", "USPSTF — prevention recommendations.", True),
    ("guidelines.gov", "US guideline clearinghouse — may be retired; verify before enabling.", True),
    ("g-i-n.net", "Guidelines International Network.", True),
    ("magicapp.org", "MAGICapp — guideline publication platform.", True),
    ("cadth.ca", "CADTH (Canada) — HTA & drug reviews.", True),
    ("sbu.se", "SBU (Sweden) — HTA.", True),
    ("awmf.org", "AWMF (Germany) — guideline register.", True),
    ("has-sante.fr", "HAS (France) — health authority guidance.", True),

    # --- drug regulators & formularies ---
    ("fda.gov", "US FDA — approvals, labels, safety communications.", True),
    ("ema.europa.eu", "European Medicines Agency.", True),
    ("mhra.gov.uk", "UK MHRA — drug safety.", True),
    ("bnf.org", "British National Formulary.", True),
    ("bnfc.nice.org.uk", "BNF for Children.", True),
    ("dailymed.nlm.nih.gov", "DailyMed — US drug labelling.", True),
    ("medsafe.govt.nz", "Medsafe (New Zealand).", True),
    ("tga.gov.au", "TGA (Australia).", True),
    ("hc-sc.gc.ca", "Health Canada.", True),
    ("pmda.go.jp", "PMDA (Japan).", True),

    # --- cardiovascular ---
    ("escardio.org", "European Society of Cardiology.", True),
    ("acc.org", "American College of Cardiology.", True),
    ("heart.org", "American Heart Association.", True),
    ("ahajournals.org", "AHA journals.", True),
    ("hrsonline.org", "Heart Rhythm Society.", True),
    ("eshonline.org", "European Society of Hypertension.", True),
    ("ish-world.com", "International Society of Hypertension.", True),
    ("world-heart-federation.org", "World Heart Federation.", True),

    # --- endocrine & diabetes ---
    ("diabetes.org", "ADA — Standards of Care.", True),
    ("easd.org", "European Association for the Study of Diabetes.", True),
    ("idf.org", "International Diabetes Federation.", True),
    ("endocrine.org", "Endocrine Society.", True),
    ("aace.com", "AACE.", True),
    ("thyroid.org", "American Thyroid Association.", True),
    ("eurothyroid.com", "European Thyroid Association.", True),

    # --- nephrology ---
    ("kdigo.org", "KDIGO guidelines.", True),
    ("kidney.org", "KDOQI / National Kidney Foundation.", True),
    ("era-online.org", "European Renal Association.", True),
    ("asn-online.org", "American Society of Nephrology.", True),
    ("theisn.org", "International Society of Nephrology.", True),

    # --- respiratory ---
    ("ginasthma.org", "GINA — asthma.", True),
    ("goldcopd.org", "GOLD — COPD.", True),
    ("ersnet.org", "European Respiratory Society.", True),
    ("thoracic.org", "American Thoracic Society.", True),
    ("brit-thoracic.org.uk", "British Thoracic Society.", True),

    # --- infectious disease & AMR ---
    ("idsociety.org", "IDSA.", True),
    ("escmid.org", "ESCMID.", True),
    ("eucast.org", "EUCAST — susceptibility breakpoints.", True),
    ("clsi.org", "CLSI standards.", True),
    ("hivinfo.nih.gov", "HIV/ART guidelines (NIH).", True),
    ("iasusa.org", "IAS-USA.", True),
    ("sepsis.org", "Sepsis Alliance.", True),
    ("sccm.org", "Society of Critical Care Medicine — Surviving Sepsis.", True),

    # --- oncology ---
    ("nccn.org", "NCCN guidelines.", True),
    ("esmo.org", "ESMO.", True),
    ("asco.org", "ASCO.", True),
    ("cancer.gov", "NCI — PDQ.", True),
    ("uicc.org", "Union for International Cancer Control.", True),
    ("iarc.who.int", "IARC.", True),
    ("sabcs.org", "San Antonio Breast Cancer Symposium (verify).", True),

    # --- gastroenterology & hepatology ---
    ("easl.eu", "EASL.", True),
    ("aasld.org", "AASLD.", True),
    ("gastro.org", "American Gastroenterological Association.", True),
    ("gi.org", "American College of Gastroenterology.", True),
    ("ueg.eu", "United European Gastroenterology.", True),
    ("worldgastroenterology.org", "WGO — global guidelines.", True),

    # --- neurology & psychiatry ---
    ("aan.com", "American Academy of Neurology.", True),
    ("ean.org", "European Academy of Neurology.", True),
    ("ilae.org", "International League Against Epilepsy.", True),
    ("stroke.org", "American Stroke Association.", True),
    ("world-stroke.org", "World Stroke Organization.", True),
    ("psychiatry.org", "American Psychiatric Association.", True),
    ("ihs-headache.org", "International Headache Society — classification.", True),
    ("movementdisorders.org", "International Parkinson & Movement Disorder Society.", True),

    # --- obstetrics, gynaecology & paediatrics ---
    ("acog.org", "ACOG.", True),
    ("rcog.org.uk", "RCOG.", True),
    ("figo.org", "FIGO.", True),
    ("aap.org", "American Academy of Pediatrics.", True),
    ("rcpch.ac.uk", "RCPCH.", True),

    # --- surgery, anaesthesia & critical care ---
    ("facs.org", "American College of Surgeons.", True),
    ("rcseng.ac.uk", "Royal College of Surgeons of England.", True),
    ("esicm.org", "European Society of Intensive Care Medicine.", True),
    ("asahq.org", "American Society of Anesthesiologists.", True),
    ("esahq.org", "European Society of Anaesthesiology.", True),
    ("aagbi.org", "AAGBI.", True),
    ("atls.org", "ATLS (verify).", True),

    # --- other specialties ---
    ("rheumatology.org", "American College of Rheumatology.", True),
    ("eular.org", "EULAR.", True),
    ("aad.org", "American Academy of Dermatology.", True),
    ("aao.org", "American Academy of Ophthalmology.", True),
    ("entnet.org", "American Academy of Otolaryngology.", True),
    ("auanet.org", "American Urological Association.", True),
    ("aaos.org", "American Academy of Orthopaedic Surgeons.", True),
    ("hematology.org", "American Society of Hematology.", True),
    ("ehaweb.org", "European Hematology Association.", True),
    ("isth.org", "ISTH — thrombosis & haemostasis.", True),
    ("acr.org", "American College of Radiology.", True),
    ("myesr.org", "European Society of Radiology.", True),
    ("snmmi.org", "SNMMI — nuclear medicine.", True),
    ("astro.org", "ASTRO — radiation oncology.", True),

    # --- major journals (largely paywalled: expect abstract-level retrieval) ---
    ("nejm.org", "NEJM — substantially paywalled; expect abstract-level retrieval.", True),
    ("thelancet.com", "The Lancet — substantially paywalled; expect abstract-level retrieval.", True),
    ("bmj.com", "The BMJ — substantially paywalled; expect abstract-level retrieval.", True),
    ("jamanetwork.com", "JAMA Network — substantially paywalled; expect abstract-level retrieval.", True),
    ("annals.org", "Annals of Internal Medicine — substantially paywalled.", True),
    ("nature.com", "Nature (incl. Nature Medicine) — substantially paywalled.", True),
]

# Region-tagged master list: (domain, trust_note, enabled, region)
SEED_DOMAINS: list[tuple[str, str, bool, str]] = (
    [(d, n, e, "IN") for d, n, e in _INDIAN]
    + [(d, n, e, "INTL") for d, n, e in _INTERNATIONAL]
)
