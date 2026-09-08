from app_shell.client_api import PushEventPolicy
from app_shell.navigation import AppShellRegistry
from mail_contour.providers import (
    MailProviderAccount,
    MailProviderConnectionState,
    MailProviderRegistry,
)
from mail_contour.sync_service import UnifiedMailSyncService
from mail_contour.unified_mailbox import UnifiedMailbox


class FakeMailProvider:
    provider = "fake"

    def list_accounts(self):
        return [
            MailProviderAccount("work", "work@example.com", "fake", "Рабочая"),
            MailProviderAccount("sales", "sales@example.com", "fake", "Продажи"),
        ]

    def connection_state(self, account_id):
        return MailProviderConnectionState("fake", account_id, True, ("mail.read",))

    def build_authorization_url(self, *, redirect_uri, state):
        return f"https://example.test/oauth?redirect_uri={redirect_uri}&state={state}"

    def complete_authorization(self, *, code, redirect_uri, state):
        return self.list_accounts()[0]

    def fetch_messages(self, account_id, *, cursor=None, limit=100):
        rows = {
            "work": [
                {
                    "email_id": "mail-1",
                    "account_id": "work",
                    "provider_message_id": "provider-1",
                    "thread_id": "thread-1",
                    "sender": "supplier@example.com",
                    "recipients": ["work@example.com"],
                    "subject": "Счет за запчасти",
                    "received_at": "2026-09-08T10:00:00+03:00",
                    "body_text": "Счет во вложении",
                    "attachments": [{
                        "attachment_id": "att-1",
                        "filename": "invoice.pdf",
                        "mime_type": "application/pdf",
                    }],
                }
            ],
            "sales": [
                {
                    "email_id": "mail-2",
                    "account_id": "sales",
                    "provider_message_id": "provider-2",
                    "thread_id": "thread-2",
                    "sender": "client@example.com",
                    "recipients": ["sales@example.com"],
                    "subject": "Заявка на перевозку",
                    "received_at": "2026-09-08T11:00:00+03:00",
                    "body_text": "Нужна доставка",
                }
            ],
        }
        return {"messages": rows[account_id], "next_cursor": "next"}

    def fetch_attachment(self, account_id, provider_message_id, attachment_id):
        return {"attachment_id": attachment_id}


def build_mail_stack():
    mailbox = UnifiedMailbox()
    providers = MailProviderRegistry()
    providers.register(FakeMailProvider())
    sync = UnifiedMailSyncService(mailbox, providers)
    sync.refresh_accounts()
    return mailbox, providers, sync


def test_sync_combines_multiple_accounts_into_one_inbox():
    _, _, sync = build_mail_stack()
    result = sync.sync_all()
    inbox = sync.inbox()
    assert result["total_imported"] == 2
    assert [x["email_id"] for x in inbox] == ["mail-2", "mail-1"]


def test_provider_dedupe_survives_repeated_sync():
    _, _, sync = build_mail_stack()
    sync.sync_all()
    second = sync.sync_all()
    assert second["total_imported"] == 0
    assert len(sync.inbox()) == 2


def test_unified_inbox_can_filter_by_account_and_search():
    _, _, sync = build_mail_stack()
    sync.sync_all()
    assert [x["email_id"] for x in sync.inbox(account_ids=["sales"])] == ["mail-2"]
    assert [x["email_id"] for x in sync.inbox(search="счет")] == ["mail-1"]


def test_app_shell_exposes_same_business_modules_on_mac_and_iphone():
    registry = AppShellRegistry()
    mac = registry.build_client_manifest("mac")
    iphone = registry.build_client_manifest("iphone")
    assert [x["module_id"] for x in mac["navigation"]] == [x["module_id"] for x in iphone["navigation"]]
    assert mac["backend_contract"] == iphone["backend_contract"] == "shared"


def test_generic_pdf_does_not_become_invoice_only_because_of_extension():
    mailbox, _, _ = build_mail_stack()
    mailbox.ingest([{
        "email_id": "mail-3",
        "account_id": "work",
        "provider_message_id": "provider-3",
        "thread_id": "thread-3",
        "sender": "partner@example.com",
        "recipients": ["work@example.com"],
        "subject": "Документы",
        "received_at": "2026-09-08T12:00:00+03:00",
        "body_text": "Во вложении презентация",
        "attachments": [{"attachment_id": "att-3", "filename": "presentation.pdf", "mime_type": "application/pdf"}],
    }])
    result = mailbox.classify_and_route("mail-3")
    assert result["classification"] != "supplier_invoice_candidate"


def test_push_policy_marks_supplier_invoice_as_high_priority():
    event = PushEventPolicy().from_mail({
        "email_id": "mail-1",
        "classification": "supplier_invoice_candidate",
        "subject": "Счет",
        "sender": "supplier@example.com",
    })
    assert event is not None
    assert event.priority == "high"
    assert event.route == "/mail/mail-1"
