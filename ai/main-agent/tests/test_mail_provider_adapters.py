from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter


class FakeGateway:
    def __init__(self):
        self.accounts = {
            "gmail": [{"account_id": "g1", "address": "g@example.com", "display_name": "Gmail"}],
            "outlook": [{"account_id": "o1", "address": "o@example.com", "display_name": "Outlook"}],
        }

    def list_accounts(self, provider):
        return self.accounts[provider]

    def connection_state(self, provider, account_id):
        return {"connected": True, "scopes": ["mail.read"]}

    def build_authorization_url(self, provider, *, redirect_uri, state, scopes):
        return f"https://auth.example/{provider}?state={state}"

    def complete_authorization(self, provider, *, code, redirect_uri, state, scopes):
        return self.accounts[provider][0]

    def fetch_messages(self, provider, account_id, *, cursor, limit):
        return {
            "messages": [
                {
                    "provider_message_id": "m1",
                    "thread_id": "t1",
                    "sender": "sender@example.com",
                    "recipients": ["receiver@example.com"],
                    "subject": "Hello",
                    "received_at": "2026-09-08T12:00:00Z",
                }
            ],
            "next_cursor": "next",
        }

    def fetch_attachment(self, provider, account_id, provider_message_id, attachment_id):
        return {"attachment_id": attachment_id, "content_ref": "opaque://attachment"}


def test_gmail_adapter_normalizes_messages_and_uses_oauth():
    adapter = GmailProviderAdapter(FakeGateway())
    account = list(adapter.list_accounts())[0]
    page = adapter.fetch_messages(account.account_id)

    assert account.provider == "gmail"
    assert account.auth_mode == "oauth"
    assert page["messages"][0]["email_id"] == "gmail:g1:m1"
    assert "gmail.readonly" in " ".join(adapter.scopes)


def test_outlook_adapter_exposes_mail_read_and_oauth_flow():
    adapter = OutlookProviderAdapter(FakeGateway())
    url = adapter.build_authorization_url(redirect_uri="app://oauth", state="s1")
    account = adapter.complete_authorization(code="code", redirect_uri="app://oauth", state="s1")

    assert url.startswith("https://auth.example/outlook")
    assert account.provider == "outlook"
    assert "Mail.Read" in adapter.scopes
