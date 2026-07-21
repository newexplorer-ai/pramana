# Pramana allowlist — for shortening

Live export from production, 322 enabled domains.

**How to use this:** delete the lines you don't want and hand the file back.
Anything still present is kept. I'll apply it to `server/seed_domains.py` and to
the production database.

## Why shorten

The search API rejects more than **100 domains** in one call. A longer pool is
split into batches — batch 1 is searched first, and batch 2 runs only if batch 1
returns nothing usable. A domain in batch 2 is a second-class source: consulted
only after the first 100 have already failed. Lines marked ⚠︎ **batch 2** are
in that position today.

Getting each list to 100 or fewer means one search per region, lower latency,
and no hidden ranking.

**Order is priority** — earlier is searched first. Reordering is as useful as cutting.

| list | enabled | target | must cut |
|---|---|---|---|
| Indian | 196 | 100 | **96** |
| International | 126 | 100 | **26** |

The two lists are independent — each gets its own search — so cutting Indian
sources does not make room for international ones.

---

## Indian sources

Searched first on every question. An Indian-grounded answer is never displaced by international literature.

**196 enabled.** Needs to lose **96** to fit one search pass.

| group | count |
|---|---|
| Government, regulatory & national programmes | 45 |
| ICMR institutes | 11 |
| Journals | 30 |
| Professional societies & councils | 55 |
| State health departments | 30 |
| Hospital & institute protocols | 25 |

### Government, regulatory & national programmes  (45)

- `main.mohfw.gov.in` — Ministry of Health & Family Welfare — official policy & STGs.
- `cdsco.gov.in` — Central Drugs Standard Control Organisation — drug approvals & safety.
- `mohfw.gov.in` — Ministry of Health & Family Welfare — primary ministry domain.
- `clinicalestablishments.mohfw.gov.in` — MoHFW Clinical Establishments Act — STGs by specialty.
- `dghs.mohfw.gov.in` — Directorate General of Health Services — apex technical advisory body.
- `ncdc.gov.in` — National Centre for Disease Control — outbreak, AMR & communicable disease.
- `ncdc.mohfw.gov.in` — NCDC under DGHS — surveillance & outbreak documentation.
- `ihip.mohfw.gov.in` — Integrated Health Information Platform — national disease surveillance.
- `ncdirindia.org` — National Centre for Disease Informatics & Research — cancer registry.
- `niirncd.icmr.org.in` — ICMR National Institute of Health Research, Jodhpur — NCD research.
- `ncahp.abdm.gov.in` — National Commission for Allied & Healthcare Professions.
- `nmc.org.in` — National Medical Commission — medical education & practice regulation.
- `pharmacopoeia.org.in` — Indian Pharmacopoeia Commission — IP monographs & pharmacovigilance.
- `nvbdcp.gov.in` — National Centre for Vector Borne Diseases Control — malaria, dengue, kala-azar.
- `nhp.gov.in` — National Health Portal — MoHFW health information.
- `nihfw.ac.in` — National Institute of Health & Family Welfare — public health training.
- `ctri.nic.in` — Clinical Trials Registry — India.
- `nppaindia.nic.in` — National Pharmaceutical Pricing Authority — drug price control.
- `fssai.gov.in` — Food Safety & Standards Authority of India.
- `notto.mohfw.gov.in` — National Organ & Tissue Transplant Organisation.
- `nabh.co` — NABH — hospital accreditation standards.
- `nhsrcindia.org` — National Health Systems Resource Centre — health systems guidance.
- `nha.gov.in` — National Health Authority — Ayushman Bharat implementation.
- `cghs.gov.in` — Central Government Health Scheme — protocols & formulary.
- `rchiips.org` — IIPS — National Family Health Survey reports.
- `iipsindia.ac.in` — International Institute for Population Sciences — health demography.
- `abdm.gov.in` — Ayushman Bharat Digital Mission — health data standards.
- `nbe.edu.in` — National Board of Examinations — postgraduate medical standards.
- `iadvl.org` — IADVL — dermatology practice guidance.
- `censusindia.gov.in` — Registrar General — Sample Registration System vital statistics.
- `ipc.gov.in` — Indian Pharmacopoeia Commission — alternate host.
- `pcindia.org` — Poison Control network (verify).  ·  ⚠︎ batch 2
- `ihsociety.org` — Indian Hepatology / related society.  ·  ⚠︎ batch 2
- `nnfi.org` — National Neonatology Forum of India.  ·  ⚠︎ batch 2
- `iapneocon.org` — IAP Neonatology chapter.  ·  ⚠︎ batch 2
- `pediatriconcall.com` — Paediatric clinical reference (commercial — review carefully).  ·  ⚠︎ batch 2
- `ipsn.org.in` — Indian Paediatric Nephrology group.  ·  ⚠︎ batch 2
- `isham-india.org` — Indian medical mycology society.  ·  ⚠︎ batch 2
- `cardiologysocietyindia.org` — Cardiology society alternate host.  ·  ⚠︎ batch 2
- `iheartindia.org` — Cardiac society (verify).  ·  ⚠︎ batch 2
- `ihcs.org.in` — Indian Haematology / cancer society.  ·  ⚠︎ batch 2
- `esiendocrine.org` — Endocrine society alternate host.  ·  ⚠︎ batch 2
- `ipaindia.org` — Indian Psychiatric / palliative association (verify which).  ·  ⚠︎ batch 2
- `mnjinstitute.org` — MNJ Institute of Oncology, Hyderabad.  ·  ⚠︎ batch 2
- `lepraindia.org` — Leprosy programme / association.  ·  ⚠︎ batch 2

