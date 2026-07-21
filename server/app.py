"""
Pramana orchestrator — FastAPI backend for the two-tier MVP.

Tiers (Tier 1/corpus was cut from scope):
  Tier 2  — grounded web answer: Anthropic web_search server tool restricted
            to the admin-maintained allowlist (`allowed_domains`), citations
            enforced by the API, groundedness-judged.
  Tier 3  — general-model fallback, clearly labelled; withheld entirely for
            high-stakes (dosing/interaction) queries (PRD decision D1→c).

Also owns: Google auth + beta allowlist (server-side now), admin config-as-data,
audit log, query/gap logging, saved conversations, access requests.

Run:  ANTHROPIC_API_KEY=... uvicorn app:app --port 4173 --app-dir server
The frontend is served from the repo root by this same process.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
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

app = FastAPI(title="Pramana API")

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
  content TEXT, tier INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS query_logs(
  query_id TEXT PRIMARY KEY, user_email TEXT, conversation_id TEXT,
  query_text TEXT, tier INTEGER, status TEXT, high_stakes INTEGER,
  latency_ms INTEGER, model_used TEXT, feedback TEXT,
  suggested_source INTEGER DEFAULT 0, fallthrough TEXT,
  source_region TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS saved_conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, title TEXT,
  conversation_id TEXT, query TEXT, saved_at TEXT,
  UNIQUE(user_email, conversation_id));
"""

# The owner is the ONLY admin. Everyone else joins as a clinician via the
# approval queue (or is added explicitly in Admin → Beta access).
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
    ("websearch.max_uses", "3", "3", "Tier 2 search cap per query.", 0),
    ("groundedness.judge", "true", "true", "Run the judge model on Tier 2 answers.", 0),
    # Retrieval gate: a single stray source is not coverage. Applied to the
    # grounded path — fewer than this many distinct cited sources falls through.
    ("retrieval.min_chunks", "2", "2",
     "Minimum distinct cited sources before a grounded answer may be served.", 0),
    # Indian sources are searched first and international ones only if they
    # fail, so an Indian-grounded answer is never displaced by more abundant
    # Western guidance. 'indian_only' disables the international fallback.
    ("search.region_mode", "mixed", "indian_first",
     "indian_first (Indian pool searched alone first) | mixed (both regions in "
     "one call) | indian_only (no international fallback).", 1),
    # Mixed mode only. Indian slots in the first call; the rest of the cap goes
    # to international. Higher = stronger Indian presence in the ranked pool.
    ("search.mixed_indian_slots", "40", "40",
     "Mixed mode: Indian sources in the first search call (rest are international).", 1),
    # Safety switch: when false, unverified general-model answers are never
    # served — every ungrounded question returns an honest not-found instead.
    ("answers.allow_tier3", "true", "true",
     "Serve unverified Tier 3 answers. Off = grounded answers only.", 0),
    ("cost.daily_user_cap", "40", "40", "Per-clinician query cap per day.", 0),
    ("context.max_turns", "6", "6", "Conversation depth resent per request.", 0),
]


def _migrate() -> None:
    """Additive column migrations for already-deployed databases."""
    cols = {r["name"] for r in q("PRAGMA table_info(query_logs)")}
    if "fallthrough" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN fallthrough TEXT")
    if "source_region" not in cols:
        q("ALTER TABLE query_logs ADD COLUMN source_region TEXT")
    dcols = {r["name"] for r in q("PRAGMA table_info(allowlist_domains)")}
    if "region" not in dcols:
        q("ALTER TABLE allowlist_domains ADD COLUMN region TEXT NOT NULL DEFAULT 'IN'")
    if "priority" not in dcols:
        q("ALTER TABLE allowlist_domains ADD COLUMN priority INTEGER NOT NULL DEFAULT 9999")


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
    # provider switch; embeddings belonged to the cut Tier 1 corpus path.
    q("""DELETE FROM app_config WHERE key LIKE 'embedding%'
         OR key IN ('model.generation','model.tier3','model.judge')""")
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
    rows = q("""SELECT u.* FROM auth_sessions s JOIN allowed_users u
                ON u.email = s.email WHERE s.token=?""", (token,))
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

