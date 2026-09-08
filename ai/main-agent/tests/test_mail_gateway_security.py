from __future__ import annotations

from cryptography.fernet import Fernet

from mail_gateway.providers import GmailClient, OutlookClient
from mail_gateway.token_store import EncryptedFileTokenStore, OAuthTokenRecord


def test_token_store_encrypts_oauth_tokens(tmp_path):
    path = tmp_path / "tokens.bin"
    key = Fernet.generate_key().decode("ascii")
    store = EncryptedFileTokenStore(path=str(path), key=key)
    store.upsert(
        OAuthTokenRecord(
            provider="gmail",
            account_id="mail@example.com",
            address="mail@example.com",
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            expires_at=9999999999,
            scopes=("gmail.readonly",),
        )
    )

    raw = path.read_bytes()
    assert b"secret-access-token" not in raw
    assert b"secret-refresh-token" not in raw

    loaded = store.get("gmail", "mail@example.com")
    assert loaded.access_token == "secret-access-token"
    assert loaded.refresh_token == "secret-refresh-token"


def test_gmail_authorization_url_preserves_state_and_readonly_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    store = EncryptedFileTokenStore(path=str(tmp_path / "tokens.bin"), key=Fernet.generate_key().decode())
    client = GmailClient(store)

    url = client.authorization_url(
        redirect_uri="https://api.example.com/mail/oauth/gmail/callback",
        state="secure-state-value-123456",
        scopes=("openid", "email", "https://www.googleapis.com/auth/gmail.readonly"),
    )

    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "state=secure-state-value-123456" in url
    assert "gmail.readonly" in url
    assert "access_type=offline" in url


def test_outlook_authorization_url_uses_auth_code_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "ms-client")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_OAUTH_TENANT", "common")
    store = EncryptedFileTokenStore(path=str(tmp_path / "tokens.bin"), key=Fernet.generate_key().decode())
    client = OutlookClient(store)

    url = client.authorization_url(
        redirect_uri="https://api.example.com/mail/oauth/outlook/callback",
        state="secure-state-value-123456",
        scopes=("openid", "email", "offline_access", "Mail.Read"),
    )

    assert "login.microsoftonline.com/common/oauth2/v2.0/authorize" in url
    assert "response_type=code" in url
    assert "offline_access" in url
    assert "Mail.Read" in url
