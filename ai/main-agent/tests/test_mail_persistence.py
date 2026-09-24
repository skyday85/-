from pathlib import Path

from integrations.events import IntegrationOutbox
from integrations.fleet_documents import FleetDocumentQueue
from mail_contour.persistence import MailPersistence
from mail_contour.unified_mailbox import UnifiedMailbox


def test_mail_messages_survive_runtime_restart(tmp_path: Path):
    db = MailPersistence(str(tmp_path / "mail.sqlite3"))
    mailbox = UnifiedMailbox(db)
    mailbox.register_account(__import__("mail_contour.unified_mailbox", fromlist=["MailAccount"]).MailAccount(
        account_id="work", address="work@example.com", provider="fake", owner_user_id="u1"
    ))
    mailbox.ingest("u1", [{
        "account_id": "work", "provider_message_id": "p1",
        "email_id": "m1", "thread_id": "t1", "sender": "client@example.com",
        "recipients": ["work@example.com"], "subject": "Заявка на перевозку",
        "received_at": "2026-09-22T12:00:00+03:00", "body_text": "Нужна перевозка",
    }])
    mailbox.classify_and_route("u1", "m1")

    restarted = UnifiedMailbox(MailPersistence(str(tmp_path / "mail.sqlite3")))
    row = restarted.get_message("u1", "m1")
    assert row["classification"] == "transport_request"
    assert row["smart_folder"] == "important_requests"
    assert row["importance"] == "high"


def test_integration_outbox_survives_restart(tmp_path: Path):
    path = str(tmp_path / "mail.sqlite3")
    first = IntegrationOutbox(MailPersistence(path))
    event = first.publish(
        user_id="u1", event_type="transport_request_received",
        source="unified_mail", source_id="m1", title="Заявка",
        payload={"email_id": "m1"}, destinations=("messenger",), priority="high"
    )
    second = IntegrationOutbox(MailPersistence(path))
    assert second.get(event["event_id"])["delivery_status"] == "pending"


def test_fleet_document_candidate_survives_restart(tmp_path: Path):
    path = str(tmp_path / "mail.sqlite3")
    first = FleetDocumentQueue(MailPersistence(path))
    item = first.add_invoice_candidate(
        organization_id="org1", user_id="u1", source_email_id="m1",
        attachment_id="a1", filename="parts-invoice.pdf", mime_type="application/pdf"
    )
    second = FleetDocumentQueue(MailPersistence(path))
    assert second.list_pending("u1")[0]["candidate_id"] == item["candidate_id"]


def test_document_dismissal_persists_and_enforces_owner(tmp_path: Path):
    path = str(tmp_path / "mail.sqlite3")
    queue = FleetDocumentQueue(MailPersistence(path))
    candidate = queue.add_invoice_candidate(
        organization_id="org1", user_id="u1", source_email_id="m2",
        attachment_id="a2", filename="invoice.pdf"
    )
    import pytest
    with pytest.raises(KeyError):
        queue.dismiss("u2", candidate["candidate_id"])
    queue.dismiss("u1", candidate["candidate_id"])
    restarted = FleetDocumentQueue(MailPersistence(path))
    assert restarted.list_pending("u1") == []
    assert restarted._items[candidate["candidate_id"]].status == "dismissed"


def test_integration_event_retry_is_persisted(tmp_path: Path):
    path = str(tmp_path / "mail.sqlite3")
    queue = IntegrationOutbox(MailPersistence(path))
    event = queue.publish(
        user_id="u1", event_type="transport_request_received",
        source="unified_mail", source_id="m3", title="Заявка",
        payload={}, destinations=("messenger",)
    )
    queue.mark_attempt(event["event_id"], delivered=False)
    restarted = IntegrationOutbox(MailPersistence(path))
    assert restarted.get(event["event_id"])["delivery_attempts"] == 1
    assert len(restarted.pending(destination="messenger")) == 1