HIGH_STAKES_RE = re.compile(
    r"\b(dos(e|es|ing|age)|mg/kg|interaction|contraindicat|overdose|titrat)", re.I)

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
    "6. Be concise: 2-4 sentences, professional register, no preamble. Write "
    "plain prose — no markdown bold, headers, or bullet lists.\n"
    "7. Answer whenever the search returned relevant material, even if it is "
    "partial: report what those sources do say and note the limit. Do not "
    "discard usable sources — a partial grounded answer is more useful than a "
    "refusal.\n"
    "8. If the sources do NOT substantively answer the question, do not compose "
    "an answer, do not describe what you searched for, and do not explain what "
    "you could not find. Reply with exactly: NO_SUBSTANTIVE_ANSWER\n"
    "9. You are a reference tool, not a clinician: report what the literature "
    "says; do not add practice recommendations of your own.\n"
    "10. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)


def tier2_system(region: str) -> str:
    """Tier 2 system prompt for the pool actually being searched."""
    return ("You are Pramana, a literature reference tool for Indian "
            "healthcare professionals. Answer the clinical question using ONLY "
            "the web search results. "
            f"{_T2_POOL.get(region, _T2_POOL['IN'])}\n\n{_T2_RULES}")

# The router's ONLY refusal signal. Returned by a dedicated structured call
# because Anthropic rejects structured output combined with the Citations
# feature (400) — and API-enforced citations are the product's core promise,
# so generation keeps citations and the boolean comes from this verdict step.
VERDICT_SYSTEM = (
    "You audit a draft answer against the sources it cites. Return JSON only.\n"
    "Each cited source is tagged [IN] (Indian) or [INTL] (international).\n"
    "answered: true only if the answer states substantive findings drawn from "
    "the cited sources. It is FALSE if the text instead reports that nothing "
    "was found, describes what was searched for, says the sources do not cover "
    "the question, is empty, or only points elsewhere for the real answer.\n"
    "grounded: true only if the cited evidence supports the answer's factual "
    "claims.\n"
    "provenance_ok: false if any claim about drug dosing or dose adjustment, "
    "drug availability, formulary or NLEM status, or an Indian national "
    "programme protocol (TB, HIV, vector-borne, immunisation) rests on a "
    "source tagged [INTL]. Also false if the answer presents international "
    "guidance as though it were Indian guidance. True otherwise.\n"
    'Reply exactly: {"answered": <bool>, "grounded": <bool>, '
    '"provenance_ok": <bool>}'
)

