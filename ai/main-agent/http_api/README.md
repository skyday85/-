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

## Business-case orchestration (development MVP)

The Main Agent stores **references** to records in other applications, not copies
of business data, invoices, payments or OAuth credentials. Each request is scoped
to the authenticated `X-Organization-Id`.

- `GET /business-cases?status=...` — list this organization's cases
- `POST /business-cases` — create a case with `title`, `case_type`
- `GET /business-cases/{case_id}` — links, signals, reviews, audit history
- `POST /business-cases/{case_id}/links` — link an active registered project's record
- `POST /business-cases/{case_id}/signals` — ingest a source event from a registered active project
- `POST /business-cases/{case_id}/reviews/{review_id}/decision` — authenticated user approves or rejects a specific review
- `POST /business-cases/{case_id}/resume` — user explicitly resumes a failed case with a reason
- `POST /business-cases/{case_id}/close` — user closes a case only when no unresolved review or blocking failure remains

External signals must include a stable `source_event_id`, `source_record_id`,
`project_id` and `event_type`. The ledger suppresses duplicate source events
across cases within the same organization and project; a conflicting reuse is
rejected with HTTP 409. Allowed event types:
`observed`, `progress`, `completed`, `failed`, `review_requested`.
A source's `completed` signal does **not** close the business case automatically.
No event directly mutates an application's records.

**Security**: The signal route requires `X-Case-Integration-Key` matching
`APP_CASE_INGEST_KEY`, in addition to trusted user/organization context.
Never embed service secrets in a browser or mobile client. The trusted proxy
must validate the user's actual organization membership and discard
untrusted forwarded identity headers. This reference implementation does
not provide an independent identity provider.

**Storage**: `MAIN_AGENT_DATABASE_PATH` points to a local SQLite reference
implementation. It is intended for one-process/local testing; run no
multi-instance production deployment with this file-backed store.
The future dedicated main-agent service should migrate the same contract to
shared organization-isolated Postgres before real multi-user rollout.
