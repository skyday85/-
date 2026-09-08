# Mail Gateway

Standalone credential-owning service for Gmail and Outlook. The Main Agent HTTP API talks to this service with a service token. Provider client secrets, access tokens and refresh tokens never enter the Main Agent runtime, unified client or business modules.

## Security boundary

- Production traffic must use HTTPS/TLS.
- `MAIL_GATEWAY_SERVICE_TOKEN` authenticates the Main Agent API to this gateway.
- OAuth client secrets live only in this service's secret store/environment.
- OAuth tokens are encrypted at rest by `MAIL_GATEWAY_ENCRYPTION_KEY`.
- The encrypted token file is created with owner-only permissions.
- A managed KMS/secrets backend can replace `EncryptedFileTokenStore` without changing the provider adapter contract.
- Do not expose this service directly to the Mac/iPhone client.

Generate a local Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Google setup

Create an OAuth 2.0 Web application in Google Cloud, enable Gmail API, and configure the Main Agent callback URL as an authorized redirect URI. The application requests `openid`, `email` and Gmail read-only access.

## Microsoft setup

Register a Microsoft Entra application, configure the same Main Agent callback URL, create a confidential-client secret, and grant delegated `Mail.Read` plus `offline_access`. `MICROSOFT_OAUTH_TENANT=common` supports both organizational and personal Microsoft accounts; set a tenant ID to restrict access to one organization.

## Run locally

```bash
pip install -r mail_gateway/requirements.txt
uvicorn mail_gateway.app:app --host 127.0.0.1 --port 8100
```

Then configure the Main Agent API:

```text
MAIL_GATEWAY_BASE_URL=http://127.0.0.1:8100
MAIL_GATEWAY_SERVICE_TOKEN=<same token as gateway>
```

Production must replace localhost HTTP with HTTPS.