### ICMR institutes  (11)

- `nin.res.in` — National Institute of Nutrition (ICMR) — dietary guidelines & RDA.
- `niv.co.in` — National Institute of Virology, Pune (ICMR) — virology reference.
- `nirt.res.in` — National Institute for Research in Tuberculosis (ICMR).
- `nirrch.res.in` — National Institute for Research in Reproductive & Child Health (ICMR).
- `nimr.org.in` — National Institute of Malaria Research (ICMR).
- `nicpr.res.in` — National Institute of Cancer Prevention & Research (ICMR).
- `nie.gov.in` — National Institute of Epidemiology (ICMR).
- `nariindia.org` — National AIDS Research Institute (ICMR).
- `rmrims.org.in` — Rajendra Memorial Research Institute of Medical Sciences (ICMR).
- `niohenv.res.in` — National Institute of Occupational Health (ICMR).
- `nirth.res.in` — National Institute of Research in Tribal Health (ICMR).

### Journals  (30)

- `ijmr.org.in` — Indian Journal of Medical Research — ICMR peer-reviewed journal.
- `nmji.in` — National Medical Journal of India — peer-reviewed, AIIMS-affiliated.
- `indianpediatrics.net` — Indian Pediatrics — IAP official journal.
- `jiaps.com` — Journal of Indian Association of Pediatric Surgeons.
- `japi.org` — Journal of the Association of Physicians of India.
- `ijp-online.com` — Indian Journal of Pharmacology — IPS journal.
- `ijmm.org` — Indian Journal of Medical Microbiology — IAMM journal.
- `ijdvl.com` — Indian Journal of Dermatology, Venereology & Leprology.
- `ijo.in` — Indian Journal of Ophthalmology — AIOS journal.
- `ijccm.org` — Indian Journal of Critical Care Medicine — ISCCM journal.
- `ijem.in` — Indian Journal of Endocrinology & Metabolism.
- `ijaweb.org` — Indian Journal of Anaesthesia — ISA journal.
- `cancerjournal.net` — Journal of Cancer Research & Therapeutics.
- `indianjnephrol.org` — Indian Journal of Nephrology — ISN journal.
- `indianjpsychiatry.org` — Indian Journal of Psychiatry — IPS journal.
- `lungindia.com` — Lung India — Indian Chest Society journal.
- `jpgmonline.com` — Journal of Postgraduate Medicine — KEM Hospital, Mumbai.
- `jcdr.net` — Journal of Clinical & Diagnostic Research.
- `ijri.org` — Indian Journal of Radiology & Imaging — IRIA journal.
- `ijcm.org.in` — Indian Journal of Community Medicine — IAPSM journal.
- `jfmpc.com` — Journal of Family Medicine & Primary Care.
- `ijpmonline.org` — Indian Journal of Pathology & Microbiology.
- `jogi.co.in` — Journal of Obstetrics & Gynaecology of India — FOGSI.
- `ijhg.com` — Indian Journal of Human Genetics.
- `jgid.org` — Journal of Global Infectious Diseases.
- `ijstd.org` — Indian Journal of Sexually Transmitted Diseases & AIDS.
- `e-ijd.org` — Indian Journal of Dermatology.
- `ijmpo.org` — Indian Journal of Medical & Paediatric Oncology.
- `jpn.co.in` — Journal of Pediatric Neurosciences.
- `apiindia-journal.org` — API journal properties.  ·  ⚠︎ batch 2

