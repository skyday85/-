# Unified HTTP API

This service exposes the shared backend contract used by the macOS and iPhone clients.

## Local development

```bash
cd ai/main-agent
python -m pip install -r requirements-http.txt
uvicorn http_api.app:app --host 127.0.0.1 --port 8000 --reload
```

The Vite/Tauri client uses `http://127.0.0.1:8000` by default in local development.

## Production invariants

- Public API and client URLs use HTTPS only.
- Anonymous API access is rejected outside local development.
- Authentication is supplied by the trusted application/reverse-proxy layer through `X-Authenticated-User` until the dedicated identity service is connected.
- Gmail/Microsoft OAuth client secrets and refresh tokens are never stored in this service or in the Main Agent.
- `MAIL_GATEWAY_BASE_URL` points to the external credential-owning mail gateway and must use HTTPS outside localhost.
- `MAIL_GATEWAY_SERVICE_TOKEN` is stored only in deployment secret storage.

## Endpoints

- `GET /health`
- `GET /client/bootstrap?platform=mac|iphone`
- `POST /agent/commands`
- `GET /mail/inbox`
- `GET /mail/messages/{email_id}`
- `POST /mail/messages/{email_id}/process`
- `POST /mail/sync`
- `POST /mail/accounts/{gmail|outlook}/authorize`
- `GET /mail/oauth/{gmail|outlook}/callback`

The API talks to `MainAgentRuntime`; clients never access module databases or provider credentials directly.

## Mail identity and routing

Organization membership is mandatory for the client mailbox endpoints. Set
`APP_ORGANIZATION_ID`, `MAIL_BOOTSTRAP_OWNER_USER_ID`, and
`MAIL_BOOTSTRAP_OWNER_EMAIL` together for initial owner creation; this ID
must correspond to a trusted authenticated subject. A reverse proxy/IdP must
verify users and organization membership, strip incoming identity headers,
and insert verified identity plus `APP_TRUSTED_PROXY_SECRET` in production.
Do not expose development header authentication over a public network.

- `GET/POST /mail/admin/users`: list/create mail-service users (externally authenticated).
- `POST /mail/admin/users/{user_id}/status`: deactivate/reactivate accounts.
- `GET /mail/admin/connected-accounts`: connected provider accounts for an
  owner in the same organization.
- `GET/POST/DELETE /mail/admin/grants`: assign/revoke mailbox visibility and
  forwarding approval.
- `GET/POST /mail/admin/rules`: manage content-matching routing rules.
- `POST /mail/admin/rules/{rule_id}/status`: immediately enable/disable rules.
- `GET /mail/forward-jobs`: only jobs from explicitly assigned mailboxes.
- `GET /mail/forward-jobs/{job_id}/preview`: permission-scoped source preview.
- `GET /mail/forward-jobs/{job_id}/attachments/{id}`: permission-scoped download.
- `POST /mail/forward-jobs/{job_id}/approve|dismiss`: explicit send decision.

The current SQLite implementation is suitable for a single development service.
Before horizontally scaling, migrate organization directory, account grants,
forwarding idempotency/claims and mail persistence to a shared transactional
database. Provider OAuth secrets remain in the separate encrypted Mail Gateway.
For scanned PDFs/image OCR, deploy resource-limited `tesseract` (rus+eng) and
`pdftoppm` binaries; scanned files with missing tooling or unreadable text
stay in manual review and are never automatically sent.

## Cross-account logical message deduplication

`GET /mail/inbox?source_id=...` filters by an opaque account/source identifier
received from `/client/bootstrap`. Source IDs are compared against CURRENT
live grants; guessed or revoked sources return 403. With no filter, only the
mailboxes currently assigned to the authenticated user are combined.

The visible inbox groups conservatively matching source copies into one
logical message and includes `source_accounts`, `source_count`, and
`copy_count`. Unread counts and smart-folder counts reflect logical messages
visible to that user, rather than a sum of physical mailbox deliveries.
The account selector can still display each original independently.

The organization-scoped SQLite `org_mail_processing` ledger allows ONLY the
first physical delivery to trigger downstream events, invoices and forwarding
rules. Later copies receive their own classification but do not repeat
side effects, including after a service restart. Processing failures that
could have partially completed are parked as `needs_review` and are NOT
automatically resent or retried.

Two messages carrying DIFFERENT RFC Internet Message-IDs are never collapsed.
Without a usable ID, strict plaintext/attachment equality, distinct source
accounts and arrival within two minutes are all required. Short or incomplete
messages remain independent rather than risking false deduplication.

Production deployment must migrate this ledger into the organization's shared
transactional database along with directory/grants before running multiple
replicas. Existing source data is not deleted. Previously processed historical
messages require explicit migration/reconciliation before any bulk replay.
