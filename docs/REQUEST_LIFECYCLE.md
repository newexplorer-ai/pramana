# How Pramana answers one question

A trace of exactly what happens between a clinician pressing **Send** and an
answer appearing, as the system runs today. Line references point at
`server/app.py` unless noted.

> **Current config on production** (all admin-tunable in *Admin → Models & config*):
> provider `openai` · generation `gpt-5.2` · judge `gpt-5-mini` ·
> `search.region_mode = indian_first` · `search.mixed_indian_slots = 40` ·
> `retrieval.min_chunks = 1` · `websearch.max_uses = 3` ·
> allowlist 200 domains (100 Indian, 100 international) ·
> provider domain cap 100.
>
> These values change the routing but not the shape of the flow below.

---

## 0. The short version

```
Send
 └─ POST /api/ask  (auth + daily-cap check, then an SSE stream opens)
     ├─ classify: high-stakes? load allowlist, split IN/INTL, load history
     ├─ TIER 2  — search allowlisted sources, one call per batch:
     │     for each batch until one answers:
     │        generate-with-search  →  citations
     │        gate: enough citations?          (retrieval.min_chunks)
     │        judge: answered? grounded? provenance_ok?   (separate model call)
     │        pass → Tier 2 answer, stop
     │        fail → log the reason, try next batch
     ├─ TIER 3  — if no batch answered:
     │        high-stakes OR grounded-only mode → withhold (not_found)
     │        else → general-model answer, no citations (unverified)
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
(app.py:244) joins it to `allowed_users` on every request and rejects if the
row is missing or `enabled = 0` — so disabling a user in the admin panel kills
their live sessions immediately.

## 2. Gatekeeping (before any model call) — app.py:757

1. **Empty query** → `400`.
2. **Daily cap** (app.py:763): count this user's `query_logs` rows in the last
   day; at or above `cost.daily_user_cap` (40) → `429`.
   *Known bug: the window comparison is off — see [Known issues](#known-issues).*
3. **Conversation** (app.py:770): reuse the supplied `conversation_id` or mint
   a new UUID. First time seen, insert a `conversations` row whose title is the
   query's first 80 chars.

Then the SSE stream opens and everything below runs inside it.

## 3. Request setup — app.py:779

- `query_id` — a fresh UUID for this single turn.
- **High-stakes flag** (app.py:781): `HIGH_STAKES_RE.search(query)` — a regex
  matching `dose|dosing|dosage|mg/kg|interaction|contraindicat|overdose|titrat`.
  This one boolean decides later whether an ungrounded answer may ever be shown.
- **Allowlist load** (app.py:784): all `enabled=1` domains, ordered by
  `priority, rowid` (the curated editorial ranking), split into
  `by_region["IN"]` and `by_region["INTL"]`.
- **History** (app.py:802 / `_load_history`): the last `context.max_turns` (6)
  turns of this conversation, oldest-first, prepended to the new question so
  follow-ups have context.
- **`result` skeleton** is seeded with `sources_searched` (every domain that
  *could* be searched, `web:`-prefixed), `retrieved_at`, and empty
  `citations`/`followups`.

## 4. Tier 2 — grounded web search — app.py:821

Tier 2 is the product. It searches the allowlist and only serves an answer that
survives a citation gate **and** an independent judge.

### 4a. Building the search batches — app.py:826

A provider caps how many domains one search call may filter on (OpenAI: 100).
So the pool is split into **cap-sized batches**, tried in order, and the loop
stops at the first batch that produces a served answer. How the batches are
built depends on `search.region_mode`:

| mode | batch layout | when International is reached |
|---|---|---|
| `indian_first` *(current)* | Batch 1 = up to 100 Indian; then International | only if every Indian batch fails |
| `indian_only` | Indian batches only | never |
| `mixed` | Batch 1 = top 40 Indian + top 60 International; leftovers next | in the same first call |

Under the current `indian_first` mode, all 100 Indian domains fit one call, so
Batch 1 is purely Indian and International is a *separate later batch* reached
only if the Indian pass yields no served answer — this makes Indian precedence
**structural**: an Indian source, if one can answer, always answers first.

In `mixed` mode precedence instead stops being structural — an Indian answer is
no longer guaranteed just because Indian sources exist — so it is enforced by
the prompt's PROVENANCE rule (see 4c) and the answer's region is derived from
the citations actually used, not from which pool was searched.

### 4b. The per-batch loop — app.py:849

For each batch, until one answers:

1. **Emit stage** — `"Searching reliable Indian medical sources"`
   (or `international` / `Indian and international`). No vendor name, pool size,
   or batch number reaches the clinician.
2. **Generate with search** (`_grounded_answer`, app.py:722): one model call
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
4. **Retrieval gate** (app.py:883): fewer than `retrieval.min_chunks` (1)
   citations → discard, log `below_min_chunks`, emit
   *"Not enough supporting references found"*, try next batch. A lone source is
   not coverage.
5. **Tag citations by region** (app.py:894): each citation is tagged `IN`/`INTL`
   by its domain (suffix-matched, since providers return hosts like `www.who.int`
   for an allowlisted `who.int`; an unrecognised host is never treated as Indian).
   This happens **before** the judge, so the judge sees the region markers.

### 4c. The judge — app.py:896 / `_verdict`

A **separate `gpt-5-mini` model call** audits the draft against its own
citations and returns three booleans. (It is a separate call because Anthropic
rejects structured output combined with its Citations feature, so grounding is
judged after generation rather than during it.)

- **`answered`** — does the text actually answer, or is it a disguised refusal
  ("the sources don't cover this")? This is the guard against the original bug
  where a refusal was served behind a green *Grounded* badge.
- **`grounded`** — are the claims supported by the cited passages?
- **`provenance_ok`** — is any dosing / availability / NLEM / national-programme
  claim resting on an `[INTL]` source, or international guidance dressed up as
  Indian? Either makes it `false`.

Each citation is passed to the judge tagged `[IN]` / `[INTL]`. If the judge call
itself fails, `ok=false`.

**Any** of these failing (`not ok`, `not answered`, `not grounded`,
`not provenance_ok`) → the answer is thrown away, the reason is logged, and the
loop moves to the next batch. Only when all pass (app.py:910) is the Tier 2
answer committed: `tier=2`, `status=answered`, the segments, the citations, and
`source_region` = the single region if all citations agree, else `MIXED`.

## 5. Tier 3 — fallback or refusal — app.py:928

Reached only if **no** Tier 2 batch produced a served answer.

- **Withhold** (app.py:930): if the query is **high-stakes**, *or*
  `answers.allow_tier3` is off → no answer. `tier=null`, `status=not_found`.
  The clinician sees *"Dosing or interaction question — no answer without a
  reliable source"*. This is the deliberate safety stance: never give an
  ungrounded dosing/interaction answer.
- **General-model answer** (app.py:941): otherwise, one plain model call with
  `TIER3_SYSTEM` (which forbids inventing citations, forbids specific doses, and
  requires a hedged "Generally…" opener stating it may not match Indian
  guidance). Result: `tier=3`, `status=unverified`, **no citations**. The UI
  badges it *General model* with an explicit "not grounded, verify before use"
  warning.
- If Tier 3 errors or returns empty → `not_found`.

## 6. Invariant guard — app.py:991

A final safety net before anything is shown: if a response claims a tier but has
no answer text, or claims Tier 2 but carries no citations, it is forcibly
downgraded to `not_found`. This makes "a grounded badge with nothing real behind
it" structurally impossible, independent of anything the model or judge did.

## 7. Persist + respond — app.py:1002

- **`query_logs`** — one row: tier, status, high-stakes, latency, model used,
  `source_region`, and the full `fallthrough` JSON (every batch that failed and
  why). This is what drives the admin **gap log**.
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
| Withheld (high-stakes) | *Not found* | dosing/interaction questions need a reliable source |
| Not found (all failed) | *Not found* | the sources that were checked are listed |

---

## Cost of one question

- **Tier 2 served on the Indian batch:** 2 model calls — one
  generate-with-search, one judge. (~20–30 s wall clock; the search dominates.)
  This is the common case under `indian_first`.
- **Falls to International then serves:** add one more generate-with-search
  (+ its judge call) — the Indian batch ran, failed, and the International batch
  ran next.
- **Each failed batch adds** one generate-with-search (+ a judge call if it got
  as far as the judge).
- **Tier 3 answer:** the Tier 2 attempts **plus** one more general-model call.
- **Withheld / not found:** the Tier 2 attempts only — no generation beyond them.

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
   ("what patient X should do") when the question invites one. The judge does
   not test for this.
2. **High-stakes detection is a 5-keyword regex.** It misses paraphrases
   ("how much for a 3-year-old", "is this safe in pregnancy", "can I combine
   X and Y"), which then reach an ungrounded Tier 3 answer instead of being
   withheld.
3. **Daily-cap window is wrong.** `created_at > datetime('now','-1 day')`
   compares an ISO-8601 timestamp (with a `T`) against a space-separated
   SQLite datetime; on the boundary date the comparison mis-sorts and counts
   some queries older than 24 h, capping heavy users a few hours early.
4. **Sessions never expire.** `auth_sessions.created_at` is recorded but never
   read; a token is valid until the user is disabled.
5. **PHI is accepted and stored in clear text.** A query naming a patient is
   written verbatim to `query_logs`, `turns`, and the `conversations` title,
   and sent to the model provider. No detection, redaction, or retention limit.
6. **The Tier 2 badge is static.** It says "Indian and international sources"
   even when every citation is international; the per-source rail tags carry the
   truth, the badge does not.

---

*Generated from `server/app.py` as deployed. If the routing behaves unexpectedly,
the `fallthrough` column in `query_logs` (admin gap log) records the exact reason
each batch was rejected.*
