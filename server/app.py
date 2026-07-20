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
  enabled INTEGER NOT NULL DEFAULT 1, added_by TEXT, created_at TEXT);
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
  suggested_source INTEGER DEFAULT 0, created_at TEXT);
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
SEED_DOMAINS = [
    ("icmr.gov.in", "Indian Council of Medical Research — apex national research & guideline body."),
    ("main.mohfw.gov.in", "Ministry of Health & Family Welfare — official policy & STGs."),
    ("ijmr.org.in", "Indian Journal of Medical Research — ICMR peer-reviewed journal."),
    ("nmji.in", "National Medical Journal of India — peer-reviewed, AIIMS-affiliated."),
    ("indianpediatrics.net", "Indian Pediatrics — IAP official journal."),
    ("cdsco.gov.in", "Central Drugs Standard Control Organisation — drug approvals & safety."),
]
# key, value, default, description, critical
SEED_CONFIG = [
    ("model.generation", "claude-opus-4-8", "claude-opus-4-8", "Model ID for Tier 2/3 generation.", 1),
    ("model.judge", "claude-haiku-4-5", "claude-haiku-4-5", "Model for the groundedness check.", 0),
    ("generation.effort", "medium", "medium", "Effort level for generation (low|medium|high).", 0),
    ("websearch.max_uses", "3", "3", "Tier 2 search cap per query.", 0),
    ("groundedness.judge", "true", "true", "Run the judge model on Tier 2 answers.", 0),
    ("cost.daily_user_cap", "40", "40", "Per-clinician query cap per day.", 0),
    ("context.max_turns", "6", "6", "Conversation depth resent per request.", 0),
]


def init_db() -> None:
    with _db_lock:
        _db.executescript(SCHEMA)
        _db.commit()
    if not q("SELECT 1 FROM allowed_users LIMIT 1"):
        for email, name, role, enabled, by in SEED_USERS:
            q("INSERT INTO allowed_users VALUES(?,?,?,?,?,?,NULL)",
              (email, name, role, enabled, by, now()))
    if not q("SELECT 1 FROM allowlist_domains LIMIT 1"):
        for domain, note in SEED_DOMAINS:
            q("INSERT INTO allowlist_domains VALUES(?,?,1,'system',?)", (domain, note, now()))
    if not q("SELECT 1 FROM app_config LIMIT 1"):
        for key, value, default, desc, critical in SEED_CONFIG:
            q("INSERT INTO app_config VALUES(?,?,?,?,?,'system',?)",
              (key, value, default, desc, critical, now()))
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