### Professional societies & councils  (55)

- `icmr.gov.in` — Indian Council of Medical Research — apex national research & guideline body.
- `main.icmr.nic.in` — ICMR legacy host — Standard Treatment Workflows & guideline archive.
- `nhm.gov.in` — National Health Mission — programme guidelines & training modules.
- `tbcindia.gov.in` — National TB Elimination Programme — TB diagnosis & treatment guidelines.
- `naco.gov.in` — National AIDS Control Organisation — HIV testing & ART guidelines.
- `pmjay.gov.in` — PM-JAY — treatment package guidelines & rates.
- `indiannursingcouncil.org` — Indian Nursing Council — nursing practice standards.
- `neurologyindia.com` — Neurology India — Neurological Society of India.
- `iapindia.org` — Indian Academy of Pediatrics — immunisation schedule & guidelines.
- `csi.org.in` — Cardiological Society of India — consensus statements.
- `rssdi.in` — RSSDI — diabetes guidelines (consensus, not statutory).
- `apiindia.org` — Association of Physicians of India — internal medicine guidance.
- `fogsi.org` — FOGSI — obstetric & gynaecological good practice recommendations.
- `isnindia.org` — Indian Society of Nephrology — specialty guidance.
- `indianchestsociety.org` — Indian Chest Society — respiratory consensus guidelines.
- `isccm.org` — Indian Society of Critical Care Medicine — ICU guidelines.
- `isaweb.in` — Indian Society of Anaesthesiologists — perioperative guidance.
- `iria.org.in` — Indian Radiological & Imaging Association — imaging standards.
- `asiindia.org` — Association of Surgeons of India — surgical guidance.
- `indianpsychiatricsociety.org` — Indian Psychiatric Society — clinical practice guidelines.
- `iansindia.org` — Indian Academy of Neurology — consensus guidance.
- `isgindia.org` — Indian Society of Gastroenterology — GI practice guidance.
- `inasl.org.in` — INASL — hepatology consensus statements.
- `aios.org` — All India Ophthalmological Society.
- `ioaindia.org` — Indian Orthopaedic Association.
- `usiindia.org` — Urological Society of India.
- `endocrinesocietyindia.org` — Endocrine Society of India — consensus statements.
- `nsi.org.in` — Neurological Society of India.
- `dciindia.gov.in` — Dental Council of India.
- `nbtc.naco.gov.in` — National Blood Transfusion Council.  ·  ⚠︎ batch 2
- `ipsindia.org` — Indian Pharmacological Society.  ·  ⚠︎ batch 2
- `iapsmindia.org` — Indian Association of Preventive & Social Medicine.  ·  ⚠︎ batch 2
- `iamrindia.org` — Indian Association of Medical Microbiologists.  ·  ⚠︎ batch 2
- `ihsindia.org` — Indian Headache Society.  ·  ⚠︎ batch 2
- `rheumatologyindia.org` — Indian Rheumatology Association.  ·  ⚠︎ batch 2
- `icogonline.org` — Indian College of Obstetricians & Gynaecologists.  ·  ⚠︎ batch 2
- `tsi-india.org` — Transplantation Society of India.  ·  ⚠︎ batch 2
- `issindia.org` — Indian Society of Surgeons / related.  ·  ⚠︎ batch 2
- `vsi-india.org` — Vascular Society of India.  ·  ⚠︎ batch 2
- `isvsindia.org` — Indian Society for Vascular Surgery.  ·  ⚠︎ batch 2
- `iabsindia.org` — Indian Association of Biomedical Scientists.  ·  ⚠︎ batch 2
- `acbindia.org` — Association of Clinical Biochemists of India.  ·  ⚠︎ batch 2
- `ismrindia.org` — Indian Society for Magnetic Resonance.  ·  ⚠︎ batch 2
- `aroi.org` — Association of Radiation Oncologists of India.  ·  ⚠︎ batch 2
- `ismpoindia.org` — Indian Society of Medical & Paediatric Oncology.  ·  ⚠︎ batch 2
- `isdindia.org` — Indian Society of Diabetology.  ·  ⚠︎ batch 2
- `iosindia.org` — Indian Osteoporosis Society.  ·  ⚠︎ batch 2
- `igsindia.org` — Indian Geriatrics Society.  ·  ⚠︎ batch 2
- `palliativecare.in` — Indian Association of Palliative Care.  ·  ⚠︎ batch 2
- `painsocietyindia.org` — Indian Society for Study of Pain.  ·  ⚠︎ batch 2
- `sleepindia.org` — Indian Society for Sleep Research.  ·  ⚠︎ batch 2
- `epilepsyindia.org` — Indian Epilepsy Society.  ·  ⚠︎ batch 2
- `strokeindia.org` — Indian Stroke Association.  ·  ⚠︎ batch 2
- `cancerindia.org.in` — Indian Cancer Society.  ·  ⚠︎ batch 2
- `tbassociation.org` — Tuberculosis Association of India.  ·  ⚠︎ batch 2

