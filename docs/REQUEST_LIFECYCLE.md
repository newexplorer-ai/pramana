# How Pramana answers one question

A trace of exactly what happens between a clinician pressing **Send** and an
answer appearing, as the system runs today. References name functions in
`server/app.py` (stable across edits) rather than line numbers.

> **Current config on production** (all admin-tunable in *Admin → Models & config*):
> provider `openai` · generation `gpt-5.2` · classifier `gpt-5-mini` ·
> `search.region_mode = indian_first` · `search.mixed_indian_slots = 40` ·
> `retrieval.min_chunks = 1` · `websearch.max_uses = 3` ·
> allowlist 200 domains (100 Indian, 100 international) ·
> provider domain cap 100.
>
> A fourth mode, **`dual`**, is built and deployed but **dormant** — production
> runs `indian_first`. It replaces the batch loop with two parallel searches
> and a compose step; see [§4d](#4d-dual-mode). The rest of this trace describes
> the current `indian_first` path.
>
> These values change the routing but not the shape of the flow below.

---

## 0. The short version

```
Send
 └─ POST /api/ask  (auth + daily-cap check, then an SSE stream opens)
     ├─ load allowlist, split IN/INTL, load history
     ├─ TIER 2  — search allowlisted sources, one call per batch:
     │     for each batch until one answers:
     │        generate-with-search  →  citations
     │        gate: enough citations? (retrieval.min_chunks)
     │        refusal check: is it the NO_SUBSTANTIVE_ANSWER sentinel?
     │        pass both → Tier 2 answer, stop
     │        fail → log the reason, try next batch
     ├─ TIER 3  — if no batch answered:
     │        general-model answer, no citations (unverified)
     │        (only not_found if Tier 3 itself returns nothing)
     ├─ invariant guard  (never show an empty/uncited answer behind a badge)
     ├─ persist: query_logs + turns
     └─ emit one `result` event
```

Every `stage` event above streams to the browser live; the single `result`
event at the end carries the answer. There is **no Tier 1** — the curated
corpus was cut from scope, so the sequence starts at Tier 2.

---

## 1. Browser → server

**Frontend** (`js/desktop.js` → `askLive()` → `js/api.js` → `ask()`):

- `POST /api/ask` with `{ query, conversation_id? }` and a `Bearer` token.
- The response is **not** JSON — it is an SSE stream (`text/event-stream`).
  The client reads it with a `ReadableStream` reader, splitting on `\n\n`, and
  dispatches three event types: `stage`, `error`, `result`.
- A `401` anywhere clears the token and bounces to the login page.

The token is a random 32-byte string minted at login (`issue_token`,
`secrets.token_urlsafe(32)`), stored in `auth_sessions`. `current_user`
joins it to `allowed_users` on every request and rejects if the
row is missing or `enabled = 0` — so disabling a user in the admin panel kills
their live sessions immediately.

## 2. Gatekeeping (before any model call) — the `ask()` handler

1. **Empty query** → `400`.
2. **Daily cap** (in `ask()`): count this user's `query_logs` rows in the last
   day; at or above `cost.daily_user_cap` (40) → `429`.
   *Known bug: the window comparison is off — see [Known issues](#known-issues).*
3. **Conversation** (in `ask()`): reuse the supplied `conversation_id` or mint
   a new UUID. First time seen, insert a `conversations` row whose title is the
   query's first 80 chars.

Then the SSE stream opens and everything below runs inside it.

## 3. Request setup (inside `stream()`)

- `query_id` — a fresh UUID for this single turn.
- **Allowlist load:** all `enabled=1` domains, ordered by
  `priority, rowid` (the curated editorial ranking), split into
  `by_region["IN"]` and `by_region["INTL"]`.
- **History** (`_load_history`): the last `context.max_turns` (6)
  turns of this conversation, oldest-first, prepended to the new question so
  follow-ups have context.
- **`result` skeleton** is seeded with `sources_searched` (every domain that
  *could* be searched, `web:`-prefixed), `retrieved_at`, and empty
  `citations`/`followups`.

## 4. Tier 2 — grounded web search

Tier 2 is the product. It searches the allowlist and only serves an answer that
survives a citation gate **and** is not a refusal sentinel.

### 4a. Building the search batches

A provider caps how many domains one search call may filter on (OpenAI: 100).
So the pool is split into **cap-sized batches**, tried in order, and the loop
stops at the first batch that produces a served answer. How the batches are
built depends on `search.region_mode`:

| mode | batch layout | when International is reached |
|---|---|---|
| `indian_first` *(current)* | Batch 1 = up to 100 Indian; then International | only if every Indian batch fails |
| `indian_only` | Indian batches only | never |
| `mixed` | Batch 1 = top 40 Indian + top 60 International; leftovers next | in the same first call |
| `dual` *(built, dormant)* | not a batch loop — two parallel searches + compose ([§4d](#4d-dual-mode)) | always, in parallel with Indian |

Under the current `indian_first` mode, all 100 Indian domains fit one call, so
Batch 1 is purely Indian and International is a *separate later batch* reached
only if the Indian pass yields no served answer — this makes Indian precedence
**structural**: an Indian source, if one can answer, always answers first.

In `mixed` mode precedence instead stops being structural — an Indian answer is
no longer guaranteed just because Indian sources exist — so it is enforced by
the prompt's PROVENANCE rule (see 4c) and the answer's region is derived from
the citations actually used, not from which pool was searched.

### 4b. The per-batch loop

For each batch, until one answers:

1. **Emit stage** — `"Searching reliable Indian medical sources"`
   (or `international` / `Indian and international`). No vendor name, pool size,
   or batch number reaches the clinician.
2. **Generate with search** (`_grounded_answer`): one model call
   with a web-search tool attached and `allowed_domains` set to this batch. The
   **search happens server-side inside that one call** — the model searches,
   reads, and writes the answer with citations attached, in a single round trip.
   - *OpenAI path* (`_openai_grounded`): Responses API + `web_search` tool with
     `filters.allowed_domains`; citations come from `url_citation` annotations;
     inline markdown links are stripped (the UI renders them as pills instead).
   - *Anthropic path*: Messages API + `web_search_20260209` server tool;
     citations are API-enforced; `pause_turn` is resumed up to 3× for long
     searches.
3. **Parse follow-ups** (`_parse_followups`): split the trailing
   `[[FOLLOWUPS]] a | b` marker off the answer text.
4. **Retrieval gate:** fewer than `retrieval.min_chunks` (1)
   citations → discard, log `below_min_chunks`, emit
   *"Not enough supporting references found"*, try next batch. A lone source is
   not coverage.
5. **Tag citations by region:** each citation is tagged `IN`/`INTL`
   by its domain (suffix-matched, since providers return hosts like `www.who.int`
   for an allowlisted `who.int`; an unrecognised host is never treated as Indian).
   The region drives the answer's badge (`source_region`).

### 4c. The refusal check — `_is_non_answer`

There is **no groundedness judge** (removed — see [Removed](#removed)). The only
check between a generated draft and it being served is a **string test**, not a
model call: the generation prompt instructs the model to reply exactly
`NO_SUBSTANTIVE_ANSWER` when the sources don't answer, and `_is_non_answer`
catches that sentinel (or an empty answer) and falls through to the next batch.

That is the *entire* remaining guard. An answer that has ≥ `min_chunks`
citations and is not the sentinel is served as `tier=2, status=answered` —
whether or not its claims are actually supported by those citations, and
regardless of whether a dosing claim rests on an international source. Both of
those were the judge's job. `source_region` is the single region if all
citations agree, else `MIXED`.

### 4d. Dual mode — parallel search + compose (built, dormant) {#4d-dual-mode}

When `search.region_mode = dual`, §4a–4b are replaced by a different shape. It
exists because the batch modes treat the two pools as *fallbacks for each
other*: `mixed` puts both in one call, but `allowed_domains` is a **permission
filter, not a quota** — the denser international pool consumes the single search
budget and the Indian domains are never meaningfully queried. Dual fixes that by
giving each pool **its own call with its own budget the other cannot consume.**

1. **Retrieval-plan classifier** (`_retrieval_plan`): one small-model call
   returns `both` / `international_only` / `indian_only`, biased to `both`,
   failing open to `both` on any error. It exists so a pure-science question can
   skip the Indian call and stay at single-pool cost. Disableable via
   `search.dual_classifier` (off ⇒ always `both`).
2. **Two dedicated searches, in parallel** (`ThreadPoolExecutor`, max 2 workers):
   the Indian call gets `allowed_domains` = Indian pool only, the international
   call gets the international pool only. The blocking SDK calls release the GIL
   on network I/O, so **wall-clock is one search, not two** (measured: 1.0 s for
   two 1 s searches). Because each call's allowlist is one pool, the Indian
   search is *structurally incapable* of returning international results — the
   starvation failure is impossible, not merely discouraged.
3. **Gate + region-tag each draft** exactly as §4b does (citation count +
   sentinel check), independently.
4. **Compose** (`_compose`, `both_answered` case only): one call with **no
   search tool**, on the generation model. Its prompt anchors on the Indian
   position where one exists, always shows that international evidence exists,
   surfaces conflicts with attribution rather than averaging, and states plainly
   where Indian sources are silent. Output = one Indian-anchored answer; its
   citations are the **union** of both drafts, still region-tagged.
5. **Refusal check** the composed answer (or the single-pool draft) with
   `_is_non_answer` — a sentinel/empty composed answer falls through. There is
   no groundedness or provenance check on the merged answer; it is served as-is.

**Asymmetric outcomes are first-class**, recorded in `pool_outcome`:

| Indian call | Intl call | `pool_outcome` | result |
|---|---|---|---|
| passes | passes | `both_answered` | compose merges both |
| passes | empty/fails | `indian_only_answered` | Indian draft served directly (no compose) |
| empty/fails | passes | `intl_only_answered` | international draft served, honestly labelled |
| empty/fails | empty/fails | `both_empty` | fall through to Tier 3 / not-found |

The per-pool citation counts (`indian_citations`, `intl_citations`) are logged
alongside, which is what turns a thin-Indian-coverage question into a visible,
queryable signal instead of a silent international-only answer.

## 5. Tier 3 — general-model fallback

Reached whenever **no** Tier 2 batch produced a served answer. There is no
upfront withhold: the general model is *always* the fallback (see
[Removed](#removed)).

- **General-model answer:** one plain model call with `TIER3_SYSTEM` (which
  forbids inventing citations, forbids specific doses, and requires a hedged
  "Generally…" opener stating it may not match Indian guidance). Result:
  `tier=3`, `status=unverified`, **no citations**. The UI badges it *General
  model* with an explicit "not grounded, verify before use" warning.
- **`not_found`** is reached only when Tier 3 *itself* produces nothing — the
  provider refuses, errors, or returns empty. It is no longer a chosen policy;
  it is only a genuine failure to answer.

## 6. Invariant guard

A final safety net before anything is shown: if a response claims a tier but has
no answer text, or claims Tier 2 but carries no citations, it is forcibly
downgraded to `not_found`. This makes "a grounded badge with nothing real behind
it" structurally impossible, independent of anything the model did.

## 7. Persist + respond

- **`query_logs`** — one row: tier, status, latency, model used,
  `source_region`, and the full `fallthrough` JSON (every batch that failed and
  why). In dual mode it also carries `pool_outcome` and the per-pool
  `indian_citations` / `intl_citations` counts. This is what drives the admin
  **gap log**.
- **`turns`** — the user question always; the assistant answer only if one was
  produced. These become the conversation history for the next follow-up.
- **Emit `result`** — the one SSE event carrying the answer object the frontend
  renders.

`latency_ms` is measured across the whole stream; the browser shows it as
seconds.

---

## What the clinician sees

| outcome | badge | note shown |
|---|---|---|
| Tier 2 served | *Referenced from reliable Indian and international sources* | citations as pills + a sources rail with per-source `IN`/`INTL` tags |
| Tier 3 served | *General model* | "not grounded in medical literature… verify before clinical use" |
| Not found (all failed) | *Not found* | the sources that were checked are listed |

---

## Cost of one question

- **Tier 2 served on the Indian batch:** 1 model call — the
  generate-with-search. (~20–30 s wall clock; the search dominates.)
  This is the common case under `indian_first`.
- **Falls to International then serves:** add one more generate-with-search —
  the Indian batch ran, fell through, and the International batch ran next.
- **Each failed batch adds** one generate-with-search.
- **Tier 3 answer:** the Tier 2 attempts **plus** one more general-model call.
- **Not found:** the Tier 2 attempts plus the Tier 3 call that came back empty.

**In `dual` mode**, a `both`-plan question costs a classifier call + two
searches (parallel, so ~one search of *latency* but ~2× search *spend*) +
compose — 4 model calls, ~one search of wall-clock. A single-pool plan
(`international_only` / `indian_only`) skips compose and stays at classifier +
1 search. The design accepts the extra spend to get Indian/international
parity right, and logs `pool_outcome` so the cost trade can later be tuned from
real numbers.

A non-medical question ("plan a trip to Italy") currently runs the **entire**
Tier 2 loop, finds nothing, and produces a Tier 3 answer — 3 model calls for a
question the tool should decline up front. A scope gate to short-circuit this is
designed but not yet built.

---

## Known issues affecting this path {#known-issues}

These are live as of this writing and documented here so the trace is honest:

1. **No "reference tool, not clinician" enforcement.** The Tier 2 prompt asks
   the model to report what the literature says, not to advise — but nothing
   checks it, and the model will still produce a personalised care plan
   ("what patient X should do") when the question invites one. Nothing checks
   for this.
2. **Daily-cap window is wrong.** `created_at > datetime('now','-1 day')`
   compares an ISO-8601 timestamp (with a `T`) against a space-separated
   SQLite datetime; on the boundary date the comparison mis-sorts and counts
   some queries older than 24 h, capping heavy users a few hours early.
3. **Sessions never expire.** `auth_sessions.created_at` is recorded but never
   read; a token is valid until the user is disabled.
4. **PHI is accepted and stored in clear text.** A query naming a patient is
   written verbatim to `query_logs`, `turns`, and the `conversations` title,
   and sent to the model provider. No detection, redaction, or retention limit.
5. **The Tier 2 badge is static.** It says "Indian and international sources"
   even when every citation is international; the per-source rail tags carry the
   truth, the badge does not.

---

## Removed {#removed}

**Per-question high-stakes withhold** (formerly a `HIGH_STAKES_RE` keyword
regex). It flagged dosing/interaction questions and withheld the Tier 3
fallback for them. Removed deliberately: the regex only matched literal words
(`dose`, `mg/kg`, `titrate`…) and silently missed every paraphrase — "how is
this treated", "how much for a child", "is it safe in pregnancy" — so it gave
the *appearance* of a safety gate while catching only a fraction of what it
named. A dosing question now gets the same Tier 3 general-model answer as any
other ungrounded question, carrying the "not grounded — verify before clinical
use" warning.

**Grounded-only mode** (`answers.allow_tier3`), the admin switch that withheld
*every* ungrounded answer. Removed too: the product now always attempts an
answer — grounded when it can, general-model-with-warning otherwise — and only
returns `not_found` when even the general model comes back empty. There is no
remaining way to make the product refuse a question upfront; the config key is
deleted on boot and the admin switch is gone.

**The groundedness judge** (`_verdict`, `VERDICT_SYSTEM`, `groundedness.judge`),
a separate `gpt-5-mini` call that audited every Tier 2 draft on three booleans —
`answered` (is it a disguised refusal?), `grounded` (do the citations support the
claims?), `provenance_ok` (does a dosing/NLEM claim rest on a foreign source?).
Removed at the operator's direction after it repeatedly failed *composed* dual
answers as `not_grounded` and dropped good questions to Tier 3.

This is the most consequential removal. The `answered` guard was the guard
against **the founding bug of this codebase** — a refusal served behind a green
*Grounded* badge. In its place is only `_is_non_answer`, a string check for the
`NO_SUBSTANTIVE_ANSWER` sentinel the generation prompt asks the model to emit.
So: a model that emits the sentinel is caught; a model that writes a *prose*
refusal, or a confidently wrong answer, or a dosing figure from an international
source, is **now served as grounded**. The generation prompt still asks the
model not to do these things (rules 2–5, 9), but nothing enforces it. The only
structural guarantees left are the citation-count gate and the invariant guard
(no empty/uncited answer behind a badge).

---

*Describes `server/app.py` as deployed. If the routing behaves unexpectedly,
the `fallthrough` column in `query_logs` (admin gap log) records the exact reason
each batch was rejected.*