TIER2_SYSTEM = (
    "You are Pramana, a literature reference tool for Indian healthcare "
    "professionals. Answer the clinical question using ONLY the web search "
    "results, which are restricted to vetted Indian medical domains (ICMR, "
    "MoHFW, Indian journals). Rules:\n"
    "1. Every factual claim must come from the search results — the API "
    "attaches citations; never state anything you cannot cite.\n"
    "2. Be concise: 2-4 sentences of answer, professional register, no preamble.\n"
    "3. If the allowlisted sources do not contain enough to answer, respond "
    "with exactly [[NOT_FOUND]] and nothing else.\n"
    "4. You are a reference tool, not a clinician: report what the literature "
    "says; do not add practice recommendations of your own.\n"
    "5. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)

TIER3_SYSTEM = (
    "You are Pramana's unverified fallback. The indexed Indian literature did "
    "not cover this question, so you are answering from general knowledge. "
    "Rules:\n"
    "1. Begin the substance of the answer with the word 'Generally' or "
    "similar hedging; keep it to 2-4 sentences.\n"
    "2. State explicitly that this may not match Indian guidelines, drug "
    "availability, or approved indications.\n"
    "3. Never invent citations or reference specific Indian guidelines.\n"
    "4. After the answer, on a new line, write [[FOLLOWUPS]] followed by two "
    "short follow-up questions separated by ' | '."
)


def _client():
    if anthropic is None:
        raise HTTPException(503, "anthropic_sdk_missing")
    try:
        return anthropic.Anthropic()
    except Exception as e:  # missing credentials
        raise HTTPException(503, f"anthropic_credentials: {e}")


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


def _judge_grounded(client, question: str, answer: str, citations: list[dict]) -> bool:
    """Cheap judge (PRD §7.4): do the cited passages support the answer?"""
    if cfg("groundedness.judge") != "true" or not citations:
        return bool(citations)
    evidence = "\n".join(f"- {c['cited_text'][:400]} ({c['domain']})" for c in citations[:8])
    try:
        resp = client.messages.create(
            model=cfg("model.judge", "claude-haiku-4-5"),
            max_tokens=256,
            output_config={"format": {"type": "json_schema", "schema": {
                "type": "object",
                "properties": {"grounded": {"type": "boolean"}},
                "required": ["grounded"], "additionalProperties": False}}},
            messages=[{"role": "user", "content":
                       f"Question: {question}\n\nAnswer: {answer}\n\nCited passages:\n{evidence}\n\n"
                       "Does the cited evidence support every factual claim in the answer?"}],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return bool(json.loads(text).get("grounded"))
    except Exception:
        # Judge failure must not take the product down; deterministic
        # citation-presence check already passed.
        return True


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
        domains = [r["domain"] for r in
                   q("SELECT domain FROM allowlist_domains WHERE enabled=1")]
        sources_searched = [f"web:{d}" for d in domains]
        history = _load_history(conversation_id)
        result: dict = {
            "query_id": query_id, "conversation_id": conversation_id,
            "high_stakes": high_stakes, "sources_searched": sources_searched,
            "retrieved_at": today(), "citations": [], "followups": [],
        }

        try:
            client = _client()
        except HTTPException as e:
            yield sse("error", {"detail": e.detail})
            return

        model = cfg("model.generation", "claude-opus-4-8")
        effort = cfg("generation.effort", "medium")

        # ---------- Tier 2: allowlisted web search ----------
        tier2_resp = None
        if domains:
            yield sse("stage", {"label": f"Searching {len(domains)} allowlisted Indian domains"})
            try:
                tier2_resp = _run_with_pause_turn(
                    client,
                    model=model,
                    max_tokens=2048,
                    thinking={"type": "adaptive"},
                    output_config={"effort": effort},
                    system=[{"type": "text", "text": TIER2_SYSTEM,
                             "cache_control": {"type": "ephemeral"}}],
                    tools=[{"type": "web_search_20260209", "name": "web_search",
                            "max_uses": int(cfg("websearch.max_uses", "3")),
                            "allowed_domains": domains}],
                    messages=history + [{"role": "user", "content": query}],
                )
            except Exception as e:
                yield sse("stage", {"label": "Web search unavailable", "state": "warn"})
                yield sse("error", {"detail": f"generation_failed: {e}"})
                return

        answered_t2 = False
        if tier2_resp is not None and tier2_resp.stop_reason != "refusal":
            segments, citations, plain = _extract_answer(tier2_resp)
            plain, followups = _parse_followups(plain)
            if segments:
                segments[-1]["text"], _ = _parse_followups(segments[-1]["text"])
            not_found = "[[NOT_FOUND]]" in plain or not citations
            if not not_found:
                yield sse("stage", {"label": f"Retrieved {len(citations)} cited passages"})
                yield sse("stage", {"label": "Checking groundedness"})
                if _judge_grounded(client, query, plain, citations):
                    answered_t2 = True
                    result.update({
                        "tier": 2, "status": "answered", "answer_text": plain,
                        "segments": segments, "citations": citations,
                        "followups": followups, "model_used": tier2_resp.model,
                    })

        # ---------- Tier 3 / withheld ----------
        if not answered_t2:
            if high_stakes:
                yield sse("stage", {"label": "High-stakes query — withholding unverified answer"})
                result.update({
                    "tier": 3, "status": "not_found",
                    "answer_text": "Not found in the indexed Indian literature. "
                                   "This looks like a dosing or interaction question, so no "
                                   "unverified general-model answer is shown.",
                    "segments": [], "model_used": None,
                })
            else:
                yield sse("stage", {"label": "No grounded source — falling back to general model"})
                try:
                    t3 = client.messages.create(
                        model=model, max_tokens=1024,
                        thinking={"type": "adaptive"},
                        output_config={"effort": effort},
                        system=[{"type": "text", "text": TIER3_SYSTEM,
                                 "cache_control": {"type": "ephemeral"}}],
                        messages=history + [{"role": "user", "content": query}],
                    )
                except Exception as e:
                    yield sse("error", {"detail": f"generation_failed: {e}"})
                    return
                if t3.stop_reason == "refusal":
                    plain, followups = "The model declined to answer this question.", []
                else:
                    plain = "\n".join(b.text for b in t3.content if b.type == "text")
                    plain, followups = _parse_followups(plain)
                result.update({
                    "tier": 3, "status": "unverified", "answer_text": plain,
                    "segments": [{"text": plain, "citations": []}],
                    "followups": followups, "model_used": t3.model,
                })

        result["latency_ms"] = int((time.time() - started) * 1000)

        # log + persist the turn (PRD: instrument everything)
        q("""INSERT INTO query_logs(query_id,user_email,conversation_id,query_text,
             tier,status,high_stakes,latency_ms,model_used,created_at)
             VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (query_id, user["email"], conversation_id, query, result["tier"],
           result["status"], int(high_stakes), result["latency_ms"],
           result.get("model_used"), now()))
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
    rows = q("SELECT domain, trust_note FROM allowlist_domains WHERE enabled=1 ORDER BY domain")
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
    if q("SELECT 1 FROM allowlist_domains WHERE domain=?", (domain,)):
        raise HTTPException(409, "duplicate")
    q("INSERT INTO allowlist_domains VALUES(?,?,1,?,?)", (domain, note, user["name"], now()))
    audit(user["name"], "create", f"domain {domain} added")
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
    return {"ok": True}


@app.get("/api/admin/audit")
def audit_list(user: dict = Depends(require_role("editor"))):
    return [dict(r) for r in
            q("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")]


@app.get("/api/admin/gap-log")
def gap_log(user: dict = Depends(require_role("editor"))):
    """Corpus-gap register: unanswered / unverified / suggested-source queries."""
    return [dict(r) for r in q("""
        SELECT query_id, query_text, tier, status, high_stakes,
               suggested_source, created_at
        FROM query_logs
        WHERE status IN ('not_found','unverified') OR suggested_source=1
        ORDER BY created_at DESC LIMIT 200""")]


# ---------------------------------------------------------------- errors & static

@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Static frontend — mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")