### State health departments  (30)

- `hmfw.ap.gov.in` — Andhra Pradesh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.arunachal.gov.in` — Arunachal Pradesh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `nhm.assam.gov.in` — Assam — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `shsb.bihar.gov.in` — Bihar — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `cghealth.nic.in` — Chhattisgarh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.goa.gov.in` — Goa — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `gujhealth.gujarat.gov.in` — Gujarat — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `haryanahealth.nic.in` — Haryana — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `nrhmhp.gov.in` — Himachal Pradesh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `jrhms.jharkhand.gov.in` — Jharkhand — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `karunadu.karnataka.gov.in` — Karnataka — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `dhs.kerala.gov.in` — Kerala — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `arogyakeralam.gov.in` — Kerala (NHM) — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.mp.gov.in` — Madhya Pradesh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `arogya.maharashtra.gov.in` — Maharashtra — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `manipurhealthdirectorate.mn.gov.in` — Manipur — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `meghealth.gov.in` — Meghalaya — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.mizoram.gov.in` — Mizoram — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `nagahealth.nagaland.gov.in` — Nagaland — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.odisha.gov.in` — Odisha — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `nhm.punjab.gov.in` — Punjab — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `rajswasthya.nic.in` — Rajasthan — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.sikkim.gov.in` — Sikkim — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `tnhealth.tn.gov.in` — Tamil Nadu — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `hmfw.telangana.gov.in` — Telangana — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.tripura.gov.in` — Tripura — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `upnrhm.gov.in` — Uttar Pradesh — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.uk.gov.in` — Uttarakhand — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `wbhealth.gov.in` — West Bengal — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2
- `health.delhi.gov.in` — Delhi — State health department — state guidance; may differ from national policy.  ·  ⚠︎ batch 2

### Hospital & institute protocols  (25)

- `aiims.edu` — AIIMS New Delhi — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `pgimer.edu.in` — PGIMER Chandigarh — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `cmch-vellore.edu` — CMC Vellore — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `sctimst.ac.in` — SCTIMST Trivandrum — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `tmc.gov.in` — Tata Memorial Centre — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `actrec.gov.in` — ACTREC, Tata Memorial — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `nimhans.ac.in` — NIMHANS Bengaluru — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `jipmer.edu.in` — JIPMER Puducherry — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `sgpgi.ac.in` — SGPGI Lucknow — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `rgcirc.org` — Rajiv Gandhi Cancer Institute — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsbhopal.edu.in` — AIIMS Bhopal — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsjodhpur.edu.in` — AIIMS Jodhpur — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsbhubaneswar.nic.in` — AIIMS Bhubaneswar — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsrishikesh.edu.in` — AIIMS Rishikesh — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimspatna.edu.in` — AIIMS Patna — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsraipur.edu.in` — AIIMS Raipur — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `aiimsnagpur.edu.in` — AIIMS Nagpur — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `kgmu.org` — King George's Medical University, Lucknow — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `bhu.ac.in` — IMS-BHU Varanasi — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `maulanaazadmedicalcollege.in` — Maulana Azad Medical College — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `grantmedicalcollege.org` — Grant Medical College, Mumbai — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `mgims.ac.in` — MGIMS Sevagram — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `stjohns.in` — St John's Medical College, Bengaluru — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `kasturbahospital.org` — Kasturba Medical College, Manipal — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2
- `amrita.edu` — Amrita Institute of Medical Sciences — Institutional protocol; local practice, not national policy.  ·  ⚠︎ batch 2

### Currently disabled (3) — not searched at all

- `ayush.gov.in` — Ministry of Ayush — OUT OF SCOPE: corpus is modern/allopathic only. Enable only if a labelled AYUSH mode ships.
- `ccras.nic.in` — Central Council for Research in Ayurvedic Sciences — OUT OF SCOPE, same exclusion as ayush.gov.in.
- `ccrhindia.nic.in` — Central Council for Research in Homoeopathy — OUT OF SCOPE, same exclusion as ayush.gov.in.

