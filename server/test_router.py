"""Router regression tests.

Runs the real FastAPI app against a throwaway database with the provider
calls stubbed, so the tier/fall-through logic is exercised end-to-end
without network access or API keys.

    server/.venv/bin/python server/test_router.py

The bug under guard: a model that composes a refusal ("the search did not
retrieve any current advisory…") while citations are attached was being
served behind a green "Grounded · Tier 2" badge. The router must now read
the structured `answered` boolean and never infer refusal from prose.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["PRAMANA_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("PRAMANA_DEMO_PASSWORD", None)
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-used"   # provider calls are stubbed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as A                                          # noqa: E402
from fastapi.testclient import TestClient                 # noqa: E402

client = TestClient(A.app)
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")


def token() -> str:
    r = client.post("/api/auth/demo", json={"email": "k.prasad.iitr@gmail.com"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


AUTH = {"Authorization": f"Bearer {token()}"}


def ask(query: str) -> dict:
    """Drive /api/ask and return the parsed `result` event."""
    with client.stream("POST", "/api/ask", json={"query": query}, headers=AUTH) as r:
        assert r.status_code == 200, r.text
        event, result = None, None
        for line in r.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "result":
                result = json.loads(line[6:])
        return result


def stub(*, text: str, citations: list[dict], answered: bool,
         grounded: bool = True, verdict_ok: bool = True,
         t3_text: str = "Generally, this is a fallback answer."):
    """Replace the provider calls with deterministic fakes."""
    A._grounded_answer = lambda *a, **k: (text, citations, "stub-model", False)
    A._verdict = lambda *a, **k: {"answered": answered, "grounded": grounded,
                                  "ok": verdict_ok}
    A._openai_plain = lambda *a, **k: t3_text
    A._client = lambda model: object()

    class _Blk:
        type = "text"; text = t3_text

    class _Resp:
        model = "stub-model"; stop_reason = "end_turn"; content = [_Blk()]

    class _Msgs:
        def create(self, **k):
            return _Resp()

    class _C:
        messages = _Msgs()

    A._client = lambda model: _C()


CITE = [{"cited_text": "Metformin is first line.", "url": "https://icmr.gov.in/a",
         "title": "ICMR", "domain": "icmr.gov.in"},
        {"cited_text": "Target HbA1c <7%.", "url": "https://main.mohfw.gov.in/b",
         "title": "MoHFW", "domain": "main.mohfw.gov.in"}]

print("\nRouter regression tests\n" + "=" * 60)

# ---------------------------------------------------------------- test 1
# Sources retrieved but irrelevant: the model's prose is a refusal. The
# router must read answered:false and fall through — no Tier 2 emitted.
print("\n1. Irrelevant sources → answered:false → falls through, no Tier 2")
stub(text="The restricted search did not retrieve any current ICMR advisory "
          "specifying fluid management protocols.",
     citations=CITE, answered=False)
r1 = ask("Current ICMR advisory on dengue fluid management?")
check("tier is not 2", r1["tier"] != 2, f"tier={r1['tier']}")
check("no grounded status", r1["status"] != "answered", f"status={r1['status']}")
check("refusal prose never served as the answer",
      "did not retrieve" not in (r1.get("answer_text") or ""))
check("fall-through logged with tier+reason",
      any(f["tier"] == 2 and f["reason"] == "not_answered"
          for f in (r1.get("fallthrough") or [])),
      str(r1.get("fallthrough")))

# ---------------------------------------------------------------- test 2
# One result, below retrieval.min_chunks (2): generation result must be
# discarded and the router proceeds without serving Tier 2.
print("\n2. Single source below min_chunks → no Tier 2, falls through")
stub(text="A perfectly good grounded answer.", citations=CITE[:1], answered=True)
r2 = ask("Something with only one source?")
check("tier is not 2", r2["tier"] != 2, f"tier={r2['tier']}")
check("min_chunks fall-through logged",
      any(f["tier"] == 2 and f["reason"].startswith("below_min_chunks")
          for f in (r2.get("fallthrough") or [])),
      str(r2.get("fallthrough")))

# ---------------------------------------------------------------- test 3
# All tiers fail → not_found, tier null, sources_searched populated.
print("\n3. All tiers fail → status:not_found, tier:null, sources_searched set")
stub(text="", citations=[], answered=False, t3_text="")
r3 = ask("A question nothing can answer?")
check("status is not_found", r3["status"] == "not_found", f"status={r3['status']}")
check("tier is null", r3["tier"] is None, f"tier={r3['tier']}")
check("sources_searched populated", len(r3.get("sources_searched") or []) > 0,
      str(r3.get("sources_searched"))[:80])
check("no synthesized answer text", not (r3.get("answer_text") or "").strip())

# ---------------------------------------------------------------- test 4
# THE regression guard: answered:false must never serialize with a tier.
print("\n4. Regression guard: answered:false never serialized with a tier")
cases = [
    ("refusal prose + citations", "The search did not find anything relevant.", CITE, False),
    ("empty text + citations", "", CITE, False),
    ("refusal + single citation", "No guidance located.", CITE[:1], False),
]
for label, text, cites, answered in cases:
    stub(text=text, citations=cites, answered=answered, t3_text="")
    rr = ask(f"probe: {label}")
    ok = rr["tier"] is None and rr["status"] == "not_found"
    check(f"{label} → tier null / not_found", ok,
          f"tier={rr['tier']} status={rr['status']}")

# verdict unavailable must also never be served behind a badge
stub(text="Looks grounded but unverifiable.", citations=CITE,
     answered=True, verdict_ok=False, t3_text="")
r4b = ask("verdict unavailable probe")
check("verdict failure → never Tier 2", r4b["tier"] != 2, f"tier={r4b['tier']}")

# not_grounded must also fall through
stub(text="Claims not supported by sources.", citations=CITE,
     answered=True, grounded=False, t3_text="")
r4c = ask("ungrounded probe")
check("not_grounded → never Tier 2", r4c["tier"] != 2, f"tier={r4c['tier']}")

# ---------------------------------------------------------------- test 5
# The observed case: IDH / AV-thrombosis. Must be Tier 3 (unverified) or
# not_found — never a Tier 2 grounded answer.
print("\n5. Observed case: IDH / AV-access thrombosis")
IDH = ("Association between intradialytic hypotension and "
       "arteriovenous access thrombosis in haemodialysis patients?")

stub(text="The searched Indian sources do not address the association between "
          "intradialytic hypotension and AV access thrombosis.",
     citations=CITE, answered=False,
     t3_text="Generally, intradialytic hypotension is considered a risk factor "
             "for vascular access thrombosis. This may not match Indian guidelines.")
r5a = ask(IDH)
check("refusal → not Tier 2", r5a["tier"] != 2, f"tier={r5a['tier']}")
check("outcome is Tier 3 unverified or not_found",
      (r5a["tier"] == 3 and r5a["status"] == "unverified")
      or (r5a["tier"] is None and r5a["status"] == "not_found"),
      f"tier={r5a['tier']} status={r5a['status']}")
if r5a["tier"] == 3:
    check("Tier 3 answer carries no citations", not r5a.get("citations"))

# same query, Tier 3 also unavailable → not_found
stub(text="Indian sources do not cover this.", citations=CITE,
     answered=False, t3_text="")
r5b = ask(IDH)
check("Tier 3 unavailable → not_found + tier null",
      r5b["tier"] is None and r5b["status"] == "not_found",
      f"tier={r5b['tier']} status={r5b['status']}")
check("sources_searched shown to the clinician",
      len(r5b.get("sources_searched") or []) > 0)

# ---------------------------------------------------------------- invariant
print("\n6. Contract: field names unchanged, thresholds from app_config")
for f in ("tier", "status", "citations", "sources_searched"):
    check(f"contract field '{f}' present", f in r5b, str(sorted(r5b))[:80])
rows = A.q("SELECT value FROM app_config WHERE key='retrieval.min_chunks'")
check("retrieval.min_chunks read from app_config", bool(rows),
      "config key missing")

# gap log captures the fall-throughs
gap = client.get("/api/admin/gap-log", headers=AUTH).json()
check("gap log captured fall-through rows", len(gap) > 0, f"rows={len(gap)}")
check("fall-through reasons persisted to query_logs",
      any(g.get("fallthrough") for g in gap),
      "no fallthrough column populated")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All router tests passed.")
