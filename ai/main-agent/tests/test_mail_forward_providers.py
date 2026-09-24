import base64
from email import message_from_bytes
from email.message import EmailMessage

import pytest
from cryptography.fernet import Fernet

from mail_gateway.providers import GmailClient, OutlookClient
from mail_gateway.token_store import EncryptedFileTokenStore, OAuthTokenRecord


class Response:
    def __init__(self, data=None):
        self.data = data or {}

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class GmailHTTP:
    def __init__(self, original: bytes):
        self.original = original
        self.sent = None

    def get(self, url, **kwargs):
        assert kwargs.get("params") == {"format": "raw"}
        return Response({"raw": base64.urlsafe_b64encode(self.original).decode("ascii")})

    def post(self, url, **kwargs):
        self.sent = kwargs["json"]["raw"]
        return Response({"id": "sent-1"})


class OutlookHTTP:
    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return Response()


def token_store(tmp_path, provider: str, scopes: tuple[str, ...]):
    store = EncryptedFileTokenStore(path=str(tmp_path / "tokens.bin"), key=Fernet.generate_key().decode())
    store.upsert(OAuthTokenRecord(
        owner_user_id="owner", provider=provider, account_id="account-1",
        address="owner@example.com", access_token="secret", refresh_token="refresh",
        expires_at=9999999999, scopes=scopes,
    ))
    return store


def test_gmail_forward_preserves_original_and_attachments(tmp_path):
    original = EmailMessage()
    original["From"] = "sender@example.com"
    original["To"] = "owner@example.com"
    original["Subject"] = "Invoice"
    original.set_content("Attached invoice")
    original.add_attachment(b"invoice-file", maintype="application",
                            subtype="pdf", filename="invoice.pdf")
    client = GmailClient(token_store(
        tmp_path, "gmail", ("https://www.googleapis.com/auth/gmail.readonly",
                              "https://www.googleapis.com/auth/gmail.send")))
    transport = GmailHTTP(original.as_bytes())
    client.http = transport
    result = client.forward_message("owner", "account-1", "provider-message", "team@example.com")
    assert result["status"] == "accepted"
    outgoing = message_from_bytes(base64.urlsafe_b64decode(transport.sent))
    assert outgoing["To"] == "team@example.com"
    assert "Invoice" in outgoing["Subject"]
    assert any(part.get_filename() == "invoice.pdf" for part in outgoing.walk())
    assert any(part.get_payload(decode=True) == b"invoice-file" for part in outgoing.walk())


def test_gmail_forward_requires_explicit_send_scope(tmp_path):
    client = GmailClient(token_store(
        tmp_path, "gmail", ("https://www.googleapis.com/auth/gmail.readonly",)))
    client.http = GmailHTTP(b"original")
    with pytest.raises(PermissionError):
        client.forward_message("owner", "account-1", "provider-message", "team@example.com")
    assert client.http.sent is None


def test_outlook_uses_native_forward_and_mail_send_permission(tmp_path):
    client = OutlookClient(token_store(tmp_path, "outlook", ("Mail.Read", "Mail.Send")))
    transport = OutlookHTTP()
    client.http = transport
    result = client.forward_message("owner", "account-1", "message-123", "team@example.com")
    assert result["status"] == "accepted"
    url, payload = transport.requests[0]
    assert url.endswith("/me/messages/message-123/forward")
    assert payload["json"]["toRecipients"] == [{"emailAddress": {"address": "team@example.com"}}]
