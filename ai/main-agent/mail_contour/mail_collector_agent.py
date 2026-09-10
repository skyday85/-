from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from mail_contour.unified_mailbox import MailAccount, UnifiedMailbox


class MailCollectorAgent:
    """Specialized agent for user-scoped mailboxes in one operational view."""

    agent_id = "mail_collector_agent"

    def __init__(self, mailbox: UnifiedMailbox | None = None, integration_outbox=None, fleet_document_queue=None) -> None:
        self.mailbox = mailbox or UnifiedMailbox()
        self.integration_outbox = integration_outbox
        self.fleet_document_queue = fleet_document_queue

    def add_account(self, *, user_id: str, account_id: str, address: str, provider: str, display_name: str | None = None) -> Dict[str, Any]:
        return self.mailbox.register_account(MailAccount(account_id=account_id, address=address, provider=provider, owner_user_id=user_id, display_name=display_name))

    def ingest_messages(self, user_id: str, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.mailbox.ingest(user_id, messages)

    def inbox(self, user_id: str, *, unread_only: bool = False, smart_folder: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.mailbox.unified_inbox(user_id, unread_only=unread_only, smart_folder=smart_folder)

    def process_message(self, user_id: str, email_id: str, *, organization_id: Optional[str] = None) -> Dict[str, Any]:
        message = self.mailbox.classify_and_route(user_id, email_id)
        event_type = message.get("integration_event_type")
        if event_type and self.integration_outbox is not None:
            destinations = ("messenger",) if event_type == "transport_request_received" else ("main_agent",)
            self.integration_outbox.publish(
                user_id=user_id,
                event_type=event_type,
                source="unified_mail",
                source_id=email_id,
                title=message.get("subject") or event_type,
                payload={
                    "organization_id": organization_id,
                    "email_id": email_id,
                    "sender": message.get("sender"),
                    "subject": message.get("subject"),
                    "smart_folder": message.get("smart_folder"),
                    "classification": message.get("classification"),
                },
                destinations=destinations,
                priority=message.get("importance", "normal"),
            )

        if organization_id and message.get("classification") == "parts_invoice_candidate" and self.fleet_document_queue is not None:
            for attachment in message.get("attachments", []):
                filename = str(attachment.get("filename", ""))
                mime_type = str(attachment.get("mime_type", ""))
                if filename.lower().endswith((".pdf", ".xml", ".xlsx", ".xls")) or mime_type in {"application/pdf", "application/xml", "text/xml"}:
                    self.fleet_document_queue.add_invoice_candidate(
                        organization_id=organization_id,
                        user_id=user_id,
                        source_email_id=email_id,
                        attachment_id=str(attachment["attachment_id"]),
                        filename=filename or "document",
                        mime_type=mime_type or None,
                        size_bytes=attachment.get("size_bytes"),
                    )
        return message

    def process_unread(self, user_id: str, *, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self.process_message(user_id, x["email_id"], organization_id=organization_id) for x in self.inbox(user_id, unread_only=True)]
