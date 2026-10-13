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