TIER3_SYSTEM = (
    "You are Pramana's unverified fallback. The vetted literature pool — "
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
# is what the groundedness promise rests on. OpenAI's web search returns URL
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
    # Bare "(https://…)" leftovers, and markdown bold the prompt asks against.
    text = re.sub(r"\s*\(https?://[^)]*\)", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _openai_plain(client, model, system, messages) -> str:
    convo = "\n\n".join(
        f"{m['role'].upper()}: {m['content'] if isinstance(m['content'], str) else ''}"
        for m in messages)
    resp = client.responses.create(model=model, instructions=system,
                                   input=convo, max_output_tokens=1024)
    return _strip_md_links(getattr(resp, "output_text", "") or "")


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


def _verdict(question: str, answer: str, citations: list[dict]) -> dict:
    """Structured refusal + groundedness signal. Booleans only.

    Returns {"answered": bool, "grounded": bool, "ok": bool}. `ok` is False if
    the verdict call itself failed, which the router treats conservatively:
    an unverifiable answer is never served behind a grounded badge.
    """
    if not citations:
        return {"answered": False, "grounded": False,
                "provenance_ok": False, "ok": True}
    evidence = "\n".join(
        f"[{'INTL' if c.get('region') == 'INTL' else 'IN'}] {c['domain']} — "
        f"{c['cited_text'][:400]}" for c in citations[:8])
    prompt = (f"Question: {question}\n\nDraft answer: {answer}\n\n"
              f"Cited sources:\n{evidence}")
    judge_model = model_for("judge")
    schema = {"type": "object",
              "properties": {"answered": {"type": "boolean"},
                             "grounded": {"type": "boolean"},
                             "provenance_ok": {"type": "boolean"}},
              "required": ["answered", "grounded", "provenance_ok"],
              "additionalProperties": False}
    for _ in range(2):                     # one retry; transient failures happen
        try:
            jc = _client(judge_model)
            if provider_of(judge_model) == "openai":
                # Reasoning models spend max_output_tokens on internal
                # reasoning first: a small budget returns status=incomplete
                # with empty output_text, which silently failed every verdict.
                r = jc.responses.create(model=judge_model,
                                        instructions=VERDICT_SYSTEM,
                                        input=prompt, max_output_tokens=2000)
                text = getattr(r, "output_text", "") or ""
                if getattr(r, "status", "") == "incomplete" and not text.strip():
                    raise RuntimeError("verdict truncated by token budget")
            else:
                resp = jc.messages.create(
                    model=judge_model, max_tokens=256,
                    system=[{"type": "text", "text": VERDICT_SYSTEM}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                    messages=[{"role": "user", "content": prompt}],
                )
                text = next(b.text for b in resp.content if b.type == "text")
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0) if m else text)
            grounded = bool(data.get("grounded"))
            if cfg("groundedness.judge", "true") != "true":
                grounded = True            # judge disabled by admin switch
            # Absent key means the judge did not assert a violation. Defaulting
            # to False here would refuse every Indian-pass answer.
            return {"answered": bool(data.get("answered")),
                    "grounded": grounded,
                    "provenance_ok": bool(data.get("provenance_ok", True)),
                    "ok": True}
        except Exception:
            continue
    return {"answered": False, "grounded": False,
            "provenance_ok": False, "ok": False}


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
        text, citations = _openai_grounded(client, model, system, msgs,
                                           domains, max_uses)
        return text, citations, model, False
    resp = _run_with_pause_turn(
        client, model=model, max_tokens=2048,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[{"type": "web_search_20260209", "name": "web_search",
                "max_uses": max_uses, "allowed_domains": domains}],
        messages=msgs,
    )
    segments, citations, plain = _extract_answer(resp)
    return plain, citations, resp.model, resp.stop_reason == "refusal"


def _load_history(conversation_id: str) -> list[dict]:
    max_turns = int(cfg("context.max_turns", "6"))
    rows = q("""SELECT role, content FROM turns WHERE conversation_id=?
                ORDER BY id DESC LIMIT ?""", (conversation_id, max_turns))
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


@app.post("/api/ask")
def ask(body: dict, request: Request, user: dict = Depends(current_user)):
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(400, "empty_query")

    # per-user daily cap (PRD cost guardrail)
    cap = int(cfg("cost.daily_user_cap", "40"))
    used = q("""SELECT COUNT(*) n FROM query_logs WHERE user_email=?
                AND created_at > datetime('now','-1 day')""", (user["email"],))[0]["n"]
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
        high_stakes = bool(HIGH_STAKES_RE.search(query))
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
            "high_stakes": high_stakes, "sources_searched": sources_searched,
            "retrieved_at": today(), "citations": [], "followups": [],
            "source_region": None,
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

        if region_mode == "mixed":
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
            yield sse("stage", {"label": f"Searching {len(pool)} allowlisted {label} "
                                         f"sources{part} via {PROVIDERS[prov]['label']}"})
            try:
                plain, citations, used_model, refused = _grounded_answer(
                    model, tier2_system(region), msgs, pool, effort,
                    int(cfg("websearch.max_uses", "3")))
            except HTTPException as e:
                yield sse("error", {"detail": str(e.detail)})
                return
            except Exception as e:
                yield sse("stage", {"label": f"{label.capitalize()} search unavailable",
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
                yield sse("stage", {"label": f"Only {len(citations)} qualifying {label} "
                                             f"source{'' if len(citations)==1 else 's'} — "
                                             f"below the minimum of {min_chunks}"})
            else:
                yield sse("stage", {"label": f"Retrieved {len(citations)} cited "
                                             f"{label} passages"})
                yield sse("stage", {"label": "Checking the answer against its sources"})
                # Tag before the verdict: the judge decides provenance from the
                # [IN]/[INTL] markers, so untagged citations would read as Indian.
                # Tagged per domain, not per pass — a mixed pool returns both.
                for c in citations:
                    c["region"] = cite_region(c.get("domain", ""))
                v = _verdict(query, plain, citations)
                if not v["ok"]:
                    fell(2, f"verdict_unavailable:{tag}")
                elif not v["answered"]:
                    # THE regression guard: the model produced prose but it does
                    # not substantively answer. Never serve this behind a badge.
                    fell(2, f"not_answered:{tag}")
                elif not v["grounded"]:
                    fell(2, f"not_grounded:{tag}")
                elif not v.get("provenance_ok", True):
                    # Dosing/NLEM/programme claim resting on foreign guidance,
                    # or international guidance dressed up as Indian. Same
                    # severity as ungrounded: refuse rather than render.
                    fell(2, f"provenance_violation:{tag}")
                else:
                    answered_t2 = True
                    # Derived from what was actually cited, not from which pool
                    # was searched: a mixed pool can produce a purely Indian
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
        if not answered_t2:
            tier3_enabled = cfg("answers.allow_tier3", "true") == "true"
            if high_stakes or not tier3_enabled:
                reason = "high_stakes" if high_stakes else "tier3_disabled"
                fell(3, reason)
                yield sse("stage", {"label": "High-stakes query — withholding unverified answer"
                                    if high_stakes else
                                    "Grounded-only mode — no unverified answer shown"})
                result.update({
                    "tier": None, "status": "not_found", "withheld_reason": reason,
                    "answer_text": "", "segments": [], "model_used": None,
                })
            else:
                t3_model, t3_prov = model, prov
                yield sse("stage", {"label": "No grounded source — falling back to "
                                             f"{PROVIDERS[t3_prov]['label']} general model"})
                try:
                    t3_client = _client(t3_model)
                    if t3_prov == "openai":
                        plain = _openai_plain(t3_client, t3_model, TIER3_SYSTEM, msgs)
                        used = t3_model
                    else:
                        t3 = t3_client.messages.create(
                            model=t3_model, max_tokens=1024,
                            thinking={"type": "adaptive"},
                            output_config={"effort": effort},
                            system=[{"type": "text", "text": TIER3_SYSTEM,
                                     "cache_control": {"type": "ephemeral"}}],
                            messages=msgs,
                        )
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
             source_region,created_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (query_id, user["email"], conversation_id, query, result["tier"],
           result["status"], int(high_stakes), result["latency_ms"],
           result.get("model_used"),
           json.dumps(falls) if falls else None,
           result.get("source_region"), now()))
        q("INSERT INTO turns(conversation_id,role,content,tier,created_at) VALUES(?,?,?,?,?)",
          (conversation_id, "user", query, None, now()))
        if result.get("answer_text"):
            q("INSERT INTO turns(conversation_id,role,content,tier,created_at) VALUES(?,?,?,?,?)",
              (conversation_id, "assistant", result["answer_text"], result["tier"], now()))

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

@app.get("/api/library")
def library_list(user: dict = Depends(current_user)):
    rows = q("""SELECT id,title,query,saved_at FROM saved_conversations
                WHERE user_email=? ORDER BY id DESC""", (user["email"],))
    return [dict(r) for r in rows]


@app.post("/api/library")
def library_save(body: dict, user: dict = Depends(current_user)):
    q("""INSERT OR IGNORE INTO saved_conversations
         (user_email,title,conversation_id,query,saved_at) VALUES(?,?,?,?,?)""",
      (user["email"], str(body.get("title", ""))[:120],
       body.get("conversation_id") or str(uuid.uuid4()),
       str(body.get("query", ""))[:500], today()))
    return {"ok": True}


@app.delete("/api/library/{item_id}")
def library_delete(item_id: int, user: dict = Depends(current_user)):
    q("DELETE FROM saved_conversations WHERE id=? AND user_email=?",
      (item_id, user["email"]))
    return {"ok": True}


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

# Static frontend — mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
