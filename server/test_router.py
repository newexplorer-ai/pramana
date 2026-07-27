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
_REAL_TRIAGE = A._triage           # kept before the stubs replace it


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


SENTINEL = "NO_SUBSTANTIVE_ANSWER"


def stub(*, text: str, citations: list[dict], answered: bool = True,
         grounded: bool = True, verdict_ok: bool = True,
         t3_text: str = "Generally, this is a fallback answer."):
    """Deterministic provider fakes. The groundedness judge is gone, so a
    grounded answer is served whenever it has >= min_chunks citations and is
    not the NO_SUBSTANTIVE_ANSWER sentinel. `answered=False` now emits that
    sentinel (the only refusal signal left); grounded/verdict_ok are accepted
    for legacy call sites but no longer gate anything."""
    grounded_text = text if answered else SENTINEL
    A._grounded_answer = lambda *a, **k: (grounded_text, citations, "stub-model", False)
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
# The model emits the NO_SUBSTANTIVE_ANSWER sentinel: with the judge gone,
# this sentinel is the only refusal signal, and it must fall through — no
# Tier 2 emitted, sentinel text never shown.
print("\n1. Sentinel refusal → falls through, no Tier 2, sentinel never shown")
stub(text="", citations=CITE, answered=False)   # answered=False emits the sentinel
r1 = ask("Current ICMR advisory on dengue fluid management?")
check("tier is not 2", r1["tier"] != 2, f"tier={r1['tier']}")
check("no grounded status", r1["status"] != "answered", f"status={r1['status']}")
check("sentinel never served as the answer",
      SENTINEL not in (r1.get("answer_text") or ""))
check("fall-through logged with tier+reason",
      any(f["tier"] == 2 and f["reason"].startswith("no_substantive_answer")
          for f in (r1.get("fallthrough") or [])),
      str(r1.get("fallthrough")))
