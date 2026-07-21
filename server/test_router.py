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
REAL_VERDICT = A._verdict          # kept before the stubs replace it


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")


def token() -> str:
    r = client.post("/api/auth/demo", json={"email": "k.prasad.iitr@gmail.com"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


AUTH = {"Authorization": f"Bearer {token()}"}

# Tests 1-9 exercise sequential routing; test 10 switches to mixed. Pin the
# mode rather than inheriting whatever the seeded default happens to be.
A.q("UPDATE app_config SET value='indian_first' WHERE key='search.region_mode'")


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
      any(f["tier"] == 2 and f["reason"].startswith("not_answered")
          for f in (r1.get("fallthrough") or [])),
      str(r1.get("fallthrough")))
reasons1 = {f["reason"] for f in (r1.get("fallthrough") or [])}
check("both regions attempted before falling through",
      any(r.startswith("not_answered:IN") for r in reasons1)
      and any(r.startswith("not_answered:INTL") for r in reasons1),
      str(reasons1))

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

# ---------------------------------------------------------------- test 7
# Region routing: Indian sources answer first and international is only
# reached when the Indian pass fails, so abundant Western guidance can
# never displace an Indian-grounded answer.
print("\n7. Region routing: Indian first, international as labelled fallback")

INTL_CITE = [{"cited_text": "KDIGO guidance.", "url": "https://kdigo.org/x",
              "title": "KDIGO", "domain": "kdigo.org"},
             {"cited_text": "NICE guidance.", "url": "https://nice.org.uk/y",
              "title": "NICE", "domain": "nice.org.uk"}]

IN_DOMAINS = {d["domain"] for d in CITE}


def region_stub(*, indian_answers: bool):
    """Vary the provider result by which domain pool the router passed in."""
    seen: list[str] = []

    def _ga(model, system, msgs, pool, effort, max_uses):
        is_indian = any(d in IN_DOMAINS or d.endswith((".in", ".gov.in"))
                        for d in pool)
        seen.append("IN" if is_indian else "INTL")
        if is_indian:
            return (("An Indian-grounded answer." if indian_answers else
                     "Indian sources do not address this."),
                    CITE, "stub-model", False)
        return ("An international-grounded answer.", INTL_CITE, "stub-model", False)

    A._grounded_answer = _ga
    A._verdict = lambda query, answer, cites: {
        "answered": "do not address" not in answer, "grounded": True, "ok": True}
    return seen

seen = region_stub(indian_answers=True)
r7a = ask("A question Indian sources answer?")
check("Indian answer served as Tier 2", r7a["tier"] == 2, f"tier={r7a['tier']}")
check("source_region is IN", r7a.get("source_region") == "IN",
      str(r7a.get("source_region")))
check("international pass never run when India answers",
      "INTL" not in seen, str(seen))
check("stops at the first batch that answers", len(seen) == 1, str(seen))
check("citations tagged with region",
      all(c.get("region") == "IN" for c in r7a["citations"]),
      str(r7a["citations"])[:120])

seen = region_stub(indian_answers=False)
r7b = ask("A question only international sources answer?")
check("falls through to international", r7b["tier"] == 2, f"tier={r7b['tier']}")
check("source_region is INTL", r7b.get("source_region") == "INTL",
      str(r7b.get("source_region")))
check("every Indian batch tried before any international one",
      seen.index("INTL") == seen.count("IN"), str(seen))
check("Indian fall-through logged before international answer",
      any(":IN" in f["reason"] and ":INTL" not in f["reason"]
          for f in (r7b.get("fallthrough") or [])),
      str(r7b.get("fallthrough")))
check("citations tagged INTL",
      all(c.get("region") == "INTL" for c in r7b["citations"]),
      str(r7b["citations"])[:120])

# indian_only mode must never reach international sources
A.q("UPDATE app_config SET value='indian_only' WHERE key='search.region_mode'")
seen = region_stub(indian_answers=False)
r7c = ask("indian_only probe")
check("indian_only never searches international", "INTL" not in seen, str(seen))
check("indian_only yields no Tier 2 when India cannot answer",
      r7c["tier"] != 2, f"tier={r7c['tier']}")
A.q("UPDATE app_config SET value='indian_first' WHERE key='search.region_mode'")

# region-tagged seeding
counts = {r["region"]: r["n"] for r in A.q(
    "SELECT region, COUNT(*) n FROM allowlist_domains GROUP BY region")}
check("both regions seeded", counts.get("IN", 0) > 0 and counts.get("INTL", 0) > 0,
      str(counts))
check("source_region persisted to query_logs",
      bool(A.q("SELECT 1 FROM query_logs WHERE source_region='INTL'")),
      "no INTL row logged")

# ---------------------------------------------------------------- test 8
# Provenance: a dosing/NLEM/programme claim resting on international
# sources must be refused with the same severity as an ungrounded one.
print("\n8. Provenance violation refused like an ungrounded answer")
A._grounded_answer = lambda *a, **k: (
    "Generally the dose is 5 mg/kg daily.", list(CITE), "stub-model", False)
A._verdict = lambda *a, **k: {"answered": True, "grounded": True,
                              "provenance_ok": False, "ok": True}
A._openai_plain = lambda *a, **k: ""
r8 = ask("What is the dose in renal impairment?")
check("provenance violation → never Tier 2", r8["tier"] != 2, f"tier={r8['tier']}")
check("provenance fall-through logged",
      any(f["reason"].startswith("provenance_violation")
          for f in (r8.get("fallthrough") or [])),
      str(r8.get("fallthrough")))

# A judge that omits provenance_ok must not refuse every answer — defaulting
# the absent key to False would silently kill the whole Indian pass.
class _JudgeResp:
    class _B:
        type = "text"
        text = '{"answered": true, "grounded": true}'
    content = [_B()]


class _JudgeClient:
    class messages:
        @staticmethod
        def create(**k):
            return _JudgeResp()


A._client = lambda model: _JudgeClient()
v = REAL_VERDICT("q", "a", [{"cited_text": "x", "domain": "icmr.gov.in",
                             "region": "IN"}])
check("absent provenance_ok defaults to permissive",
      v["provenance_ok"] is True and v["ok"] is True, str(v))
check("no citations → provenance_ok is False",
      REAL_VERDICT("q", "a", [])["provenance_ok"] is False)

# ---------------------------------------------------------------- test 9
# Snapshot: the pool sent and the prompt describing it must agree. This is
# the class of test that would have caught the Indian-prompt-with-
# international-pool defect.
print("\n9. Snapshot: assembled prompt matches the pool actually sent")
INTL_SET = {d["domain"] for d in INTL_CITE} | {"who.int", "nice.org.uk"}
calls: list[tuple[str, list]] = []


def _capture(model, system, msgs, pool, effort, max_uses):
    calls.append((system, list(pool)))
    return ("Indian sources do not address this.", CITE, "stub-model", False)


A._grounded_answer = _capture
A._verdict = lambda q, a, c: {"answered": False, "grounded": True,
                              "provenance_ok": True, "ok": True}
A._openai_plain = lambda *a, **k: ""
calls.clear()
ask("A question that exhausts both passes?")

live_intl = {r["domain"] for r in A.q(
    "SELECT domain FROM allowlist_domains WHERE enabled=1 AND region='INTL'")}
live_in = {r["domain"] for r in A.q(
    "SELECT domain FROM allowlist_domains WHERE enabled=1 AND region='IN'")}

in_calls = [(s, p) for s, p in calls if not (set(p) & live_intl)]
intl_calls = [(s, p) for s, p in calls if set(p) & live_intl]
in_sys, _ = in_calls[0]
intl_sys, _ = intl_calls[0]

# THE outage guard: a pool longer than the provider cap is a 400, so Tier 2
# silently never runs. Every batch must sit inside the cap.
CAP = A.PROVIDERS[A.active_provider()].get("max_domains", 100)
check(f"no batch exceeds the provider cap of {CAP}",
      all(len(p) <= CAP for _, p in calls),
      f"sizes={[len(p) for _, p in calls]}")
check("batches are non-empty", all(p for _, p in calls))

# batching must not lose domains: the union of every batch is the full pool
searched = {d for _, p in calls for d in p}
check("every enabled Indian domain is searched",
      live_in <= searched, str(sorted(live_in - searched))[:120])
check("every enabled international domain is searched",
      live_intl <= searched, str(sorted(live_intl - searched))[:120])
check("no domain searched twice",
      sum(len(p) for _, p in calls) == len(searched),
      f"sent={sum(len(p) for _, p in calls)} unique={len(searched)}")

# region purity survives batching
check("Indian batches contain zero INTL domains",
      all(not (set(p) & live_intl) for _, p in in_calls))
check("international batches contain only INTL domains",
      all(set(p) <= live_intl for _, p in intl_calls))
check("apex bodies land in the first Indian batch",
      "icmr.gov.in" in in_calls[0][1] and "main.mohfw.gov.in" in in_calls[0][1],
      str(in_calls[0][1][:4]))

# prompt text must describe the pool it was sent with
check("Indian prompt does not claim international results",
      "international guideline and literature" not in in_sys, in_sys[:160])
check("international prompt says no Indian source covered it",
      "No Indian source" in intl_sys, intl_sys[:160])
check("both prompts carry the provenance rule",
      all("NLEM status" in s for s in (in_sys, intl_sys)))
check("both prompts carry the refusal sentinel",
      all("NO_SUBSTANTIVE_ANSWER" in s for s in (in_sys, intl_sys)))
check("both prompts ask for structure and quotes",
      all("LENGTH AND STRUCTURE" in s and "QUOTE THE SOURCES" in s
          for s in (in_sys, intl_sys)))

# Markdown structure must survive the link stripper: it used to remove bold,
# which would silently undo the formatting the prompt now asks for.
md = A._strip_md_links(
    "## Mechanism\n**60-80%** of cases, see [JASN](https://x.example/a).\n"
    "> Low-flow states precipitate thrombosis.\n1. Flow falls.")
check("bold survives the stripper", "**60-80%**" in md, md[:120])
check("headings survive the stripper", "## Mechanism" in md, md[:120])
check("blockquotes survive the stripper", "> Low-flow" in md, md[:120])
check("numbered steps survive the stripper", "1. Flow falls." in md, md[:120])
check("markdown links are still stripped", "https://x.example" not in md, md[:120])

# the verdict must see region tags, not bare domains
seen_prompt: list[str] = []
A._grounded_answer = lambda *a, **k: ("An answer.", list(INTL_CITE), "m", False)


def _spy_verdict(question, answer, citations):
    seen_prompt.append("".join(
        f"[{c.get('region')}]" for c in citations))
    return {"answered": True, "grounded": True, "provenance_ok": True, "ok": True}


A._verdict = _spy_verdict
ask("tagging probe")
check("citations tagged before the verdict call",
      seen_prompt and "[None]" not in seen_prompt[0], str(seen_prompt))

# --------------------------------------------------------------- test 10
# Mixed mode: both regions in one call, Indian slots first. Precedence is
# no longer structural, so the badge must come from the citations used.
print("\n10. Mixed mode: 40 Indian + 60 international in the first call")
A.q("UPDATE app_config SET value='mixed' WHERE key='search.region_mode'")
A.q("UPDATE app_config SET value='40' WHERE key='search.mixed_indian_slots'")

mcalls: list[tuple[str, list]] = []


def _mcapture(model, system, msgs, pool, effort, max_uses):
    mcalls.append((system, list(pool)))
    return ("No answer here.", [], "stub-model", False)


A._grounded_answer = _mcapture
A._verdict = lambda q, a, c: {"answered": False, "grounded": True,
                              "provenance_ok": True, "ok": True}
A._openai_plain = lambda *a, **k: ""
mcalls.clear()
ask("mixed mode probe")

CAP = A.PROVIDERS[A.active_provider()].get("max_domains", 100)
first = mcalls[0][1]
check("first call splits 40 Indian / 60 international",
      len([d for d in first if d in live_in]) == 40
      and len([d for d in first if d in live_intl]) == 60,
      f"IN={len([d for d in first if d in live_in])} "
      f"INTL={len([d for d in first if d in live_intl])}")
check("first call is highest-priority Indian sources",
      first[0] == "icmr.gov.in", str(first[:3]))
check("no mixed batch exceeds the cap",
      all(len(p) <= CAP for _, p in mcalls),
      f"sizes={[len(p) for _, p in mcalls]}")
mseen = [d for _, p in mcalls for d in p]
check("every enabled domain reached exactly once",
      sorted(mseen) == sorted(live_in | live_intl),
      f"sent={len(mseen)} unique={len(set(mseen))} pool={len(live_in|live_intl)}")
check("mixed prompt tells the model both regions may appear",
      "may also include" in mcalls[0][0], mcalls[0][0][:200])

# the badge must follow the citations, not the pool
MIX = [{"cited_text": "ICMR says.", "url": "https://icmr.gov.in/a",
        "title": "ICMR", "domain": "icmr.gov.in"},
       {"cited_text": "KDIGO says.", "url": "https://kdigo.org/b",
        "title": "KDIGO", "domain": "kdigo.org"}]
A._grounded_answer = lambda *a, **k: ("A mixed answer.", [dict(c) for c in MIX],
                                      "stub-model", False)
A._verdict = lambda q, a, c: {"answered": True, "grounded": True,
                              "provenance_ok": True, "ok": True}
r10 = ask("mixed citation probe")
check("mixed citations → source_region MIXED",
      r10.get("source_region") == "MIXED", str(r10.get("source_region")))
check("each citation carries its own region",
      [c["region"] for c in r10["citations"]] == ["IN", "INTL"],
      str([(c["domain"], c.get("region")) for c in r10["citations"]]))

A._grounded_answer = lambda *a, **k: ("An Indian answer.", [dict(c) for c in CITE],
                                      "stub-model", False)
r10b = ask("mixed but indian-only citations probe")
check("Indian-only citations from a mixed pool → source_region IN",
      r10b.get("source_region") == "IN", str(r10b.get("source_region")))

# an unrecognised host must never be badged Indian
A._grounded_answer = lambda *a, **k: (
    "From somewhere else.",
    [{"cited_text": "x", "url": "https://unknown.example/a",
      "title": "?", "domain": "unknown.example"},
     {"cited_text": "y", "url": "https://other.example/b",
      "title": "?", "domain": "other.example"}], "stub-model", False)
r10c = ask("unknown host probe")
check("unknown host is not treated as Indian",
      r10c.get("source_region") != "IN", str(r10c.get("source_region")))

# www-prefixed and sub-hosts of an allowlisted domain resolve to its region
A._grounded_answer = lambda *a, **k: (
    "From WHO.",
    [{"cited_text": "x", "url": "https://www.who.int/a",
      "title": "WHO", "domain": "www.who.int"},
     {"cited_text": "y", "url": "https://apps.who.int/b",
      "title": "WHO", "domain": "apps.who.int"}], "stub-model", False)
r10d = ask("www-prefixed host probe")
check("www-prefixed and sub-hosts resolve to their region",
      r10d.get("source_region") == "INTL", str(r10d.get("source_region")))

A.q("UPDATE app_config SET value='indian_first' WHERE key='search.region_mode'")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All router tests passed.")
