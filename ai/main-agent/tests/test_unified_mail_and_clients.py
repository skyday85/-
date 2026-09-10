from app_shell.client_api import PushEventPolicy
from app_shell.navigation import AppShellRegistry
from integrations.events import IntegrationOutbox
from integrations.fleet_documents import FleetDocumentQueue
from mail_contour.mail_collector_agent import MailCollectorAgent
from mail_contour.providers import MailProviderAccount, MailProviderConnectionState, MailProviderRegistry
from mail_contour.sync_service import UnifiedMailSyncService
from mail_contour.unified_mailbox import UnifiedMailbox

USER_A = "user-a"
USER_B = "user-b"


class FakeMailProvider:
    provider = "fake"

    def list_accounts(self, user_id):
        return [
            MailProviderAccount("work", f"work-{user_id}@example.com", "fake", user_id, "Рабочая"),
            MailProviderAccount("sales", f"sales-{user_id}@example.com", "fake", user_id, "Продажи"),
        ]

    def connection_state(self, user_id, account_id):
        return MailProviderConnectionState("fake", account_id, user_id, True, ("mail.read",))

    def build_authorization_url(self, *, user_id, redirect_uri, state):
        return f"https://example.test/oauth?state={state}&user={user_id}"

    def complete_authorization(self, *, user_id, code, redirect_uri, state):
        return self.list_accounts(user_id)[0]

    def fetch_messages(self, user_id, account_id, *, cursor=None, limit=100):
        suffix = user_id
        rows = {
            "work": [{"email_id": f"mail-1-{suffix}", "account_id": "work", "provider_message_id": f"provider-1-{suffix}", "thread_id": "thread-1", "sender": "supplier@example.com", "recipients": ["work@example.com"], "subject": "Счет за запчасти", "received_at": "2026-09-08T10:00:00+03:00", "body_text": "Счет за детали во вложении", "attachments": [{"attachment_id": "att-1", "filename": "invoice.pdf", "mime_type": "application/pdf"}] }],
            "sales": [{"email_id": f"mail-2-{suffix}", "account_id": "sales", "provider_message_id": f"provider-2-{suffix}", "thread_id": "thread-2", "sender": "client@example.com", "recipients": ["sales@example.com"], "subject": "Заявка на перевозку", "received_at": "2026-09-08T11:00:00+03:00", "body_text": "Нужна перевозка груза Москва — Казань"}],
        }
        return {"messages": rows[account_id], "next_cursor": "next"}

    def fetch_attachment(self, user_id, account_id, provider_message_id, attachment_id):
        return {"attachment_id": attachment_id}


def build_mail_stack():
    mailbox = UnifiedMailbox()
    providers = MailProviderRegistry()
    providers.register(FakeMailProvider())
    sync = UnifiedMailSyncService(mailbox, providers)
    sync.refresh_accounts(USER_A)
    sync.refresh_accounts(USER_B)
    return mailbox, providers, sync


def test_sync_isolates_users_with_same_account_ids():
    _, _, sync = build_mail_stack()
    sync.sync_all(USER_A)
    sync.sync_all(USER_B)
    assert {x["user_id"] for x in sync.inbox(USER_A)} == {USER_A}
    assert {x["user_id"] for x in sync.inbox(USER_B)} == {USER_B}
    assert len(sync.inbox(USER_A)) == 2
    assert len(sync.inbox(USER_B)) == 2


def test_provider_dedupe_is_scoped_per_user():
    _, _, sync = build_mail_stack()
    sync.sync_all(USER_A)
    assert sync.sync_all(USER_A)["total_imported"] == 0
    assert len(sync.inbox(USER_A)) == 2


def test_transport_request_moves_to_important_folder_and_emits_messenger_event():
    mailbox, _, sync = build_mail_stack()
    sync.sync_all(USER_A)
    outbox = IntegrationOutbox()
    collector = MailCollectorAgent(mailbox, integration_outbox=outbox)
    result = collector.process_message(USER_A, f"mail-2-{USER_A}")
    assert result["smart_folder"] == "important_requests"
    assert result["importance"] == "high"
    assert result["classification"] == "transport_request"
    event = outbox.list_for_user(USER_A)[0]
    assert event["event_type"] == "transport_request_received"
    assert "messenger" in event["destinations"]


def test_parts_invoice_moves_to_procurement_and_creates_fleet_document_candidate():
    mailbox, _, sync = build_mail_stack()
    sync.sync_all(USER_A)
    queue = FleetDocumentQueue()
    collector = MailCollectorAgent(mailbox, fleet_document_queue=queue)
    result = collector.process_message(USER_A, f"mail-1-{USER_A}")
    assert result["smart_folder"] == "procurement"
    assert result["classification"] == "parts_invoice_candidate"
    pending = queue.list_pending(USER_A)
    assert len(pending) == 1
    assert pending[0]["filename"] == "invoice.pdf"
    assert pending[0]["status"] == "pending_assignment"


def test_generic_pdf_does_not_become_invoice_only_because_of_extension():
    mailbox, _, _ = build_mail_stack()
    mailbox.ingest(USER_A, [{"email_id": "mail-3", "account_id": "work", "provider_message_id": "provider-3", "thread_id": "thread-3", "sender": "partner@example.com", "recipients": ["work@example.com"], "subject": "Документы", "received_at": "2026-09-08T12:00:00+03:00", "body_text": "Во вложении презентация", "attachments": [{"attachment_id": "att-3", "filename": "presentation.pdf", "mime_type": "application/pdf"}]}])
    result = mailbox.classify_and_route(USER_A, "mail-3")
    assert result["classification"] != "parts_invoice_candidate"


def test_app_shell_exposes_same_business_modules_on_mac_and_iphone():
    registry = AppShellRegistry()
    mac = registry.build_client_manifest("mac")
    iphone = registry.build_client_manifest("iphone")
    assert [x["module_id"] for x in mac["navigation"]] == [x["module_id"] for x in iphone["navigation"]]
    assert mac["backend_contract"] == iphone["backend_contract"] == "shared"


def test_push_policy_marks_important_request_high_priority():
    event = PushEventPolicy().from_mail({"email_id": "mail-2", "classification": "transport_request", "importance": "high", "attention_reason": "Получена заявка", "subject": "Заявка на перевозку", "sender": "client@example.com"})
    assert event is not None
    assert event.priority == "high"
