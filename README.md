# QQ Pay

A usable sandbox merchant workspace for shareable checkouts, repeat-safe captures, full refunds, and an auditable balanced ledger.

[Open the beta](https://qq-pay.vercel.app) · [API reference](https://qq-pay.vercel.app/docs) · [Engineering lab](https://qq-pay.vercel.app/lab) · [Issues](https://github.com/0xMudit/qq-pay/issues)

**v0.2.0-beta.1** · FastAPI · PostgreSQL / Supabase · Vercel · MIT

## Use the application

1. Create a private merchant account or use the shared demo credentials.
2. Create a checkout with your own title, amount and currency.
3. Share its checkout link; the customer completes a sandbox payment without signing in.
4. Inspect the transaction and ledger, issue a full refund, or cancel an unpaid checkout.

### Demo credentials

Username: `demo-pay`
Password: `PayBeta!2026`

The demo is a shared public account. Its data and API keys are visible to others who sign in with those credentials. Create your own account for isolated data. The application is a functional beta, not a production-certified service.

## Run locally

```sh
python -m venv .venv
# Activate .venv using your shell's command.
pip install -r requirements.txt
# Set API_KEY to a random secret of at least 16 characters.
uvicorn app:app --reload
```

Open http://localhost:8000. SQLite is supported for local exploration and unit tests. Set DATABASE_URL to a PostgreSQL psycopg connection URL with TLS for deployment. On a fresh local database, startup initializes the schema and shared demo account. Hosted schema changes are provided in `supabase/migrations/`.

For Docker, copy `.env.example` to `.env`, replace its secret and run `docker compose up --build`. Change host port mappings when running multiple apps. Scheduled recovery for Pocket requires its hosted scheduler or a running beta worker; plain local API startup alone does not supply a persistent scheduler.

## API integration

Create a key in the account UI and send it as `Authorization: Bearer TOKEN`. Keys expire after 30 days and can be revoked. Browser sessions use HttpOnly cookies and expire after seven days. API payloads and validation rules are documented at `/docs`.

```text
POST /api/payments                 Create an idempotent checkout
GET  /api/payments                 Account-owned checkout list
GET  /api/payments/{id}            Ledger and activity
POST /api/payments/{id}/refund     Full sandbox refund
POST /api/payments/{id}/cancel     Cancel an unpaid checkout
GET  /api/checkout/{id}            Public checkout details
POST /api/checkout/{id}/pay        Public sandbox payment
```

## Correctness and system design

### Payment guarantees

Amounts use integer minor units. Idempotency keys are unique within an account; conflicting requests return HTTP 409. Capture performs a conditional pending-to-captured update and writes two ledger entries in one transaction. Repeating capture creates no extra entries. Full refund performs the reverse transition and adds reversal entries atomically; repeated refunds do not duplicate them. Cancelled or refunded checkouts cannot be paid again. Every transition adds an activity event.

Checkout URLs are intentionally public and unguessable UUID links. They disclose the checkout title, merchant username, amount, currency and status to their holder. Merchant lists, refunds, cancellations, ledger details and API keys require account ownership.

This release uses the **built-in sandbox**, as requested. It does not charge cards, settle funds or integrate a bank/provider. No card data is collected. Partial refunds, signed webhooks and external reconciliation are future features. A workspace holds up to 500 checkouts. Dashboard INR totals do not aggregate other currencies.

## Verification

```sh
python -m pytest -q
```

Tests cover ownership boundaries, session and API-key revocation, validation, and domain failure modes. `check_postgres.py` is an opt-in concurrency check for the original engineering-lab primitives; it writes synthetic data and is not a load benchmark. See [architecture](docs/architecture.md), [deployment](docs/deployment.md), and [security](SECURITY.md).

## Beta boundaries

No uptime SLA or measured throughput claim. Account usernames are not email addresses. Email verification, password recovery, MFA and self-service account deletion are not implemented. Store recoverable credentials and avoid sensitive data while evaluating the beta. Quotas and rate limits bound usage; they are not a comprehensive anti-abuse system.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Include failure-mode tests and explain concurrency assumptions in pull requests. Do not commit secrets or real location data. Licensed under MIT.
