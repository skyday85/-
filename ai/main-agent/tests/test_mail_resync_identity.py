from mail_contour.persistence import MailPersistence
from mail_contour.providers import MailProviderRegistry, MailProviderAccount
from mail_contour.sync_service import UnifiedMailSyncService
from mail_contour.unified_mailbox import UnifiedMailbox


class ExampleProvider:
    provider = "fake"

    def __init__(self):
        self.cursors = []

    def list_accounts(self, user_id):
        return [MailProviderAccount("box", "box@example.test", "fake", user_id)]

    def fetch_messages(self, user_id, account_id, *, cursor=None, limit=100):
        self.cursors.append(cursor)
        original = {"email_id": "first", "account_id": "box",
                    "provider_message_id": "provider-first",
                    "sender": "sender@example.test", "recipients": ["box@example.test"],
                    "subject": "Old", "received_at": "2026-09-24T09:00:00Z",
                    "body_text": "Previously received mail"}
        if len(self.cursors) == 1:
            return {"messages": [original], "next_cursor": "older-page"}
        newer = {**original, "email_id": "second", "provider_message_id": "provider-second",
                 "internet_message_id": "<second@example.test>",
                 "received_at": "2026-09-24T10:00:00Z", "subject": "New"}
        return {"messages": [newer, {**original, "internet_message_id": "<first@example.test>"}]
                if cursor is None else []}


def test_sync_checks_newest_page_and_updates_old_message_identity(tmp_path):
    path = str(tmp_path / "mail.sqlite3")
    persistence = MailPersistence(path)
    mailbox = UnifiedMailbox(persistence)
    providers = MailProviderRegistry()
    source = ExampleProvider()
    providers.register(source)
    sync = UnifiedMailSyncService(mailbox, providers, persistence)
    sync.refresh_accounts("user")
    assert sync.sync_account("user", "box")["imported"] == 1
    assert sync.sync_account("user", "box")["imported"] == 1
    assert source.cursors == [None, None]
    assert mailbox.get_message("user", "first")["internet_message_id"] == "<first@example.test>"
    restarted = UnifiedMailbox(MailPersistence(path))
    assert restarted.get_message("user", "first")["internet_message_id"] == "<first@example.test>"
