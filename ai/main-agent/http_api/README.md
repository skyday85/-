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
