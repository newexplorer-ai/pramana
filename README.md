# Pramana — interactive prototype (all surfaces)

Implements the combined MVP PRD v1.0: marketing site (`index.html`, prod landing), doctor
app (`app.html`), admin portal (`admin.html`), plus the original mobile-frame
flow (`mobile.html`). PRD open decisions applied in the prototype:
**D1 → (c)** high-stakes dosing/interaction queries are withheld from Tier 3
(`isHighStakes` in `js/data.js`); **D2** Library = saved conversations
(localStorage); **D3/D4** single model chip reflecting `model.generation`;
**D5** follow-ups on Tier 1 only.


Cited medical Q&A grounded in Indian medical literature. This is a front-end
implementation of the **Pramana User Flow** design canvas: the core answer
journey from first-run consent through the three response tiers, with a
source-grouped, inline-cited answer surface.

It is a **self-contained, dependency-free web prototype** (no build step) that
wires the 7 static design frames into one navigable app. Response content is
mocked client-side; in production it comes from the FastAPI orchestrator +
Anthropic Messages API described in the PRD (§7).

## Run

```bash
python3 -m http.server 4173
# open http://localhost:4173
```

(or use the Claude Code launch config named `pramana`.)

## The flow

`consent → home → staged retrieval → tiered answer → citation card`

Try these to see each tier (routing lives in `js/data.js → routeQuery`):

| Ask | Routes to |
|---|---|
| *First-line management of type 2 diabetes in adults?* | **Tier 1** — Grounded (corpus) |
| *Current ICMR advisory on dengue fluid management?*   | **Tier 2** — Grounded (allowlisted web) |
| *Management of refractory paediatric Crohn's disease?* | **Tier 3** — Unverified general model |
| anything else | **Tier 3** — query-agnostic "not grounded" fallback |

Inline source pills and reference/citation links open the **citation card**
(verbatim passage, source metadata, PDF deep-link) — the trust-forming moment
the PRD (§6.4) prioritises above all other polish.

## Design → screen mapping

| Canvas frame | Implemented as |
|---|---|
| 1 · First run | `screenConsent()` — gated Continue |
| 2 · Empty state | `screenHome()` — chips + suggestions + composer |
| 3 · Retrieving | `screenRetrieving()` — choreographed staged progress |
| 4 · Tier 1 (corpus) | `renderGrounded()` green treatment |
| 5 · Citation card | `openCitation()` slide-over overlay |
| 6 · Tier 2 (web) | `renderGrounded()` blue treatment + snapshot stamp |
| 7 · Tier 3 (general) | `renderTier3()` purple, highlighted, no citation |

## Desktop app — `app.html` (App Conversation canvas)

Three-pane desktop layout implementing the **App Conversation** design:

- **Sidebar** — New question, Ask/Library/Sources nav, recent conversations
  (each recent opens its conversation; unknown topics honestly land in Tier 3),
  and the beta user footer.
- **Conversation column** — sticky title bar (Save/Share), persistent
  non-dismissable disclaimer strip (PRD §6.6), cited answer, follow-ups,
  and the composer. Submitting a question plays the staged-retrieval
  choreography before the answer.
- **Sources rail** — one card per cited source; the primary source is featured
  with its verbatim quoted passage and a PDF deep-link. Clicking an inline
  citation pill in the answer flashes the matching rail card; clicking a
  compact card promotes it to the featured treatment. Tier 2 shows the
  snapshot-stamped web source; Tier 3 shows an explicit "No grounded sources"
  state.

The rail collapses under 1180px and the sidebar under 860px.

## Admin portal — `admin.html` (Admin Portal canvas)

Configuration back-office for the beta, four views:

- **Allowed websites** — the Tier 2 `allowed_domains` allowlist. Working
  add-domain form (domain validated, trust note required, duplicates
  rejected), live search, and enable/disable toggles. Disabled rows dim to
  show the *effective* list exactly as sent to the API.
- **Models & parameters** — config-as-data table (thresholds, caps, model
  ids) with the global-and-immediate warning banner and a CONFIRM chip on
  `model.generation`.
- **API keys** — masked provider keys with a two-step confirm on Rotate
  (key material never shown; PRD §7.8 secrets-manager rule).
- **Audit log** — every mutation made in the UI (toggle, add, rotate)
  appends a color-coded actor/action/change row, newest first, mirroring
  the Postgres-trigger audit design.

## Authentication — Google Sign-In + admin allowlist

`login.html` gates `app.html` (role ≥ clinician) and `admin.html` (role ≥
editor) via a synchronous guard in each page's `<head>`. Roles:
**clinician** (app only) < **editor** (＋ allowlist read/write, config read)
< **admin** (everything, incl. Beta access and API keys) — per PRD §6.5.

Who may sign in is maintained in **Admin → Beta access**: add/remove Google
emails, change roles, enable/disable. Disabling revokes on the visitor's next
page load; role changes apply live. Request-access submissions from the
marketing site land in the same view's **Pending requests** queue, so
*request → approve → sign in* is a closed loop. Every mutation is audit-logged
against the real signed-in actor. Admins cannot disable or demote themselves.

### Enabling real Google Sign-In

Set `GOOGLE_CLIENT_ID` in [`js/auth.js`](js/auth.js) to a Web OAuth client ID
(console.cloud.google.com → APIs & Services → Credentials), and add your
origins to *Authorised JavaScript origins*:
`https://newexplorer-ai.github.io` and `http://localhost:4173`.
While it is empty the login page runs a clearly-labelled **demo mode** that
simulates sign-in so the flow stays testable.

### ⚠ This is a gate, not a security boundary

The allowlist is enforced **in the browser** and can be bypassed by anyone
technical. That is acceptable only because everything behind it is mock data.
Before a real corpus, real API keys, or real users exist:

1. Verify the Google ID token signature **server-side** (Supabase Auth or a
   FastAPI `/auth/google` endpoint) — the client never decides authenticity.
2. Move the allowlist to Postgres `allowed_users` + RLS, re-checked on every
   request.
3. Delete demo mode and the `localStorage` stores.

The single swap point is `verifyAndAuthorize()` in `js/auth.js`.

## Files

- `index.html` + `css/site.css` + `js/site.js` — marketing home (hero, tiers,
  citation demo, FAQ accordion, request-access modal → waitlist)
- `login.html` + `css/login.css` + `js/login.js` — Google Sign-In / demo picker
- `js/auth.js` — session, allowlist, roles, route guard (**the auth core**)
- `mobile.html` — mobile-frame flow (top bar, viewport, composer, overlay)
- `app.html` — desktop app: Ask · Conversation (3 tiers + withheld) · Library · Sources
- `admin.html` — admin portal (allowlist, config, keys, audit)
- `css/styles.css` — design tokens lifted verbatim from the canvas + components
- `css/app.css` — desktop shell (sidebar, conversation column, sources rail)
- `css/admin.css` — admin tables, toggles, warn banner, audit chips
- `js/data.js` — demo corpus content, tier routing, citation payloads (shared)
- `js/app.js` — mobile flow state machine
- `js/desktop.js` — desktop app controller (recents, conversation, rail)
- `js/admin.js` — admin state, views, and audit-logging mutations

## Notes / next steps toward the real MVP

- Swap `js/data.js` for live calls against the response contract in PRD §7.5
  (`tier` + `status` drive the same rendering paths already built here).
- Token streaming (SSE) replaces the fixed retrieval choreography.
- Design fidelity is CSS-token driven, so re-importing an updated canvas is a
  token diff, not a rewrite.