reasons1 = {f["reason"] for f in (r1.get("fallthrough") or [])}
check("both regions attempted before falling through",
      any(r.startswith("no_substantive_answer:IN") for r in reasons1)
      and any(r.startswith("no_substantive_answer:INTL") for r in reasons1),
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
# Guard: a sentinel/empty answer must never serialize with a tier.
print("\n4. Sentinel or empty answer never serialized with a tier")
cases = [
    ("sentinel + citations", SENTINEL, CITE),
    ("sentinel + single citation", SENTINEL, CITE[:1]),
]
for label, text, cites in cases:
    stub(text=text, citations=cites, t3_text="")   # answered defaults True; text IS sentinel
    rr = ask(f"probe: {label}")
    ok = rr["tier"] is None and rr["status"] == "not_found"
    check(f"{label} → tier null / not_found", ok,
          f"tier={rr['tier']} status={rr['status']}")

# DOCUMENTED CONSEQUENCE of removing the judge: a plausible-looking but
# ungrounded answer WITH enough citations is now SERVED as Tier 2. Previously
# the groundedness judge would have caught this. This test pins the new,
# weaker behaviour so a future change to it is deliberate, not accidental.
stub(text="Claims that the citations do not actually support.", citations=CITE)
r4b = ask("ungrounded-but-cited probe")
check("no judge: a cited answer is served even if ungrounded",
      r4b["tier"] == 2 and r4b["status"] == "answered",
      f"tier={r4b['tier']} status={r4b['status']}")

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
            # A non-answer is now the sentinel, not prose — there is no judge.
            return (("An Indian-grounded answer." if indian_answers else SENTINEL),
                    CITE, "stub-model", False)
        return ("An international-grounded answer.", INTL_CITE, "stub-model", False)

    A._grounded_answer = _ga
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
# DOCUMENTED CONSEQUENCE: provenance enforcement was the judge's job, so it is
# gone too. A dosing answer resting on an international source is now served.
# The generation prompt still ASKS the model not to do this, but nothing
# enforces it. This test pins the new behaviour.
print("\n8. No judge: a dosing answer on international sources is now served")
A._grounded_answer = lambda *a, **k: (
    "Generally the dose is 5 mg/kg daily.",
    [{"cited_text": "dose info", "url": "https://kdigo.org/d",
      "title": "KDIGO", "domain": "kdigo.org"},
     {"cited_text": "more", "url": "https://nice.org.uk/d",
      "title": "NICE", "domain": "nice.org.uk"}], "stub-model", False)
A._openai_plain = lambda *a, **k: ""
r8 = ask("What is the dose in renal impairment?")
check("dosing-on-international answer is now served (no provenance gate)",
      r8["tier"] == 2, f"tier={r8['tier']}")

# ---------------------------------------------------------------- test 9
# Snapshot: the pool sent and the prompt describing it must agree. This is
# the class of test that would have caught the Indian-prompt-with-
# international-pool defect.
print("\n9. Snapshot: assembled prompt matches the pool actually sent")
INTL_SET = {d["domain"] for d in INTL_CITE} | {"who.int", "nice.org.uk"}
calls: list[tuple[str, list]] = []


def _capture(model, system, msgs, pool, effort, max_uses):
    calls.append((system, list(pool)))
    return (SENTINEL, CITE, "stub-model", False)   # sentinel → exhaust both passes


A._grounded_answer = _capture
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

# --------------------------------------------------------------- test 11
# Dual mode: two dedicated searches, each confined to its own pool, then a
# compose call merges them. The starvation failure is impossible because the
# Indian call's allowlist is Indian-only.
print("\n11. Dual mode: parallel per-pool search + compose")
A.q("UPDATE app_config SET value='dual' WHERE key='search.region_mode'")

live_intl = {r["domain"] for r in A.q(
    "SELECT domain FROM allowlist_domains WHERE enabled=1 AND region='INTL'")}
live_in = {r["domain"] for r in A.q(
    "SELECT domain FROM allowlist_domains WHERE enabled=1 AND region='IN'")}

A._triage = lambda q: {"in_scope": True, "plan": "both"}
compose_seen = {}


def _dual_search_factory(indian_cites, intl_cites, in_text="Indian draft.",
                         intl_text="International draft."):
    """Region-aware stub: returns different drafts per pool, and records that
    each call's pool was confined to that region."""
    def _ga(model, system, msgs, pool, effort, max_uses):
        pool_is_intl = bool(set(pool) & live_intl)
        pool_is_in = bool(set(pool) & live_in)
        # the crux: each call sees exactly one pool
        assert not (pool_is_intl and pool_is_in), "dual call mixed the pools!"
        if pool_is_in:
            return (in_text, [dict(c) for c in indian_cites], "stub-in", False)
        return (intl_text, [dict(c) for c in intl_cites], "stub-intl", False)
    return _ga


def _spy_compose(query, indian, intl):
    compose_seen["indian_text"] = indian[0]
    compose_seen["intl_text"] = intl[0]
    merged = list(indian[1]) + list(intl[1])
    return ("Composed Indian-anchored answer.", merged, ["f1", "f2"], "stub-compose")


A._compose = _spy_compose

# 11a — both pools answer → compose runs, badge MIXED, counts recorded
A._grounded_answer = _dual_search_factory(list(CITE), list(INTL_CITE))
compose_seen.clear()
r11 = ask("dual both-answered probe")
check("both pools answered → Tier 2", r11["tier"] == 2, f"tier={r11['tier']}")
check("pool_outcome is both_answered",
      r11.get("pool_outcome") == "both_answered", str(r11.get("pool_outcome")))
check("compose received both drafts",
      compose_seen.get("indian_text") == "Indian draft."
      and compose_seen.get("intl_text") == "International draft.", str(compose_seen))
check("composed citations are the union, region-tagged",
      {c["region"] for c in r11["citations"]} == {"IN", "INTL"},
      str([(c["domain"], c.get("region")) for c in r11["citations"]]))
check("source_region MIXED for a merged answer",
      r11.get("source_region") == "MIXED", str(r11.get("source_region")))
check("per-pool citation counts recorded",
      r11.get("indian_citations") == len(CITE)
      and r11.get("intl_citations") == len(INTL_CITE),
      f"in={r11.get('indian_citations')} intl={r11.get('intl_citations')}")

# 11b — Indian empty → international-only answer, no compose, honest outcome
A._grounded_answer = _dual_search_factory([], list(INTL_CITE))
compose_seen.clear()
r11b = ask("dual indian-empty probe")
check("Indian empty → still answered from international",
      r11b["tier"] == 2 and r11b.get("source_region") == "INTL",
      f"tier={r11b['tier']} region={r11b.get('source_region')}")
check("Indian-empty outcome is intl_only_answered",
      r11b.get("pool_outcome") == "intl_only_answered", str(r11b.get("pool_outcome")))
check("compose skipped when only one pool answered",
      compose_seen == {}, str(compose_seen))
check("indian_citations is 0 when Indian pool was empty",
      r11b.get("indian_citations") == 0, str(r11b.get("indian_citations")))

# 11c — both empty → falls through, no Tier 2
A._grounded_answer = _dual_search_factory([], [])
A._openai_plain = lambda *a, **k: ""
r11c = ask("dual both-empty probe")
check("both pools empty → not Tier 2", r11c["tier"] != 2, f"tier={r11c['tier']}")
check("both-empty outcome recorded",
      r11c.get("pool_outcome") == "both_empty", str(r11c.get("pool_outcome")))

# 11d — classifier plan is honoured: international_only skips the Indian call
searched_pools: list[str] = []


def _plan_spy_search(model, system, msgs, pool, effort, max_uses):
    searched_pools.append("IN" if set(pool) & live_in else "INTL")
    return ("International draft.", list(INTL_CITE), "stub", False)


A._triage = lambda q: {"in_scope": True, "plan": "international_only"}
A._grounded_answer = _plan_spy_search
searched_pools.clear()
r11d = ask("dual international_only plan probe")
check("international_only plan searches only the international pool",
      searched_pools == ["INTL"], str(searched_pools))

# 11e — a composed answer that is the sentinel/empty falls through (the only
# refusal guard left in the dual path)
A._triage = lambda q: {"in_scope": True, "plan": "both"}
A._grounded_answer = _dual_search_factory(list(CITE), list(INTL_CITE))
A._compose = lambda q, i, n: (SENTINEL, list(i[1]) + list(n[1]), [], "stub-compose")
r11e = ask("dual sentinel-compose probe")
check("composed sentinel answer → never Tier 2",
      r11e["tier"] != 2, f"tier={r11e['tier']}")
check("no_substantive_answer logged for dual",
      any("no_substantive_answer:dual" in f["reason"]
          for f in (r11e.get("fallthrough") or [])),
      str(r11e.get("fallthrough")))
A._compose = _spy_compose

A.q("UPDATE app_config SET value='indian_first' WHERE key='search.region_mode'")

# --------------------------------------------------------------- test 12
# Transient provider errors are retried, and a not-found caused by provider
# errors is reported as a service error, not "no source covers this".
print("\n12. Retry on transient errors + service-error vs not-found")
A.time.sleep = lambda *a, **k: None          # no backoff delay in tests


class _Transient(Exception):
    status_code = 500


calls_n = [0]
def _flaky():
    calls_n[0] += 1
    if calls_n[0] < 3:
        raise _Transient("500")
    return "ok"
check("_retry succeeds after transient failures", A._retry(_flaky) == "ok")
check("_is_transient: 500 is retryable", A._is_transient(_Transient()))
check("_is_transient: a plain ValueError is not",
      not A._is_transient(ValueError("bad input")))

n2 = [0]
def _always_fail():
    n2[0] += 1
    raise _Transient("500")
try:
    A._retry(_always_fail); raised = False
except Exception:
    raised = True
check("_retry gives up after tries and re-raises", raised)
check("_retry attempted exactly 3 times", n2[0] == 3, f"n={n2[0]}")

# Router: every tier failing with a provider error → service_error, not not_found
def _boom(*a, **k):
    raise _Transient("500")
A._grounded_answer = _boom
A._openai_plain = _boom
A._triage = lambda q: {"in_scope": True, "plan": "both"}
r12 = ask("provider outage probe")
check("provider outage → status not_found", r12["status"] == "not_found",
      f"status={r12['status']}")
check("provider outage → withheld_reason service_error",
      r12.get("withheld_reason") == "service_error", str(r12.get("withheld_reason")))

# --------------------------------------------------------------- test 13
# Auth + cap correctness. Both compare ISO-8601 timestamps against SQLite
# time strings, which mis-sorted before ('T' > ' ') — pin the fixed behaviour.
print("\n13. Daily-cap window and session expiry")
import datetime as _dt
_now = _dt.datetime.now(_dt.timezone.utc)
_email = "k.prasad.iitr@gmail.com"
for _h in (2, 25, 40):
    A.q("""INSERT INTO query_logs(query_id,user_email,query_text,tier,status,
           high_stakes,latency_ms,created_at) VALUES(?,?,?,?,?,?,?,?)""",
        (f"capprobe{_h}", _email, "x", 2, "answered", 0, 100,
         (_now - _dt.timedelta(hours=_h)).isoformat()))
_counted = A.q("""SELECT COUNT(*) n FROM query_logs WHERE user_email=?
                  AND query_id LIKE 'capprobe%'
                  AND created_at > strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')""",
               (_email,))[0]["n"]
check("daily cap counts only the last 24h", _counted == 1, f"counted={_counted}")

_tok = client.post("/api/auth/demo", json={"email": _email}).json()["token"]
_H = {"Authorization": f"Bearer {_tok}"}
check("fresh session is valid", client.get("/api/me", headers=_H).status_code == 200)
A.q("UPDATE auth_sessions SET created_at=? WHERE token=?",
    ((_now - _dt.timedelta(days=31)).isoformat(), _tok))
check("session past auth.session_days is rejected",
      client.get("/api/me", headers=_H).status_code == 401)
A.q("UPDATE auth_sessions SET created_at=? WHERE token=?",
    ((_now - _dt.timedelta(days=29)).isoformat(), _tok))
check("session inside auth.session_days still valid",
      client.get("/api/me", headers=_H).status_code == 200)
check("removed library endpoints are gone",
      client.get("/api/library", headers=_H).status_code == 404)

# --------------------------------------------------------------- test 14
# Conversation history is per-user, and delete is owner-scoped. History can
# carry clinical questions, so a cross-user read or delete is a real leak.
print("\n14. History isolation and owner-scoped delete")
A._grounded_answer = lambda *a, **k: ("An answer.", [dict(c) for c in CITE],
                                      "stub-model", False)
A._triage = lambda q: {"in_scope": True, "plan": "both"}
_r = ask("history isolation probe")
_cid = _r["conversation_id"]
_other = client.post("/api/auth/demo", json={"email": "r.iyer@aiims.edu"}).json()["token"]
_OH = {"Authorization": f"Bearer {_other}"}

check("owner sees their own conversation",
      any(c["id"] == _cid for c in client.get("/api/conversations", headers=AUTH).json()))
check("another user's list excludes it",
      not any(c["id"] == _cid for c in client.get("/api/conversations", headers=_OH).json()))
check("another user cannot read the thread",
      client.get(f"/api/conversations/{_cid}", headers=_OH).status_code == 404)
check("another user cannot delete it",
      client.delete(f"/api/conversations/{_cid}", headers=_OH).status_code == 404)
check("it survives the failed delete",
      client.get(f"/api/conversations/{_cid}", headers=AUTH).status_code == 200)
check("owner can delete it",
      client.delete(f"/api/conversations/{_cid}", headers=AUTH).status_code == 200)
check("deleted thread is gone",
      client.get(f"/api/conversations/{_cid}", headers=AUTH).status_code == 404)
check("its turns are removed too",
      not A.q("SELECT 1 FROM turns WHERE conversation_id=?", (_cid,)))

# --------------------------------------------------------------- test 15
# Scope gate: a non-medical question is declined before any search, and no
# general-model answer is served in its place.
print("\n15. Scope gate: non-medical questions are declined, not answered")
_searched = []
def _spy_search(model, system, msgs, pool, effort, max_uses):
    _searched.append(len(pool))
    return ("Should never run.", [dict(c) for c in CITE], "stub", False)
A._grounded_answer = _spy_search
A._openai_plain = lambda *a, **k: "A general-knowledge answer."
A._triage = lambda q: {"in_scope": False, "plan": "both"}
_searched.clear()
r15 = ask("who won the 2024 cricket world cup?")
check("out_of_scope status", r15["status"] == "out_of_scope", str(r15["status"]))
check("no tier assigned", r15["tier"] is None, f"tier={r15['tier']}")
check("no answer text served", not (r15.get("answer_text") or "").strip())
check("no Tier 3 general-model fallback", "general-knowledge" not in (r15.get("answer_text") or ""))
check("nothing was searched", _searched == [], str(_searched))
check("out_of_scope logged", any(f["reason"] == "out_of_scope"
                                 for f in (r15.get("fallthrough") or [])),
      str(r15.get("fallthrough")))

# In-scope questions are unaffected
A._triage = lambda q: {"in_scope": True, "plan": "both"}
r15b = ask("first-line management of type 2 diabetes")
check("in-scope question still answered", r15b["tier"] == 2, f"tier={r15b['tier']}")

# Fails open: if the triage call itself errors, a real clinical question must
# still be answered rather than refused as "not medical".
_saved_client = A._client
A._client = lambda model: (_ for _ in ()).throw(RuntimeError("triage down"))
_t = _REAL_TRIAGE("first-line management of type 2 diabetes")
A._client = _saved_client
check("triage failure fails open to in_scope", _t["in_scope"] is True, str(_t))
check("triage failure defaults plan to both", _t["plan"] == "both", str(_t))

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All router tests passed.")
