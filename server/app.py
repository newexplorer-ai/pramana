"""
Praman orchestrator — FastAPI backend for the two-tier MVP.

Tiers (Tier 1/corpus was cut from scope):
  Tier 2  — grounded web answer: Anthropic web_search server tool restricted
            to the admin-maintained allowlist (`allowed_domains`), citations
            enforced by the API. Served on citation presence, no judge.
  Tier 3  — general-model fallback, clearly labelled and marked unverified.
            Always the fallback when Tier 2 finds no grounded answer.

Also owns: Google auth + beta allowlist (server-side now), admin config-as-data,
audit log, query/gap logging, saved conversations, access requests.

Run:  ANTHROPIC_API_KEY=... uvicorn app:app --port 4173 --app-dir server
The frontend is served from the repo root by this same process.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

try:
    import anthropic
except ImportError:  # surfaced as a 503 at ask-time
    anthropic = None

try:
    import openai
except ImportError:
    openai = None

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("PRAMANA_DB", str(ROOT / "server" / "pramana.db"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# On a public host, demo sign-in must not be an open door: when this is set,
# demo login additionally requires the shared beta access code.
DEMO_PASSWORD = os.environ.get("PRAMANA_DEMO_PASSWORD", "")

app = FastAPI(title="Praman API")

# ---------------------------------------------------------------- database

_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute("PRAGMA journal_mode=WAL")


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _db_lock:
        cur = _db.execute(sql, args)
        rows = cur.fetchall()
        _db.commit()
        return rows


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y")


SCHEMA = """
CREATE TABLE IF NOT EXISTS allowed_users(
  email TEXT PRIMARY KEY, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('clinician','editor','admin')),
  enabled INTEGER NOT NULL DEFAULT 1,
  added_by TEXT, created_at TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS auth_sessions(
  token TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS allowlist_domains(
  domain TEXT PRIMARY KEY, trust_note TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, added_by TEXT, created_at TEXT,
  region TEXT NOT NULL DEFAULT 'IN',
  priority INTEGER NOT NULL DEFAULT 9999);
CREATE TABLE IF NOT EXISTS app_config(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, default_value TEXT,
  description TEXT, critical INTEGER DEFAULT 0,
  updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT,
  change TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS access_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, reg TEXT,
  council TEXT, specialty TEXT, institution TEXT,
  status TEXT DEFAULT 'pending', created_at TEXT);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, user_email TEXT, title TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS turns(
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, role TEXT,
  content TEXT, tier INTEGER, result_json TEXT, query_id TEXT,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS query_logs(
  query_id TEXT PRIMARY KEY, user_email TEXT, conversation_id TEXT,
  query_text TEXT, tier INTEGER, status TEXT, high_stakes INTEGER,
  latency_ms INTEGER, model_used TEXT, feedback TEXT,
  suggested_source INTEGER DEFAULT 0, fallthrough TEXT,
  source_region TEXT, pool_outcome TEXT,
  indian_citations INTEGER, intl_citations INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS saved_conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, title TEXT,
  conversation_id TEXT, query TEXT, saved_at TEXT,
  UNIQUE(user_email, conversation_id));
"""

# Seed roles only — this runs once, on an empty database. Roles are read from
# allowed_users at request time, so promotions made in Admin → Beta access are
# authoritative and survive redeploys.
SEED_USERS = [
    ("k.prasad.iitr@gmail.com", "Dr. K. Prasad", "admin", 1, "system"),
    ("r.iyer@aiims.edu", "Dr. R. Iyer", "clinician", 1, "system"),      # test account
    ("p.nair@stjohns.in", "Dr. P. Nair", "clinician", 0, "system"),     # test account (disabled)
]
from seed_domains import CURATED, SEED_DOMAINS  # catalogue + priority order
# key, value, default, description, critical
SEED_CONFIG = [
    # One provider powers everything. Switched from Admin → Models & config.
    ("provider.active", "anthropic", "anthropic",
     "Which model provider answers questions. Requires that provider's API key.", 1),
    ("generation.effort", "medium", "medium", "Effort level for generation (low|medium|high).", 0),
    ("websearch.max_uses", "5", "5", "Tier 2 search cap per query.", 0),
    # Retrieval gate: a single stray source is not coverage. Applied to the
    # grounded path — fewer than this many distinct cited sources falls through.
    ("retrieval.min_chunks", "2", "2",
     "Minimum distinct cited sources before a grounded answer may be served.", 0),
    # Indian sources are searched first and international ones only if they
    # fail, so an Indian-grounded answer is never displaced by more abundant
    # Western guidance. 'indian_only' disables the international fallback.
    ("search.region_mode", "mixed", "indian_first",
     "indian_first (Indian pool searched alone first) | mixed (both regions in "
     "one call) | indian_only (no international fallback) | dual (two dedicated "
     "parallel searches, composed into one Indian-anchored answer).", 1),
    # Mixed mode only. Indian slots in the first call; the rest of the cap goes
    # to international. Higher = stronger Indian presence in the ranked pool.
    ("search.mixed_indian_slots", "40", "40",
     "Mixed mode: Indian sources in the first search call (rest are international).", 1),
    # Dual mode. Each pool gets its own search call (own budget the other can't
    # consume), then a compose call merges them Indian-anchored.
    ("search.dual_indian_cap", "100", "100",
     "Dual mode: max Indian domains in the Indian search call.", 0),
    ("search.dual_intl_cap", "100", "100",
     "Dual mode: max international domains in the international search call.", 0),
    ("search.dual_classifier", "true", "true",
     "Dual mode: run the retrieval-plan classifier. Off = always search both pools.", 0),
    ("cost.daily_user_cap", "40", "40", "Per-clinician query cap per day.", 0),
    ("auth.session_days", "30", "30",
     "Days a sign-in stays valid before the user must sign in again.", 0),
    ("context.max_turns", "6", "6", "Conversation depth resent per request.", 0),
]


def _migrate() -> None:
    """Additive column migrations for already-deployed databases."""
    cols = {r["name"] for r in q("PRAGMA table_info(query_logs)")}
    if "fallthrough" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN fallthrough TEXT")
    if "source_region" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN source_region TEXT")
    # Dual-pool instrumentation: which pools answered, and how many citations
    # each contributed — the record that makes the old starvation bug visible.
    if "pool_outcome" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN pool_outcome TEXT")
    if "indian_citations" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN indian_citations INTEGER")
    if "intl_citations" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN intl_citations INTEGER")
    dcols = {r["name"] for r in q("PRAGMA table_info(allowlist_domains)")}
    if "region" not in dcols:
        q("ALTER TABLE allowlist_domains ADD COLUMN region TEXT NOT NULL DEFAULT 'IN'")
    if "priority" not in dcols:
        q("ALTER TABLE allowlist_domains ADD COLUMN priority INTEGER NOT NULL DEFAULT 9999")
    # Full answer payload per assistant turn, so a conversation can be reloaded
    # with its citations intact across sessions — not just the plain text.
    tcols = {r["name"] for r in q("PRAGMA table_info(turns)")}
    if "result_json" not in tcols:
        q("ALTER TABLE turns ADD COLUMN result_json TEXT")
    # Links a turn to its query_logs row, so a question can be matched to its
    # answer even in a multi-turn thread (conversation_id alone is ambiguous).
    if "query_id" not in tcols:
        q("ALTER TABLE turns ADD COLUMN query_id TEXT")
        # Backfill: existing assistant turns carry the id inside result_json.
        q("""UPDATE turns SET query_id = json_extract(result_json,'$.query_id')
             WHERE query_id IS NULL AND result_json IS NOT NULL""")


def init_db() -> None:
    with _db_lock:
        _db.executescript(SCHEMA)
        _db.commit()
    # Columns added after first release must exist before any seeding below
    # touches them, so migrate here rather than after init.
    _migrate()
    if not q("SELECT 1 FROM allowed_users LIMIT 1"):
        for email, name, role, enabled, by in SEED_USERS:
            q("INSERT INTO allowed_users VALUES(?,?,?,?,?,?,NULL)",
              (email, name, role, enabled, by, now()))
    # Domains are additive on every boot so a curated list can grow without a
    # migration. INSERT OR IGNORE deliberately leaves existing rows untouched —
    # an admin's enable/disable decision must never be reverted by a redeploy.
    for domain, note, enabled, region in SEED_DOMAINS:
        q("""INSERT INTO allowlist_domains(domain,trust_note,enabled,added_by,created_at,region)
             VALUES(?,?,?,'system',?,?)
             ON CONFLICT(domain) DO UPDATE SET region=excluded.region""",
          (domain, note, 1 if enabled else 0, now(), region))
    # Priority is editorial, not operational, so unlike `enabled` it IS
    # refreshed every boot: the curated order in seed_domains.py is the
    # source of truth for which sources get searched first.
    for region, domains in CURATED.items():
        for pos, domain in enumerate(domains, 1):
            q("UPDATE allowlist_domains SET priority=? WHERE domain=? AND region=?",
              (pos, domain, region))
    # Config is upserted every boot, not seeded once: a running deployment
    # must pick up newly-introduced keys without losing edited values.
    for key, value, default, desc, critical in SEED_CONFIG:
        q("""INSERT INTO app_config(key,value,default_value,description,critical,updated_by,updated_at)
             VALUES(?,?,?,?,?,'system',?)
             ON CONFLICT(key) DO UPDATE SET
               default_value=excluded.default_value,
               description=excluded.description,
               critical=excluded.critical""",
          (key, value, default, desc, critical, now()))
    # Retired keys: per-role model selection was replaced by a single
    # provider switch; embeddings belonged to the cut Tier 1 corpus path;
    # answers.allow_tier3 (grounded-only mode) was removed — the general model
    # is now always the fallback, so there is no upfront withhold to toggle.
    q("""DELETE FROM app_config WHERE key LIKE 'embedding%'
         OR key IN ('model.generation','model.tier3','model.judge',
                    'answers.allow_tier3', 'groundedness.judge')""")
    if not q("SELECT 1 FROM access_requests LIMIT 1"):
        q("INSERT INTO access_requests(name,email,reg,council,specialty,institution,status,created_at) "
          "VALUES(?,?,?,?,?,?, 'pending', ?)",
          ("Dr. M. Banerjee", "m.banerjee@ipgmer.ac.in", "71204", "West Bengal",
           "Paediatrics", "IPGMER Kolkata", now()))


init_db()


def cfg(key: str, fallback: str = "") -> str:
    rows = q("SELECT value FROM app_config WHERE key=?", (key,))
    return rows[0]["value"] if rows else fallback


def audit(actor: str, action: str, change: str) -> None:
    q("INSERT INTO audit_log(actor,action,change,created_at) VALUES(?,?,?,?)",
      (actor, action, change, now()))


# ---------------------------------------------------------------- auth

ROLES = {"clinician": 1, "editor": 2, "admin": 3}


def issue_token(email: str) -> str:
    token = secrets.token_urlsafe(32)
    q("INSERT INTO auth_sessions VALUES(?,?,?)", (token, email, now()))
    return token


def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "not_authenticated")
    # Sessions expire: auth.session_days recorded created_at but never read it,
    # so a token was valid forever. Same ISO-vs-SQLite comparison caveat as the
    # daily cap — use strftime so the formats match.
    days = int(cfg("auth.session_days", "30"))
    rows = q("""SELECT u.* FROM auth_sessions s JOIN allowed_users u
                ON u.email = s.email
                WHERE s.token=?
                  AND s.created_at > strftime('%Y-%m-%dT%H:%M:%S','now',?)""",
             (token, f"-{days} days"))
    if not rows or not rows[0]["enabled"]:
        raise HTTPException(401, "session_invalid")
    u = rows[0]
    return {"email": u["email"], "name": u["name"], "role": u["role"]}


def require_role(min_role: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if ROLES[user["role"]] < ROLES[min_role]:
            raise HTTPException(403, "insufficient_role")
        return user
    return dep


@app.get("/api/health")
def health():
    return {"ok": True, "google_auth": bool(GOOGLE_CLIENT_ID),
            "demo_password": bool(DEMO_PASSWORD),
            "anthropic": bool(anthropic and (os.environ.get("ANTHROPIC_API_KEY")
                                             or os.environ.get("ANTHROPIC_AUTH_TOKEN")))}


def _login_result(email: str, name_hint: str = "") -> dict:
    rows = q("SELECT * FROM allowed_users WHERE email=?", (email.lower(),))
    if not rows:
        raise HTTPException(403, "not_allowlisted")
    u = rows[0]
    if not u["enabled"]:
        raise HTTPException(403, "disabled")
    q("UPDATE allowed_users SET last_login=? WHERE email=?", (today(), u["email"]))
    return {"token": issue_token(u["email"]),
            "user": {"email": u["email"], "name": u["name"] or name_hint, "role": u["role"]}}


@app.post("/api/auth/google")
async def auth_google(body: dict):
    """Verify a Google ID token server-side, then check the allowlist."""
    credential = body.get("credential", "")
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "google_not_configured")
    async with httpx.AsyncClient(timeout=10) as hc:
        r = await hc.get("https://oauth2.googleapis.com/tokeninfo",
                         params={"id_token": credential})
    if r.status_code != 200:
        raise HTTPException(401, "invalid_token")
    claims = r.json()
    if claims.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(401, "wrong_audience")
    if claims.get("email_verified") not in ("true", True):
        raise HTTPException(403, "unverified")
    return _login_result(claims["email"], claims.get("name", ""))


@app.post("/api/auth/demo")
def auth_demo(body: dict):
    """Simulated sign-in — only available while no Google client is configured."""
    if GOOGLE_CLIENT_ID:
        raise HTTPException(400, "demo_disabled")
    if DEMO_PASSWORD and not secrets.compare_digest(
            str(body.get("password", "")), DEMO_PASSWORD):
        raise HTTPException(403, "demo_password_required")
    email = str(body.get("email", "")).strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(400, "invalid_email")
    return _login_result(email)


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


@app.post("/api/auth/signout")
def signout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    q("DELETE FROM auth_sessions WHERE token=?", (token,))
    return {"ok": True}


# ---------------------------------------------------------------- the router

# The two Tier 2 passes send single-region pools, so the prompt is assembled
# per pass: telling the model its results are Indian while handing it KDIGO
# and WHO invites it to conclude the search misfired and refuse. The
# provenance rules stay in both variants — on the Indian pass they are inert,
# on the international pass they are the guard that stops dosing, NLEM, and
# national-programme claims being answered from foreign guidance.
_T2_POOL = {
    "IN": ("Results come from a vetted pool of Indian sources (ICMR, MoHFW, "
           "Indian journals and professional societies)."),
    "INTL": ("No Indian source in the vetted pool covered this question, so "
             "results come from international guideline and literature "
             "sources (WHO, NICE, KDIGO, PMC and similar) only."),
    # Both regions in one result set: rules 2-4 below are the only thing
    # keeping Indian sources in front, since the pool no longer does it.
    "MIXED": ("Results come from a vetted pool of Indian sources (ICMR, MoHFW, "
              "Indian journals) and, for this question, may also include "
              "international guideline and literature sources (WHO, NICE, "
              "KDIGO, PMC and similar)."),
}

_T2_RULES = (
    "Rules:\n"
    "1. Every factual claim must come from the search results — the API "
    "attaches citations; never state anything you cannot cite.\n"
    "2. PROVENANCE. Indian sources take precedence. Where an Indian source "
    "addresses the question, lead with it and state it as the answer. Use "
    "international sources for what Indian sources do not cover — mechanism, "
    "pathophysiology, general pharmacology, evidence base.\n"
    "3. Make provenance visible in the prose. When a claim rests on "
    "international literature, attribute it in-line (\"international guidance "
    "from KDIGO states…\", \"WHO recommends…\"). A reader must never be unsure "
    "which body a claim came from.\n"
    "4. Where Indian and international guidance differ substantively, say so "
    "and give both positions. Never silently reconcile them.\n"
    "5. Never base a claim about drug dosing, drug availability, formulary or "
    "NLEM status, or Indian national programme protocols on an international "
    "source. If only international sources cover such a point, say Indian "
    "guidance was not found rather than answering from them.\n"
    "6. LENGTH AND STRUCTURE. Aim for 150-250 words. Open with a direct answer "
    "in one or two sentences, then use short section headings (## Heading), a "
    "numbered list where you are describing a mechanism or sequence, and bold "
    "for key figures. Professional register, no preamble. Do not pad: if the "
    "sources support only three sentences, write three sentences.\n"
    "7. QUOTE THE SOURCES. Include one or two short verbatim quotes (25 words "
    "or fewer each) drawn from the retrieved passages, on their own line "
    "prefixed with '> ', and name the body that published each. Quote only "
    "wording that actually appears in the search results — never paraphrase "
    "into quotation marks.\n"
    "8. Answer whenever the search returned relevant material, even if it is "
    "partial: report what those sources do say and note the limit. Do not "
    "discard usable sources — a partial grounded answer is more useful than a "
    "refusal.\n"
    "8b. If the question asks for MULTIPLE papers/studies/sources (\"several\", "
    "\"a few papers\", \"list studies\"), present them as a numbered list of "
    "DISTINCT works from DIFFERENT sources where the search returned them, one "
    "line each with the title and publishing body. If only one distinct work "
    "was retrievable, give it and state plainly that it was the only one found "
    "in this search — do not pad with repeated citations of the same paper.\n"
    "9. If the sources do NOT substantively answer the question, do not compose "
    "an answer, do not describe what you searched for, and do not explain what "
    "you could not find. Reply with exactly: NO_SUBSTANTIVE_ANSWER\n"
    "10. You are a reference tool, not a clinician: report what the literature "
    "says; do not add practice recommendations of your own.\n"
    "11. Where the evidence is associative rather than causal, or contested, "
    "say so plainly rather than flattening it into a single claim.\n"
    "12. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)


def tier2_system(region: str) -> str:
    """Tier 2 system prompt for the pool actually being searched."""
    return ("You are Praman, a literature reference tool for Indian "
            "healthcare professionals. Answer the clinical question using ONLY "
            "the web search results. "
            f"{_T2_POOL.get(region, _T2_POOL['IN'])}\n\n{_T2_RULES}")


# --- triage: scope gate + retrieval plan ----------------------------------
# One small-model call that answers two questions before any search runs:
# is this a medical question at all, and which source pools does it need.
# Folding the scope gate in here is free — dual mode already makes this call.
PLAN_SYSTEM = (
    "You triage a question for a medical literature reference tool used by "
    "doctors practising in India. Return JSON only.\n"
    "in_scope = false ONLY if the question is clearly not medical or clinical — "
    "sport, travel, politics, general trivia, programming, or a request to write "
    "code or non-clinical content. Anything a clinician might reasonably ask "
    "about medicine, health, disease, drugs, diagnostics, physiology, public "
    "health, medical practice or medical research is in_scope = true, including "
    "vague, misspelt or terse clinical questions. When in any doubt, choose true.\n"
    "plan (only meaningful when in_scope) = 'both' when the question has BOTH an "
    "evidence dimension (mechanism, efficacy, trial data, guideline position) AND "
    "an India practice-context dimension (drug availability, NLEM status, cost, "
    "ICMR or national-programme position, local epidemiology). This is the common "
    "case — prefer it.\n"
    "plan = 'international_only' ONLY for pure science with no India angle — "
    "mechanism, pathophysiology, trial design — where local context adds nothing.\n"
    "plan = 'indian_only' ONLY for purely local/administrative questions "
    "(programme coverage, NLEM listing alone) where international evidence adds "
    "nothing.\n"
    "When unsure about plan, choose 'both'.\n"
    'Reply exactly: {"in_scope": <bool>, "plan": "both" | "international_only" '
    '| "indian_only"}'
)
_PLANS = ("both", "international_only", "indian_only")


_TRIAGE_OPEN = {"in_scope": True, "plan": "both"}


def _triage(query: str) -> dict:
    """{'in_scope': bool, 'plan': str}. Fails open on any doubt: refusing a real
    clinical question is far worse than searching for a non-medical one."""
    if cfg("search.dual_classifier", "true") != "true":
        return dict(_TRIAGE_OPEN)
    judge_model = model_for("judge")
    schema = {"type": "object",
              "properties": {"in_scope": {"type": "boolean"},
                             "plan": {"type": "string", "enum": list(_PLANS)}},
              "required": ["in_scope", "plan"], "additionalProperties": False}
    try:
        jc = _client(judge_model)
        if provider_of(judge_model) == "openai":
            r = jc.responses.create(model=judge_model, instructions=PLAN_SYSTEM,
                                    input=query, max_output_tokens=2000)
            text = getattr(r, "output_text", "") or ""
            if getattr(r, "status", "") == "incomplete" and not text.strip():
                return dict(_TRIAGE_OPEN)
        else:
            resp = jc.messages.create(
                model=judge_model, max_tokens=64,
                system=[{"type": "text", "text": PLAN_SYSTEM}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": query}])
            text = next(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0) if m else text)
        plan = data.get("plan")
        # Absent in_scope means the model did not assert out-of-scope.
        return {"in_scope": bool(data.get("in_scope", True)),
                "plan": plan if plan in _PLANS else "both"}
    except Exception:
        return dict(_TRIAGE_OPEN)


# --- dual mode: compose two cited drafts into one answer ------------------
# One call, NO search tool. Indian-anchored merge: the Indian position governs
# practice, but international evidence is always shown where it exists. The
# formatting rules mirror Tier 2 so the UI renders it and follow-ups parse.
COMPOSE_SYSTEM = (
    "You are Praman, composing ONE answer for a doctor practising in India from "
    "two drafts of the same question: DRAFT A from Indian sources and DRAFT B "
    "from international sources. Use ONLY facts present in the drafts — introduce "
    "nothing new and invent no citations.\n"
    "1. ANCHOR on the Indian position where DRAFT A states one; it governs what "
    "the doctor actually does.\n"
    "2. ALWAYS show that international evidence exists where DRAFT B addressed the "
    "question. Never present the Indian view as the only view when international "
    "sources spoke to the same point.\n"
    "3. Where the two AGREE, use the international evidence as the backbone and "
    "the Indian detail to localise it (availability, NLEM, cost, programme).\n"
    "4. Where they CONFLICT, surface it inline, attribute each side to its source, "
    "and name the reason for divergence where derivable (recency, cost, "
    "availability, population). Never average the two or silently pick one.\n"
    "5. Where DRAFT A is SILENT (Indian sources did not cover it), say so plainly "
    "and give the international evidence as the available basis, flagged as such.\n"
    "6. Attribute international claims in-line (\"international guidance from "
    "KDIGO…\", \"WHO…\"). Never let a claim about drug dosing, availability, NLEM "
    "status or a national programme rest on an international source without "
    "saying so.\n"
    "7. Aim for 150-250 words: open with a direct answer, then short headings "
    "(## Heading), numbered steps for a mechanism or sequence, and bold for key "
    "figures. Do not pad.\n"
    "8. Keep one or two of the short verbatim quotes the drafts already carry, "
    "on their own line prefixed with '> ', naming the body that published each.\n"
    "9. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)


def _compose(query: str, indian, intl):
    """Merge two (text, citations, ...) drafts into one Indian-anchored answer.

    Returns (text, citations, followups, model). Citations are the union of
    both drafts (deduped by URL), already region-tagged. No search happens.
    """
    def _block(label, draft):
        text, cites = draft[0], draft[1]
        lines = "\n".join(f"- [{c.get('region','INTL')}] {c.get('domain','')} — "
                          f"{(c.get('cited_text') or '')[:300]}" for c in cites)
        return f"{label}:\n{text}\n\nSources cited:\n{lines or '(none)'}"

    prompt = (f"Question: {query}\n\n"
              f"{_block('DRAFT A — from Indian sources', indian)}\n\n"
              f"{_block('DRAFT B — from international sources', intl)}")
    # Generation model, not the judge model: this is the text the clinician
    # reads, so answer quality outranks the small saving. One no-search call.
    model = model_for("generation")
    client = _client(model)
    if provider_of(model) == "openai":
        text = _openai_plain(client, model, COMPOSE_SYSTEM,
                             [{"role": "user", "content": prompt}])
    else:
        resp = client.messages.create(
            model=model, max_tokens=1600,
            system=[{"type": "text", "text": COMPOSE_SYSTEM}],
            messages=[{"role": "user", "content": prompt}])
        text = "\n".join(b.text for b in resp.content if b.type == "text")
    text, followups = _parse_followups(_strip_md_links(text))
    # Union the citations, dedup by URL, order Indian-first for the rail.
    merged, seen = [], set()
    for c in list(indian[1]) + list(intl[1]):
        u = c.get("url", "")
        if u and u not in seen:
            seen.add(u)
            merged.append(c)
    return text, merged, followups, model


TIER3_SYSTEM = (
    "You are Praman's unverified fallback. The vetted literature pool — "
    "Indian sources and international guideline sources — did not cover this "
    "question, so you are answering from general knowledge. Rules:\n"
    "1. Begin the substance of the answer with the word 'Generally' or "
    "similar hedging; keep it to 2-4 sentences.\n"
    "2. State explicitly that this may not match Indian guidelines, drug "
    "availability, or approved indications.\n"
    "3. Never invent citations or reference specific Indian guidelines, "
    "international guidelines, or named studies.\n"
    "4. Do not give specific drug doses, dose adjustments, or formulary "
    "status. If the question asks for these, say that verified guidance was "
    "not found and that a primary source should be consulted.\n"
    "5. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)


# ---------------------------------------------------------------- providers
#
# Two providers are supported (PRD D3). They are NOT equivalent for Tier 2:
# Anthropic's web_search server tool enforces citations at the API level, which
# is what the citation promise rests on. OpenAI's web search returns URL
# annotations, which we map onto the same contract — good, but a different
# guarantee. The admin UI flags this when an OpenAI model is chosen for Tier 2.

PROVIDERS = {
    "anthropic": {"label": "Anthropic (Claude)", "env": "ANTHROPIC_API_KEY",
                  "grounded": "enforced",
                  "models": {"generation": "claude-opus-4-8",
                             "judge": "claude-haiku-4-5"},
                  # Not probed against a live key — no Anthropic credential is
                  # configured. Batching at 100 is safe either way.
                  "max_domains": 100},
    # Model ids verified against the provider's own models.list(), not
    # assumed: 'gpt-5.2-mini' does not exist and silently failed every
    # verdict call, downgrading good grounded answers to unverified.
    "openai":    {"label": "OpenAI (ChatGPT)", "env": "OPENAI_API_KEY",
                  "grounded": "annotations",
                  "models": {"generation": "gpt-5.2",
                             "judge": "gpt-5-mini"},
                  # Hard API limit, probed against the live endpoint: an
                  # allowed_domains array longer than this is a 400, so the
                  # search never runs and every query silently falls to Tier 3.
                  "max_domains": 100},
}


def _domain_batches(domains: list[str], cap: int) -> list[list[str]]:
    """Split a pool into search-sized batches, preserving order.

    Seed order is trust order (apex bodies, then journals, then societies,
    then state and institutional sources), so batch 1 carries the most
    authoritative domains and later batches are only searched if it fails.
    """
    if cap <= 0:
        return [domains]
    return [domains[i:i + cap] for i in range(0, len(domains), cap)] or [[]]


def _mixed_batches(by_region: dict, indian_slots: int, cap: int) -> list[tuple]:
    """Interleave both regions into cap-sized calls, priority order preserved.

    Call 1 takes the top `indian_slots` Indian sources and fills the rest of
    the cap with international ones; later calls take what is left, still
    highest-priority first. Every enabled domain is reached exactly once.
    """
    rest = max(cap - indian_slots, 0)
    ins, intls = list(by_region["IN"]), list(by_region["INTL"])
    out, n = [], 0
    while ins or intls:
        n += 1
        take_in = ins[:indian_slots] if n == 1 else ins[:cap - min(len(intls), rest)]
        ins = ins[len(take_in):]
        batch = take_in + intls[:cap - len(take_in)]
        intls = intls[cap - len(take_in):]
        out.append(("MIXED", "Indian + international", batch, n, 0))
    # Second pass fills in the now-known total so the UI can say "1 of 2".
    return [(r, l, b, i, len(out)) for r, l, b, i, _ in out]


def active_provider() -> str:
    """The one provider currently powering every answer."""
    p = cfg("provider.active", "anthropic")
    return p if p in PROVIDERS else "anthropic"


def model_for(role: str) -> str:
    """Model id for a role ('generation' | 'judge') on the active provider."""
    return PROVIDERS[active_provider()]["models"][role]


def provider_of(model_id: str) -> str:
    return "openai" if str(model_id).lower().startswith(("gpt", "o1", "o3", "o4", "chatgpt")) \
        else "anthropic"


def provider_ready(name: str) -> bool:
    if name == "anthropic":
        return anthropic is not None and bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return openai is not None and bool(os.environ.get("OPENAI_API_KEY"))


def _client(model_id: str):
    """Return an SDK client for whichever provider owns this model id."""
    name = provider_of(model_id)
    if name == "openai":
        if openai is None:
            raise HTTPException(503, "openai_sdk_missing")
        if not os.environ.get("OPENAI_API_KEY"):
            raise HTTPException(503, "openai_credentials: OPENAI_API_KEY is not set")
        return openai.OpenAI()
    if anthropic is None:
        raise HTTPException(503, "anthropic_sdk_missing")
    try:
        return anthropic.Anthropic()
    except Exception as e:  # missing credentials
        raise HTTPException(503, f"anthropic_credentials: {e}")


def _is_transient(e: Exception) -> bool:
    """A provider error worth retrying: 5xx, rate limit, timeout, connection.
    A single OpenAI 500 was taking down every tier and surfacing as a
    misleading 'not found in Indian literature'."""
    status = (getattr(e, "status_code", None)
              or getattr(getattr(e, "response", None), "status_code", None))
    if status in (408, 409, 429, 500, 502, 503, 504):
        return True
    name = type(e).__name__
    return any(k in name for k in ("Timeout", "Connection", "InternalServerError",
                                   "ServiceUnavailable", "RateLimit", "APIError"))


def _retry(fn, tries: int = 3):
    """Retry a provider call on transient errors with a short linear backoff."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1 or not _is_transient(e):
                raise
            time.sleep(0.6 * (i + 1))


def _openai_grounded(client, model, system, messages, domains, max_uses):
    """Tier 2 via OpenAI Responses API + web_search with domain filters.

    Mapped onto the same (segments, citations, text) contract Anthropic
    produces. Citations come from url_citation annotations.
    """
    convo = "\n\n".join(
        f"{m['role'].upper()}: {m['content'] if isinstance(m['content'], str) else ''}"
        for m in messages)
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=convo,
        tools=[{"type": "web_search",
                "filters": {"allowed_domains": domains}}],
        max_output_tokens=2048,
    )
    text, citations, seen = "", [], {}
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", "") != "output_text":
                continue
            text += block.text
            for a in (getattr(block, "annotations", None) or []):
                if getattr(a, "type", "") != "url_citation":
                    continue
                url = _clean_url(getattr(a, "url", "") or "")
                if not url or url in seen:
                    continue
                seen[url] = True
                citations.append({
                    "cited_text": (getattr(a, "title", "") or "")[:400],
                    "url": url,
                    "title": getattr(a, "title", "") or "",
                    "domain": re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", url),
                })
    return _strip_md_links(text), citations


def _clean_url(url: str) -> str:
    """Drop the provider's attribution query param from citation links."""
    return re.sub(r"[?&]utm_source=openai\b", "", url).rstrip("?&")


def _strip_md_links(text: str) -> str:
    """OpenAI interleaves inline markdown links with its annotations. The UI
    renders citations as pills and a sources rail, so the inline duplicates are
    noise — remove them and leave clean prose."""
    # "([label](url))" — a parenthesised citation: drop it entirely.
    text = re.sub(r"\s*\(\[[^\]]*\]\(https?://[^)]*\)\)", "", text)
    # "[label](url)" — keep the human-readable label.
    text = re.sub(r"\[([^\]]*)\]\(https?://[^)]*\)", r"\1", text)
    # Bare "(https://…)" leftovers. Bold, headings and lists are deliberately
    # preserved now — the prompt asks for them and the UI renders them.
    text = re.sub(r"\s*\(https?://[^)]*\)", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _openai_plain(client, model, system, messages) -> str:
    convo = "\n\n".join(
        f"{m['role'].upper()}: {m['content'] if isinstance(m['content'], str) else ''}"
        for m in messages)

    def _call():
        # 3000, not 1024: gpt-5.x are reasoning models that spend output tokens
        # on internal reasoning first, so a small budget returns status=incomplete
        # with empty output_text — which silently produced a not-found.
        r = client.responses.create(model=model, instructions=system,
                                    input=convo, max_output_tokens=3000)
        text = getattr(r, "output_text", "") or ""
        if getattr(r, "status", "") == "incomplete" and not text.strip():
            raise RuntimeError("tier3 truncated by token budget")
        return text
    return _strip_md_links(_retry(_call))


def _parse_followups(text: str) -> tuple[str, list[str]]:
    followups: list[str] = []
    m = re.search(r"\[\[FOLLOWUPS\]\](.*)$", text, re.S)
    if m:
        followups = [s.strip() for s in m.group(1).strip().split("|") if s.strip()][:2]
        text = text[: m.start()].strip()
    return text.strip(), followups


def _run_with_pause_turn(client, **params):
    """Server tools can pause long turns; resume up to 3 times."""
    messages = list(params.pop("messages"))
    for _ in range(4):
        resp = client.messages.create(messages=messages, **params)
        if resp.stop_reason != "pause_turn":
            return resp
        messages = messages + [{"role": "assistant", "content": resp.content}]
    return resp


def _extract_answer(resp) -> tuple[list[dict], list[dict], str]:
    """Return (segments, citations, plain_text) from a Tier 2 response."""
    segments, citations, plain = [], [], []
    seen: dict[tuple, int] = {}
    for block in resp.content:
        if block.type != "text":
            continue
        idxs = []
        for c in (getattr(block, "citations", None) or []):
            url = getattr(c, "url", "") or ""
            key = (url, getattr(c, "cited_text", "") or "")
            if key not in seen:
                seen[key] = len(citations)
                citations.append({
                    "cited_text": (getattr(c, "cited_text", "") or "").strip(),
                    "url": url,
                    "title": getattr(c, "title", "") or "",
                    "domain": re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", url),
                })
            idxs.append(seen[key])
        segments.append({"text": block.text, "citations": sorted(set(idxs))})
        plain.append(block.text)
    return segments, citations, "\n".join(plain).strip()


def _is_non_answer(text: str) -> bool:
    """Refusal guard. The generation prompt tells the model to reply exactly
    NO_SUBSTANTIVE_ANSWER when the sources do not answer the question. With the
    groundedness judge removed, this sentinel is the only thing standing between
    a refusal and it being served behind a grounded badge — so an empty answer,
    or one that leads with the sentinel, is treated as "this pool did not
    answer" and falls through. It is a string check, not a model call."""
    t = (text or "").strip()
    return not t or "NO_SUBSTANTIVE_ANSWER" in t.upper()[:60]


def _grounded_answer(model: str, system: str, msgs: list[dict],
                     domains: list[str], effort: str, max_uses: int):
    """Provider-neutral Tier 2 generation. Returns (text, citations, model, refused).

    Search runs server-side inside this one call on both providers, so the
    retrieval gate is applied to the sources that come back rather than before
    generation — there is no separate retrieval step to gate.
    """
    prov = provider_of(model)
    client = _client(model)
    if prov == "openai":
        text, citations = _retry(lambda: _openai_grounded(
            client, model, system, msgs, domains, max_uses))
        return text, citations, model, False
    resp = _retry(lambda: _run_with_pause_turn(
        client, model=model, max_tokens=2048,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[{"type": "web_search_20260209", "name": "web_search",
                "max_uses": max_uses, "allowed_domains": domains}],
        messages=msgs,
    ))
    segments, citations, plain = _extract_answer(resp)
    return plain, citations, resp.model, resp.stop_reason == "refusal"


def _load_history(conversation_id: str) -> list[dict]:
    max_turns = int(cfg("context.max_turns", "6"))
    rows = q("""SELECT role, content FROM turns
                WHERE conversation_id=? AND content != ''
                ORDER BY id DESC LIMIT ?""", (conversation_id, max_turns))
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


@app.post("/api/ask")
def ask(body: dict, request: Request, user: dict = Depends(current_user)):
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(400, "empty_query")

    # Per-user daily cap (PRD cost guardrail). created_at is ISO-8601 with a
    # 'T' separator; SQLite's datetime() returns a space-separated string, and
    # 'T' (0x54) sorts above ' ' (0x20) — so a plain datetime() comparison
    # counted queries older than 24h and capped heavy users hours early.
    # strftime with the same layout compares like-for-like.
    cap = int(cfg("cost.daily_user_cap", "40"))
    used = q("""SELECT COUNT(*) n FROM query_logs WHERE user_email=?
                AND created_at > strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')""",
             (user["email"],))[0]["n"]
    if used >= cap:
        raise HTTPException(429, "daily_cap_reached")

    conversation_id = body.get("conversation_id") or str(uuid.uuid4())
    if not q("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)):
        q("INSERT INTO conversations VALUES(?,?,?,?)",
          (conversation_id, user["email"], query[:80], now()))

    def stream():
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        started = time.time()
        query_id = str(uuid.uuid4())
        # Priority order is the curated editorial ranking; batch 1 must carry
        # the apex bodies, so this ORDER BY is load-bearing, not cosmetic.
        rows = q("""SELECT domain, region FROM allowlist_domains
                    WHERE enabled=1 ORDER BY priority, rowid""")
        by_region = {"IN": [r["domain"] for r in rows if r["region"] == "IN"],
                     "INTL": [r["domain"] for r in rows if r["region"] == "INTL"]}
        region_of = {r["domain"]: r["region"] for r in rows}

        def cite_region(domain: str) -> str:
            """Region of a cited domain. Falls back to suffix match because
            providers return hosts like www.who.int for an allowlisted who.int."""
            d = (domain or "").lower().removeprefix("www.")
            if d in region_of:
                return region_of[d]
            for known, reg in region_of.items():
                if d == known or d.endswith("." + known):
                    return reg
            return "INTL"          # unknown host is never treated as Indian
        domains = by_region["IN"] + by_region["INTL"]
        sources_searched = [f"web:{d}" for d in domains]
        history = _load_history(conversation_id)
        result: dict = {
            "query_id": query_id, "conversation_id": conversation_id,
            "sources_searched": sources_searched,
            "retrieved_at": today(), "citations": [], "followups": [],
            "source_region": None, "pool_outcome": None,
            "indian_citations": None, "intl_citations": None,
        }

        prov = active_provider()
        model = model_for("generation")
        effort = cfg("generation.effort", "medium")
        min_chunks = int(cfg("retrieval.min_chunks", "2"))
        msgs = history + [{"role": "user", "content": query}]
        falls: list[dict] = []                       # every fall-through, for the gap log

        def fell(tier, reason):
            falls.append({"tier": tier, "reason": reason})
            result["fallthrough"] = falls

        # ---------- Tier 2: allowlisted web search ----------
        # NOTE: Tier 1 (curated corpus) is out of scope — there is no corpus,
        # no embeddings, no vector store — so the sequence starts at Tier 2.
        answered_t2 = False
        region_mode = cfg("search.region_mode", "indian_first")
        # Providers cap allowed_domains, so a pool larger than the cap is
        # rejected outright and Tier 2 never runs.
        cap = int(cfg("search.max_domains_per_call",
                      str(PROVIDERS[prov].get("max_domains", 100))))

        # ---------- Scope gate ----------
        # One triage call decides both "is this medical at all" and which pools
        # to search. Only on the first turn of a conversation: a follow-up like
        # "what about in children?" carries no clinical signal on its own and
        # must not be refused. Fails open — see _triage.
        triage = dict(_TRIAGE_OPEN)
        if not history:
            triage = _triage(query)
        out_of_scope = not triage["in_scope"]
        if out_of_scope:
            fell(2, "out_of_scope")
            yield sse("stage", {"label": "Not a medical question"})
            result.update({
                "tier": None, "status": "out_of_scope",
                "withheld_reason": "out_of_scope",
                "answer_text": "", "segments": [], "citations": [],
                "model_used": None, "sources_searched": [],
            })

        # ---------- Dual: two dedicated parallel searches, one composed answer ----
        # Each pool gets its own call with its own search budget the other pool
        # cannot consume, so an Indian search is never starved by the denser
        # international pool. A compose call then merges the two, Indian-anchored.
        if out_of_scope:
            batched = []                       # nothing is searched
        elif region_mode == "dual":
            max_uses = int(cfg("websearch.max_uses", "3"))
            plan = triage["plan"]              # from the same triage call
            in_pool = by_region["IN"][:int(cfg("search.dual_indian_cap", "100"))]
            intl_pool = by_region["INTL"][:int(cfg("search.dual_intl_cap", "100"))]
            want = {"IN": plan in ("both", "indian_only") and bool(in_pool),
                    "INTL": plan in ("both", "international_only") and bool(intl_pool)}
            if want["IN"]:
                yield sse("stage", {"label": "Searching reliable Indian medical sources"})
            if want["INTL"]:
                yield sse("stage", {"label": "Searching reliable international sources"})

            # The two searches overlap: blocking SDK calls release the GIL on
            # network I/O, so wall-clock is one search, not two. Threads touch
            # no DB — every config value they need is resolved above.
            def _search(region):
                pool = in_pool if region == "IN" else intl_pool
                return _grounded_answer(model, tier2_system(region), msgs, pool,
                                        effort, max_uses)
            drafts: dict = {}
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {r: ex.submit(_search, r) for r in ("IN", "INTL") if want[r]}
                for r, fut in futs.items():
                    try:
                        drafts[r] = fut.result()
                    except Exception as e:
                        drafts[r] = None
                        detail = re.sub(r"\s+", " ", str(e))[:160]
                        fell(2, f"generation_failed:{r}:{type(e).__name__}: {detail}")

            # Gate + region-tag each draft independently, exactly as Tier 2 does.
            good: dict = {}
            for r in ("IN", "INTL"):
                d = drafts.get(r)
                if not d:
                    continue
                text, cites, umodel, refused = d
                text, fups = _parse_followups(text)
                if refused:
                    fell(2, f"provider_refusal:{r}")
                    continue
                for c in cites:
                    c["region"] = cite_region(c.get("domain", ""))
                if len(cites) < min_chunks:
                    fell(2, f"below_min_chunks:{r}({len(cites)}<{min_chunks})")
                    continue
                if _is_non_answer(text):
                    # This pool signalled it could not answer — keep it out of
                    # compose so a refusal draft can't taint the merged answer.
                    fell(2, f"no_substantive_answer:{r}")
                    continue
                good[r] = (text, cites, fups, umodel)

            result["indian_citations"] = len(good["IN"][1]) if "IN" in good else 0
            result["intl_citations"] = len(good["INTL"][1]) if "INTL" in good else 0

            # Asymmetric outcomes are first-class: compose only when both pools
            # answered; otherwise serve the one that did, honestly labelled.
            if "IN" in good and "INTL" in good:
                result["pool_outcome"] = "both_answered"
                yield sse("stage", {"label": "Combining the evidence"})
                try:
                    ctext, ccites, cfups, cmodel = _compose(query, good["IN"], good["INTL"])
                    candidate = (ctext, ccites, cfups, cmodel)
                except Exception as e:
                    # Compose is the last thing that can fail; on failure fall
                    # back to the Indian draft rather than losing the turn.
                    fell(2, f"compose_failed:{type(e).__name__}")
                    candidate = good["IN"]
                    result["pool_outcome"] = "compose_failed_indian"
            elif "IN" in good:
                result["pool_outcome"] = "indian_only_answered"
                candidate = good["IN"]
            elif "INTL" in good:
                result["pool_outcome"] = "intl_only_answered"
                candidate = good["INTL"]
            else:
                result["pool_outcome"] = "both_empty"
                candidate = None

            if candidate and _is_non_answer(candidate[0]):
                fell(2, "no_substantive_answer:dual")
            elif candidate:
                text, cites, fups, umodel = candidate
                answered_t2 = True
                cregions = {c["region"] for c in cites}
                result.update({
                    "tier": 2, "status": "answered", "answer_text": text,
                    "segments": [{"text": text,
                                  "citations": list(range(len(cites)))}],
                    "citations": cites, "followups": fups, "model_used": umodel,
                    "source_region": (cregions.pop() if len(cregions) == 1
                                      else "MIXED"),
                })
            batched = []          # dual path is complete; skip the batch loop
        elif region_mode == "mixed":
            # One pool per call, both regions present. Precedence is no longer
            # structural — it rests on the prompt's PROVENANCE rule — so the
            # answer's region is derived from the citations it actually used.
            n_in = int(cfg("search.mixed_indian_slots", "40"))
            batched = _mixed_batches(by_region, n_in, cap)
        else:
            # Indian first. International is a separate, later pass so an
            # Indian-grounded answer can never be displaced by the far more
            # abundant Western literature — and so the answer can be badged.
            passes = [("IN", "Indian")]
            if region_mode != "indian_only":
                passes.append(("INTL", "international"))
            batched = [(region, label, batch, n + 1, len(bs))
                       for region, label in passes
                       for bs in [_domain_batches(by_region[region], cap)]
                       for n, batch in enumerate(bs)]

        for region, label, pool, bn, btotal in batched:
            if answered_t2:
                break
            if not pool:
                fell(2, f"no_enabled_domains:{region}")
                continue
            # Fall-through tag keeps the batch: "IN" vs "IN#2" tells you whether
            # the apex pool or only the long tail was searched.
            tag = region if btotal == 1 else f"{region}#{bn}"
            part = f" (batch {bn} of {btotal})" if btotal > 1 else ""
            # Stage labels are read by clinicians mid-wait. No vendor names, no
            # "allowlisted", no pool sizes or batch numbers — none of it means
            # anything at the point of care.
            yield sse("stage", {"label": f"Searching reliable {label} medical sources"})
            try:
                plain, citations, used_model, refused = _grounded_answer(
                    model, tier2_system(region), msgs, pool, effort,
                    int(cfg("websearch.max_uses", "3")))
            except HTTPException as e:
                yield sse("error", {"detail": str(e.detail)})
                return
            except Exception as e:
                yield sse("stage", {"label": f"Could not reach {label} sources",
                                    "state": "warn"})
                # Carry the provider's own message: a bare exception class name
                # hid a 400 that had disabled Tier 2 entirely.
                detail = re.sub(r"\s+", " ", str(e))[:200]
                fell(2, f"generation_failed:{tag}:{type(e).__name__}: {detail}")
                continue

            plain, followups = _parse_followups(plain)

            if refused:
                fell(2, f"provider_refusal:{tag}")
            elif len(citations) < min_chunks:
                # Retrieval gate: a lone source is not coverage.
                fell(2, f"below_min_chunks:{tag}({len(citations)}<{min_chunks})")
                yield sse("stage", {"label": "Not enough supporting references found"})
            elif _is_non_answer(plain):
                # The model signalled it could not answer from these sources.
                fell(2, f"no_substantive_answer:{tag}")
            else:
                yield sse("stage", {"label": f"Found {len(citations)} supporting "
                                             f"reference{'' if len(citations)==1 else 's'}"})
                for c in citations:
                    c["region"] = cite_region(c.get("domain", ""))
                answered_t2 = True
                # Region derived from what was actually cited, not from which
                # pool was searched: a mixed pool can produce a purely Indian
                # answer, and the badge must reflect the sources used.
                cregions = {c["region"] for c in citations}
                result.update({
                    "tier": 2, "status": "answered", "answer_text": plain,
                    "segments": [{"text": plain,
                                  "citations": list(range(len(citations)))}],
                    "citations": citations, "followups": followups,
                    "model_used": used_model,
                    "source_region": (cregions.pop() if len(cregions) == 1
                                      else "MIXED"),
                })

        # ---------- Tier 3 / not found ----------
        # A not_found response carries tier: null — no badge, no tier styling.
        if not answered_t2 and not out_of_scope:
            # No grounded answer → always fall back to the general model. There
            # is no upfront withhold: the only not_found left is when Tier 3
            # itself returns nothing (refusal, error, or empty).
            t3_model, t3_prov = model, prov
            yield sse("stage", {"label": "Answering from general knowledge"})
            try:
                t3_client = _client(t3_model)
                if t3_prov == "openai":
                    plain = _openai_plain(t3_client, t3_model, TIER3_SYSTEM, msgs)
                    used = t3_model
                else:
                    t3 = _retry(lambda: t3_client.messages.create(
                        model=t3_model, max_tokens=1024,
                        thinking={"type": "adaptive"},
                        output_config={"effort": effort},
                        system=[{"type": "text", "text": TIER3_SYSTEM,
                                 "cache_control": {"type": "ephemeral"}}],
                        messages=msgs,
                    ))
                    used = t3.model
                    if t3.stop_reason == "refusal":
                        fell(3, "provider_refusal")
                        plain = ""       # falls through to not_found below
                    else:
                        plain = "\n".join(b.text for b in t3.content if b.type == "text")
                plain, followups = _parse_followups(plain)
            except Exception as e:
                # Tier 3 is the last tier: its failure means not_found,
                # not an error page.
                fell(3, f"generation_failed:{type(e).__name__}")
                plain, followups, used = "", [], None
            if plain.strip():
                result.update({
                    "tier": 3, "status": "unverified", "answer_text": plain,
                    "segments": [{"text": plain, "citations": []}],
                    "followups": followups, "model_used": used,
                })
            else:
                fell(3, "empty_answer")
                result.update({
                    "tier": None, "status": "not_found",
                    "withheld_reason": "all_tiers_failed",
                    "answer_text": "", "segments": [], "model_used": None,
                })

        result["latency_ms"] = int((time.time() - started) * 1000)

        # A not-found caused by the provider erroring (a 500 on every call after
        # retries) is NOT "not found in the literature" — it's a service failure,
        # and the clinician must be told to retry, not that their question is
        # uncovered. Distinguish the two by looking at what actually failed.
        if result.get("status") == "not_found" and falls:
            # Every fall is either a provider error or its downstream empty_answer,
            # and at least one is a genuine provider error → the service failed,
            # this is not a genuine "no source covers it".
            reasons = [f["reason"] for f in falls]
            if (any("generation_failed" in r for r in reasons)
                    and all("generation_failed" in r or r == "empty_answer"
                            for r in reasons)):
                result["withheld_reason"] = "service_error"

        # Invariant (regression guard for the "refusal behind a Grounded badge"
        # bug): a tiered response must carry real content, and a grounded tier
        # must carry citations. Anything else is downgraded to not_found rather
        # than shown with a badge.
        if result.get("tier") is not None:
            bad = (not (result.get("answer_text") or "").strip()
                   or (result["tier"] == 2 and not result.get("citations")))
            if bad:
                fell(result["tier"], "invariant_violation")
                result.update({"tier": None, "status": "not_found",
                               "withheld_reason": "all_tiers_failed",
                               "answer_text": "", "segments": [],
                               "citations": [], "model_used": None,
                               "source_region": None})

        # log + persist the turn (PRD: instrument everything)
        q("""INSERT INTO query_logs(query_id,user_email,conversation_id,query_text,
             tier,status,high_stakes,latency_ms,model_used,fallthrough,
             source_region,pool_outcome,indian_citations,intl_citations,created_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (query_id, user["email"], conversation_id, query, result["tier"],
           result["status"], 0, result["latency_ms"],
           result.get("model_used"),
           json.dumps(falls) if falls else None,
           result.get("source_region"), result.get("pool_outcome"),
           result.get("indian_citations"), result.get("intl_citations"), now()))
        q("""INSERT INTO turns(conversation_id,role,content,tier,result_json,
             query_id,created_at) VALUES(?,?,?,?,?,?,?)""",
          (conversation_id, "user", query, None, None, query_id, now()))
        # Store the assistant turn always (even not-found) with the full result,
        # so a reloaded thread shows exactly what the clinician saw. Empty-content
        # turns are excluded from conversation history in _load_history.
        q("""INSERT INTO turns(conversation_id,role,content,tier,result_json,
             query_id,created_at) VALUES(?,?,?,?,?,?,?)""",
          (conversation_id, "assistant", result.get("answer_text") or "",
           result["tier"], json.dumps(result), query_id, now()))

        yield sse("result", result)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- feedback & gap log

@app.post("/api/feedback")
def feedback(body: dict, user: dict = Depends(current_user)):
    fb = body.get("feedback")
    if fb not in ("up", "down"):
        raise HTTPException(400, "invalid_feedback")
    q("UPDATE query_logs SET feedback=? WHERE query_id=? AND user_email=?",
      (fb, body.get("query_id", ""), user["email"]))
    return {"ok": True}


@app.post("/api/suggest-source")
def suggest_source(body: dict, user: dict = Depends(current_user)):
    q("UPDATE query_logs SET suggested_source=1 WHERE query_id=? AND user_email=?",
      (body.get("query_id", ""), user["email"]))
    return {"ok": True}


# ---------------------------------------------------------------- library (D2)

@app.get("/api/conversations")
def conversations_list(user: dict = Depends(current_user)):
    """The user's own chat history, most-recent first — auto-saved, no starring
    needed. Deduped by question so the same query asked repeatedly shows once
    (keeping the most recent thread), which otherwise floods the Recents list."""
    rows = q("""SELECT c.id, c.title, MAX(t.created_at) AS last_at,
                       COUNT(CASE WHEN t.role='user' THEN 1 END) AS turns
                FROM conversations c JOIN turns t ON t.conversation_id = c.id
                WHERE c.user_email = ?
                GROUP BY c.id ORDER BY last_at DESC""", (user["email"],))
    seen, out = set(), []
    for r in rows:
        key = (r["title"] or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(r))
        if len(out) >= 30:
            break
    return out


@app.get("/api/conversations/{conversation_id}")
def conversation_get(conversation_id: str, user: dict = Depends(current_user)):
    """Full thread for reload: every turn with its stored answer payload. Scoped
    to the owner — another user's conversation_id returns 404."""
    owner = q("SELECT user_email, title FROM conversations WHERE id=?",
              (conversation_id,))
    if not owner or owner[0]["user_email"] != user["email"]:
        raise HTTPException(404, "not_found")
    rows = q("""SELECT role, content, tier, result_json, created_at FROM turns
                WHERE conversation_id=? ORDER BY id""", (conversation_id,))
    turns = []
    for r in rows:
        t = {"role": r["role"], "content": r["content"], "tier": r["tier"],
             "created_at": r["created_at"]}
        if r["result_json"]:
            try:
                t["result"] = json.loads(r["result_json"])
            except Exception:
                pass
        turns.append(t)
    return {"id": conversation_id, "title": owner[0]["title"], "turns": turns}


@app.delete("/api/conversations/{conversation_id}")
def conversation_delete(conversation_id: str, user: dict = Depends(current_user)):
    """Remove a conversation and its turns. Owner-scoped: another user's id
    returns 404 rather than deleting anything. query_logs rows are kept — the
    gap log is an operational record, not user-facing history."""
    owner = q("SELECT user_email FROM conversations WHERE id=?", (conversation_id,))
    if not owner or owner[0]["user_email"] != user["email"]:
        raise HTTPException(404, "not_found")
    q("DELETE FROM turns WHERE conversation_id=?", (conversation_id,))
    q("DELETE FROM conversations WHERE id=?", (conversation_id,))
    return {"ok": True}


# The manual Save/Library flow was removed from the UI — auto-saved
# conversation history replaced it. The /api/library endpoints and the
# saved_conversations table went with it; existing rows are left in place
# rather than dropped, since dropping a table in SQLite is irreversible.


# ---------------------------------------------------------------- public: sources & access

@app.get("/api/sources")
def sources():
    rows = q("""SELECT domain, trust_note, region FROM allowlist_domains
                WHERE enabled=1 ORDER BY region, domain""")
    return [dict(r) for r in rows]


@app.post("/api/request-access")
def request_access(body: dict):
    email = str(body.get("email", "")).strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(400, "invalid_email")
    q("""INSERT INTO access_requests(name,email,reg,council,specialty,institution,status,created_at)
         VALUES(?,?,?,?,?,?,'pending',?)""",
      (str(body.get("name", ""))[:120], email, str(body.get("reg", ""))[:40],
       str(body.get("council", ""))[:60], str(body.get("specialty", ""))[:80],
       str(body.get("institution", ""))[:120], now()))
    return {"ok": True}


# ---------------------------------------------------------------- admin: domains

@app.get("/api/admin/domains")
def domains_list(user: dict = Depends(require_role("editor"))):
    return [dict(r) for r in q("SELECT * FROM allowlist_domains ORDER BY created_at")]


@app.post("/api/admin/domains")
def domains_add(body: dict, user: dict = Depends(require_role("editor"))):
    domain = str(body.get("domain", "")).strip().lower()
    note = str(body.get("trust_note", "")).strip()
    if not re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", domain):
        raise HTTPException(400, "invalid_domain")
    if not note:
        raise HTTPException(400, "trust_note_required")
    region = "INTL" if str(body.get("region", "IN")).upper() == "INTL" else "IN"
    if q("SELECT 1 FROM allowlist_domains WHERE domain=?", (domain,)):
        raise HTTPException(409, "duplicate")
    q("""INSERT INTO allowlist_domains(domain,trust_note,enabled,added_by,
         created_at,region) VALUES(?,?,1,?,?,?)""",
      (domain, note, user["name"], now(), region))
    audit(user["name"], "create", f"domain {domain} added ({region})")
    return {"ok": True}


@app.patch("/api/admin/domains/{domain}")
def domains_toggle(domain: str, body: dict, user: dict = Depends(require_role("editor"))):
    enabled = 1 if body.get("enabled") else 0
    if not q("SELECT 1 FROM allowlist_domains WHERE domain=?", (domain,)):
        raise HTTPException(404, "not_found")
    q("UPDATE allowlist_domains SET enabled=? WHERE domain=?", (enabled, domain))
    audit(user["name"], "enable" if enabled else "disable",
          f"domain {domain} → enabled:{bool(enabled)}")
    return {"ok": True}


# ---------------------------------------------------------------- admin: users & requests

@app.get("/api/admin/users")
def users_list(user: dict = Depends(require_role("admin"))):
    return [dict(r) for r in q("SELECT * FROM allowed_users ORDER BY created_at")]


@app.post("/api/admin/users")
def users_add(body: dict, user: dict = Depends(require_role("admin"))):
    email = str(body.get("email", "")).strip().lower()
    name = str(body.get("name", "")).strip()
    role = body.get("role", "clinician")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) or role not in ROLES or not name:
        raise HTTPException(400, "invalid")
    if q("SELECT 1 FROM allowed_users WHERE email=?", (email,)):
        raise HTTPException(409, "duplicate")
    q("INSERT INTO allowed_users VALUES(?,?,?,1,?,?,NULL)",
      (email, name, role, user["name"], now()))
    audit(user["name"], "create", f"beta access granted to {email}")
    return {"ok": True}


@app.patch("/api/admin/users/{email}")
def users_update(email: str, body: dict, user: dict = Depends(require_role("admin"))):
    email = email.lower()
    if email == user["email"]:
        raise HTTPException(400, "cannot_modify_self")
    rows = q("SELECT * FROM allowed_users WHERE email=?", (email,))
    if not rows:
        raise HTTPException(404, "not_found")
    if "enabled" in body:
        enabled = 1 if body["enabled"] else 0
        q("UPDATE allowed_users SET enabled=? WHERE email=?", (enabled, email))
        if not enabled:  # revoke live sessions immediately
            q("DELETE FROM auth_sessions WHERE email=?", (email,))
        audit(user["name"], "enable" if enabled else "disable",
              f"user {email} → enabled:{bool(enabled)}")
    if "role" in body:
        if body["role"] not in ROLES:
            raise HTTPException(400, "invalid_role")
        audit(user["name"], "update",
              f"user {email}: role {rows[0]['role']} → {body['role']}")
        q("UPDATE allowed_users SET role=? WHERE email=?", (body["role"], email))
    return {"ok": True}


@app.get("/api/admin/requests")
def requests_list(user: dict = Depends(require_role("admin"))):
    return [dict(r) for r in
            q("SELECT * FROM access_requests WHERE status='pending' ORDER BY id DESC")]


@app.post("/api/admin/requests/{req_id}")
def requests_decide(req_id: int, body: dict, user: dict = Depends(require_role("admin"))):
    decision = body.get("decision")
    rows = q("SELECT * FROM access_requests WHERE id=? AND status='pending'", (req_id,))
    if not rows or decision not in ("approve", "deny"):
        raise HTTPException(404, "not_found")
    r = rows[0]
    q("UPDATE access_requests SET status=? WHERE id=?",
      ("approved" if decision == "approve" else "denied", req_id))
    if decision == "approve":
        if not q("SELECT 1 FROM allowed_users WHERE email=?", (r["email"],)):
            q("INSERT INTO allowed_users VALUES(?,?,?,1,?,?,NULL)",
              (r["email"], r["name"], "clinician", user["name"], now()))
        audit(user["name"], "create", f"beta access granted to {r['email']}")
    else:
        audit(user["name"], "disable", f"beta request denied for {r['email']}")
    return {"ok": True}


# ---------------------------------------------------------------- admin: config & audit

@app.get("/api/admin/config")
def config_list(user: dict = Depends(require_role("editor"))):
    return [dict(r) for r in q("SELECT * FROM app_config ORDER BY key")]


@app.patch("/api/admin/config/{key}")
def config_update(key: str, body: dict, user: dict = Depends(require_role("admin"))):
    rows = q("SELECT * FROM app_config WHERE key=?", (key,))
    if not rows:
        raise HTTPException(404, "not_found")
    if rows[0]["critical"] and not body.get("confirmed"):
        raise HTTPException(409, "confirmation_required")
    value = str(body.get("value", "")).strip()
    if not value:
        raise HTTPException(400, "empty_value")
    audit(user["name"], "update", f"{key}: {rows[0]['value']} → {value}")
    q("UPDATE app_config SET value=?, updated_by=?, updated_at=? WHERE key=?",
      (value, user["name"], now(), key))
    # Model changes alter which providers are in use and what to probe, so the
    # cached credential status is immediately stale.
    if key.startswith(("model.", "provider.")):
        _probe_cache.update(at=0.0, data=None)
    return {"ok": True}


# ---------------------------------------------------------------- admin: credentials
#
# Status only. Key material is NEVER accepted, stored, or returned here — it
# lives in the platform secret store and reaches the process as an env var
# (PRD §6.3/§7.8). This endpoint answers "will answers work?", nothing more.

_probe_cache: dict = {"at": 0.0, "data": None}
_PROBE_TTL = 60  # seconds


def _probe_provider(name: str) -> dict:
    """Cheap liveness check: resolve a model this provider owns. No tokens."""
    meta = PROVIDERS[name]
    is_active = active_provider() == name
    probe_model = meta["models"]["generation"]
    out = {
        "provider": meta["label"], "key": name, "env_var": meta["env"],
        "use": "answering every question" if is_active else "standby",
        "in_use": is_active,
        "grounding": meta["grounded"],
        "configured": provider_ready(name),
        "status": "not_configured",
        "detail": f"No API key is set ({meta['env']}).",
        "probe_model": probe_model,
        "checked_at": now(),
    }
    sdk = anthropic if name == "anthropic" else openai
    if sdk is None:
        out["detail"] = f"The {name} SDK is not installed in this image."
        return out
    if not out["configured"]:
        if not is_active:
            out["detail"] = (f"No API key set ({meta['env']}). "
                             f"Needed only if you switch to {meta['label']}.")
        return out
    try:
        if name == "anthropic":
            got = anthropic.Anthropic().models.retrieve(probe_model)
            label = getattr(got, "display_name", probe_model)
        else:
            got = openai.OpenAI().models.retrieve(probe_model)
            label = getattr(got, "id", probe_model)
        out.update(status="connected", detail=f"Reached {label}.")
    except Exception as e:
        n = type(e).__name__
        out.update(status="invalid" if "Auth" in n or "Permission" in n else "error",
                   detail=f"{n}: {str(e)[:160]}")
    return out


@app.get("/api/admin/credentials")
def credentials(user: dict = Depends(require_role("admin"))):
    if time.time() - _probe_cache["at"] > _PROBE_TTL or _probe_cache["data"] is None:
        _probe_cache.update(at=time.time(),
                            data=[_probe_provider(p) for p in PROVIDERS])
    return {"providers": _probe_cache["data"],
            "rotate_hint": "flyctl secrets set --app pramana ANTHROPIC_API_KEY='sk-ant-...'",
            "rotate_hint_openai": "flyctl secrets set --app pramana OPENAI_API_KEY='sk-proj-...'"}


@app.post("/api/admin/credentials/recheck")
def credentials_recheck(user: dict = Depends(require_role("admin"))):
    _probe_cache.update(at=time.time(),
                        data=[_probe_provider(p) for p in PROVIDERS])
    return {"providers": _probe_cache["data"]}


@app.get("/api/admin/providers")
def providers_list(user: dict = Depends(require_role("editor"))):
    """The provider switch: which providers exist, which is on, which are usable."""
    act = active_provider()
    return {
        "active": act,
        "providers": [
            {"key": k, "label": v["label"], "env_var": v["env"],
             "ready": provider_ready(k), "grounding": v["grounded"],
             "active": k == act,
             "models": v["models"]}
            for k, v in PROVIDERS.items()
        ],
    }


@app.post("/api/admin/providers/{name}")
def providers_activate(name: str, user: dict = Depends(require_role("admin"))):
    if name not in PROVIDERS:
        raise HTTPException(404, "unknown_provider")
    if not provider_ready(name):
        # Switching to a provider with no key would break every answer.
        raise HTTPException(409, f"no_api_key: set {PROVIDERS[name]['env']} first")
    before = active_provider()
    if before != name:
        q("UPDATE app_config SET value=?, updated_by=?, updated_at=? WHERE key='provider.active'",
          (name, user["name"], now()))
        audit(user["name"], "update",
              f"provider: {PROVIDERS[before]['label']} → {PROVIDERS[name]['label']}")
        _probe_cache.update(at=0.0, data=None)
    return {"ok": True, "active": name}


@app.get("/api/admin/audit")
def audit_list(user: dict = Depends(require_role("editor"))):
    return [dict(r) for r in
            q("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")]


def _export_rows(user_email: str = "", since: str = "") -> list[dict]:
    """Every question with the answer it produced, newest first.

    query_logs is the spine (one row per question asked); the assistant turn
    supplies the answer text and its citations, joined on query_id.
    """
    sql = """SELECT ql.created_at, ql.user_email, ql.query_id, ql.conversation_id,
                    ql.query_text, ql.tier, ql.status, ql.source_region,
                    ql.pool_outcome, ql.indian_citations, ql.intl_citations,
                    ql.latency_ms, ql.model_used, ql.feedback, ql.fallthrough,
                    t.content AS answer_text, t.result_json
             FROM query_logs ql
             LEFT JOIN turns t
               ON t.query_id = ql.query_id AND t.role = 'assistant'
             WHERE 1=1"""
    args: list = []
    if user_email:
        sql += " AND ql.user_email = ?"
        args.append(user_email)
    if since:
        sql += " AND ql.created_at >= ?"
        args.append(since)
    sql += " ORDER BY ql.created_at DESC"

    out = []
    for r in q(sql, tuple(args)):
        row = dict(r)
        cites = []
        try:
            res = json.loads(row.pop("result_json") or "{}")
            cites = res.get("citations") or []
        except Exception:
            row.pop("result_json", None)
        row["citation_count"] = len(cites)
        row["citation_domains"] = "; ".join(
            dict.fromkeys(c.get("domain", "") for c in cites if c.get("domain")))
        row["citation_urls"] = "; ".join(c.get("url", "") for c in cites if c.get("url"))
        out.append(row)
    return out


@app.get("/api/admin/usage")
def admin_usage(user: dict = Depends(require_role("editor"))):
    """Per-user activity summary — the at-a-glance view for a test round."""
    rows = q("""SELECT user_email,
                       COUNT(*)                                    AS questions,
                       SUM(CASE WHEN tier=2 THEN 1 ELSE 0 END)     AS grounded,
                       SUM(CASE WHEN tier=3 THEN 1 ELSE 0 END)     AS unverified,
                       SUM(CASE WHEN status='not_found' THEN 1 ELSE 0 END)   AS not_found,
                       SUM(CASE WHEN status='out_of_scope' THEN 1 ELSE 0 END) AS out_of_scope,
                       SUM(CASE WHEN feedback='up' THEN 1 ELSE 0 END)   AS thumbs_up,
                       SUM(CASE WHEN feedback='down' THEN 1 ELSE 0 END) AS thumbs_down,
                       ROUND(AVG(latency_ms)/1000.0, 1)            AS avg_seconds,
                       MIN(created_at) AS first_at, MAX(created_at) AS last_at
                FROM query_logs GROUP BY user_email ORDER BY questions DESC""")
    return [dict(r) for r in rows]


@app.get("/api/admin/export")
def admin_export(format: str = "json", user_email: str = "", since: str = "",
                 user: dict = Depends(require_role("editor"))):
    """Full Q&A export for analysis. format=csv streams a spreadsheet-ready
    file; format=json returns the same rows. Optional user_email / since
    (ISO date) filters."""
    rows = _export_rows(user_email, since)
    if format != "csv":
        return rows

    cols = ["created_at", "user_email", "query_text", "answer_text", "tier",
            "status", "source_region", "citation_count", "citation_domains",
            "citation_urls", "pool_outcome", "indian_citations",
            "intl_citations", "latency_ms", "model_used", "feedback",
            "fallthrough", "query_id", "conversation_id"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c) for c in cols})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="praman-qa-{stamp}.csv"'})


@app.get("/api/admin/gap-log")
def gap_log(user: dict = Depends(require_role("editor"))):
    """Corpus-gap register: unanswered / unverified / suggested-source queries."""
    return [dict(r) for r in q("""
        SELECT query_id, query_text, tier, status, high_stakes,
               suggested_source, fallthrough, source_region, created_at
        FROM query_logs
        WHERE status IN ('not_found','unverified')
           OR suggested_source=1
           OR fallthrough IS NOT NULL
        ORDER BY created_at DESC LIMIT 200""")]


# ---------------------------------------------------------------- errors & static

@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# HTML entry points (app.html, admin.html, index.html) must always revalidate,
# or a browser caches the old page and never sees a deploy — the versioned
# ?v=N query on js/css is worthless if the HTML naming it is itself stale.
# no-cache = "keep a copy but revalidate every time" (a 304 when unchanged),
# so it's cheap. JS/CSS are cache-busted by ?v=N, so they stay cacheable.
@app.middleware("http")
async def _revalidate_html(request: Request, call_next):
    resp = await call_next(request)
    if resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# Static frontend — mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