---

## International sources

Only searched when no Indian source can answer. Answers from these are badged *International*, and are refused outright for dosing, drug availability, NLEM status, or national programme protocols.

**126 enabled.** Needs to lose **26** to fit one search pass.

| group | count |
|---|---|
| Evidence synthesis & registries | 7 |
| Guideline bodies | 13 |
| Literature databases & journals | 7 |
| Specialty & other | 99 |

### Evidence synthesis & registries  (7)

- `cochranelibrary.com` — Cochrane — systematic reviews & meta-analyses.
- `ncbi.nlm.nih.gov` — NCBI — StatPearls, Bookshelf, GeneReviews.
- `clinicaltrials.gov` — US trial registry.
- `crd.york.ac.uk` — PROSPERO — systematic review registry.
- `epistemonikos.org` — Evidence synthesis database.
- `tripdatabase.com` — Clinical evidence search.
- `cadth.ca` — CADTH (Canada) — HTA & drug reviews.

### Guideline bodies  (13)

- `guidelinecentral.com` — Guideline aggregator.
- `magicevidence.org` — MAGIC — living guidelines.
- `nice.org.uk` — NICE (UK) — evidence-based clinical guidelines.
- `sign.ac.uk` — SIGN (Scotland) — clinical guidelines.
- `uspreventiveservicestaskforce.org` — USPSTF — prevention recommendations.
- `guidelines.gov` — US guideline clearinghouse — may be retired; verify before enabling.
- `g-i-n.net` — Guidelines International Network.
- `magicapp.org` — MAGICapp — guideline publication platform.
- `awmf.org` — AWMF (Germany) — guideline register.
- `kdigo.org` — KDIGO guidelines.
- `hivinfo.nih.gov` — HIV/ART guidelines (NIH).
- `nccn.org` — NCCN guidelines.
- `worldgastroenterology.org` — WGO — global guidelines.

### Literature databases & journals  (7)

- `pmc.ncbi.nlm.nih.gov` — PubMed Central — open-access full-text biomedical literature.
- `pubmed.ncbi.nlm.nih.gov` — PubMed — indexed biomedical abstracts.
- `ahajournals.org` — AHA journals.
- `nejm.org` — NEJM — substantially paywalled; expect abstract-level retrieval.  ·  ⚠︎ batch 2
- `thelancet.com` — The Lancet — substantially paywalled; expect abstract-level retrieval.  ·  ⚠︎ batch 2
- `bmj.com` — The BMJ — substantially paywalled; expect abstract-level retrieval.  ·  ⚠︎ batch 2
- `jamanetwork.com` — JAMA Network — substantially paywalled; expect abstract-level retrieval.  ·  ⚠︎ batch 2

### Specialty & other  (99)

