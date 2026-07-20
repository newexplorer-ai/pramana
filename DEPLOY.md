# Deploying Pramana to `pramana.heybolo.de`

`heybolo.de` itself is already taken — it serves the Bolo app from the Vercel
project `german1`. Pramana therefore goes on the **`pramana.heybolo.de`**
subdomain, and it is **not** deployed to Vercel: the orchestrator is a
long-running FastAPI process with a SQLite database, and Vercel's serverless
functions have an ephemeral filesystem (every sign-in, allowlist edit, and
saved conversation would vanish between requests).

Host: **Fly.io**, region **Mumbai (`bom`)** — matching the PRD's India
data-residency intent (§7.9) — with a persistent volume for the database.

## One-time setup

Everything below needs your credentials, so run it yourself.

```bash
cd "/Users/krishnaprasad.kesavan/doctor - pramana"

# 1. Log in (opens a browser)
flyctl auth login

# 2. Create the app + the persistent volume the DB lives on
flyctl apps create pramana
flyctl volumes create pramana_data --region bom --size 1 --app pramana

# 3. Secrets. ANTHROPIC_API_KEY is what makes real answers work.
flyctl secrets set --app pramana \
  ANTHROPIC_API_KEY='sk-ant-...' \
  PRAMANA_DEMO_PASSWORD="$(openssl rand -base64 12)"

# Print the access code you just generated — you'll need to share it:
flyctl secrets list --app pramana        # (names only; see note below)

# 4. Deploy (Fly builds the Dockerfile remotely — no local Docker needed)
flyctl deploy --app pramana

# 5. Attach the subdomain
flyctl certs create pramana.heybolo.de --app pramana
flyctl certs show pramana.heybolo.de --app pramana   # prints the DNS target
```

> **Tip:** generate the access code first so you can record it —
> `CODE=$(openssl rand -base64 12); echo "$CODE"` then pass `PRAMANA_DEMO_PASSWORD="$CODE"`.
> Fly never shows a secret's value again after it's set.

## DNS (Porkbun)

`heybolo.de` uses Porkbun nameservers. In the Porkbun DNS panel for
`heybolo.de`, add the record `flyctl certs show` asks for — normally:

| Type    | Host      | Value                  |
|---------|-----------|------------------------|
| `CNAME` | `pramana` | `pramana.fly.dev`      |

Plus the `_acme-challenge.pramana` record Fly prints, for the TLS certificate.
There is **no wildcard** on this domain, so the record must be added explicitly.
Propagation is usually a few minutes; `flyctl certs show` flips to "Ready".

## Verify after deploy

```bash
curl -s https://pramana.heybolo.de/api/health
# expect: {"ok":true,"google_auth":false,"demo_password":true,"anthropic":true}
```

`anthropic: true` is the one that matters — it means real answers will work.
Then open the site, sign in with your email + the access code, and ask a
question.

## Access control on a public URL

Until a Google OAuth client is configured, sign-in is **email + shared access
code**, and the email must still be on the allowlist. That means:

- Only people you add in **Admin → Beta access** can get in, and they also need
  the code.
- `PRAMANA_DEMO_PASSWORD` is what stops the public URL from being an open door.
  **Never deploy without it.**

To upgrade to real Google Sign-In later:

```bash
flyctl secrets set --app pramana GOOGLE_CLIENT_ID='....apps.googleusercontent.com'
```

and add `https://pramana.heybolo.de` to the OAuth client's authorised
JavaScript origins. The access-code field disappears automatically.

## Updating

```bash
git push                       # keeps the GitHub Pages static demo in sync
flyctl deploy --app pramana    # ships the real app
```

## Costs

One `shared-cpu-1x` 512 MB machine with `auto_stop_machines` — it suspends when
idle, so the floor is roughly the 1 GB volume (a few cents a month). The real
cost is Anthropic API usage per query (~a few cents each; the per-user daily cap
in **Admin → Models & config** is the guardrail).