- `who.int` — World Health Organization — global guidance & essential medicines.
- `cdc.gov` — US CDC — infectious disease & prevention guidance.
- `ecdc.europa.eu` — European CDC.
- `nih.gov` — US National Institutes of Health.
- `nhs.uk` — UK NHS — clinical information.
- `gov.uk` — UK government — UKHSA guidance.
- `paho.org` — Pan American Health Organization.
- `unaids.org` — UNAIDS — HIV policy & guidance.
- `theunion.org` — International Union Against TB and Lung Disease.
- `globalfund.org` — Global Fund — programme guidance.
- `sbu.se` — SBU (Sweden) — HTA.
- `has-sante.fr` — HAS (France) — health authority guidance.
- `fda.gov` — US FDA — approvals, labels, safety communications.
- `ema.europa.eu` — European Medicines Agency.
- `mhra.gov.uk` — UK MHRA — drug safety.
- `bnf.org` — British National Formulary.
- `bnfc.nice.org.uk` — BNF for Children.
- `dailymed.nlm.nih.gov` — DailyMed — US drug labelling.
- `medsafe.govt.nz` — Medsafe (New Zealand).
- `tga.gov.au` — TGA (Australia).
- `hc-sc.gc.ca` — Health Canada.
- `pmda.go.jp` — PMDA (Japan).
- `escardio.org` — European Society of Cardiology.
- `acc.org` — American College of Cardiology.
- `heart.org` — American Heart Association.
- `hrsonline.org` — Heart Rhythm Society.
- `eshonline.org` — European Society of Hypertension.
- `ish-world.com` — International Society of Hypertension.
- `world-heart-federation.org` — World Heart Federation.
- `diabetes.org` — ADA — Standards of Care.
- `easd.org` — European Association for the Study of Diabetes.
- `idf.org` — International Diabetes Federation.
- `endocrine.org` — Endocrine Society.
- `aace.com` — AACE.
- `thyroid.org` — American Thyroid Association.
- `eurothyroid.com` — European Thyroid Association.
- `kidney.org` — KDOQI / National Kidney Foundation.
- `era-online.org` — European Renal Association.
- `asn-online.org` — American Society of Nephrology.
- `theisn.org` — International Society of Nephrology.
- `ginasthma.org` — GINA — asthma.
- `goldcopd.org` — GOLD — COPD.
- `ersnet.org` — European Respiratory Society.
- `thoracic.org` — American Thoracic Society.
- `brit-thoracic.org.uk` — British Thoracic Society.
- `idsociety.org` — IDSA.
- `escmid.org` — ESCMID.
- `eucast.org` — EUCAST — susceptibility breakpoints.
- `clsi.org` — CLSI standards.
- `iasusa.org` — IAS-USA.
- `sepsis.org` — Sepsis Alliance.
- `sccm.org` — Society of Critical Care Medicine — Surviving Sepsis.
- `esmo.org` — ESMO.
- `asco.org` — ASCO.
- `cancer.gov` — NCI — PDQ.
- `uicc.org` — Union for International Cancer Control.
- `iarc.who.int` — IARC.
- `sabcs.org` — San Antonio Breast Cancer Symposium (verify).
- `easl.eu` — EASL.
- `aasld.org` — AASLD.
- `gastro.org` — American Gastroenterological Association.
- `gi.org` — American College of Gastroenterology.
- `ueg.eu` — United European Gastroenterology.
- `aan.com` — American Academy of Neurology.
- `ean.org` — European Academy of Neurology.
- `ilae.org` — International League Against Epilepsy.
- `stroke.org` — American Stroke Association.
- `world-stroke.org` — World Stroke Organization.
- `psychiatry.org` — American Psychiatric Association.
- `ihs-headache.org` — International Headache Society — classification.
- `movementdisorders.org` — International Parkinson & Movement Disorder Society.
- `acog.org` — ACOG.
- `rcog.org.uk` — RCOG.
- `figo.org` — FIGO.
- `aap.org` — American Academy of Pediatrics.
- `rcpch.ac.uk` — RCPCH.
- `facs.org` — American College of Surgeons.
- `rcseng.ac.uk` — Royal College of Surgeons of England.  ·  ⚠︎ batch 2
- `esicm.org` — European Society of Intensive Care Medicine.  ·  ⚠︎ batch 2
- `asahq.org` — American Society of Anesthesiologists.  ·  ⚠︎ batch 2
- `esahq.org` — European Society of Anaesthesiology.  ·  ⚠︎ batch 2
- `aagbi.org` — AAGBI.  ·  ⚠︎ batch 2
- `atls.org` — ATLS (verify).  ·  ⚠︎ batch 2
- `rheumatology.org` — American College of Rheumatology.  ·  ⚠︎ batch 2
- `eular.org` — EULAR.  ·  ⚠︎ batch 2
- `aad.org` — American Academy of Dermatology.  ·  ⚠︎ batch 2
- `aao.org` — American Academy of Ophthalmology.  ·  ⚠︎ batch 2
- `entnet.org` — American Academy of Otolaryngology.  ·  ⚠︎ batch 2
- `auanet.org` — American Urological Association.  ·  ⚠︎ batch 2
- `aaos.org` — American Academy of Orthopaedic Surgeons.  ·  ⚠︎ batch 2
- `hematology.org` — American Society of Hematology.  ·  ⚠︎ batch 2
- `ehaweb.org` — European Hematology Association.  ·  ⚠︎ batch 2
- `isth.org` — ISTH — thrombosis & haemostasis.  ·  ⚠︎ batch 2
- `acr.org` — American College of Radiology.  ·  ⚠︎ batch 2
- `myesr.org` — European Society of Radiology.  ·  ⚠︎ batch 2
- `snmmi.org` — SNMMI — nuclear medicine.  ·  ⚠︎ batch 2
- `astro.org` — ASTRO — radiation oncology.  ·  ⚠︎ batch 2
- `annals.org` — Annals of Internal Medicine — substantially paywalled.  ·  ⚠︎ batch 2
- `nature.com` — Nature (incl. Nature Medicine) — substantially paywalled.  ·  ⚠︎ batch 2
