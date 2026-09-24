from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ClientContext:
    user_id: str
    device_id: str
    platform: str
    app_version: str


class UnifiedClientApi:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def bootstrap(self, context: ClientContext) -> Dict[str, Any]:
        mail_state = self.runtime.mail_connection_state(context.user_id)
        inbox = self.runtime.mail_sync.inbox(context.user_id)
        folders = {}
        for row in inbox:
            folders[row.get("smart_folder", "other")] = folders.get(row.get("smart_folder", "other"), 0) + 1
        return {
            "client": asdict(context),
            "manifest": self.runtime.client_manifest(context.platform),
            "mail": {
                "accounts": mail_state["accounts"],
                "connections": mail_state["connections"],
                "unread_count": len(self.runtime.mail_sync.inbox(context.user_id, unread_only=True)),
                "important_count": len([x for x in inbox if x.get("importance") == "high"]),
                "folders": folders,
            },
            "agents": self.runtime.list_specialized_agents(),
        }

    def get_mailbox(self, user_id: str, *, account_ids: Optional[Iterable[str]] = None, unread_only: bool = False, classification: Optional[str] = None, routed_to: Optional[str] = None, search: Optional[str] = None, smart_folder: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.runtime.mail_sync.inbox(user_id, account_ids=account_ids, unread_only=unread_only, classification=classification, routed_to=routed_to, search=search, smart_folder=smart_folder)

    def get_mail_message(self, user_id: str, email_id: str) -> Dict[str, Any]:
        return self.runtime.mail_collector.mailbox.get_message(user_id, email_id)

    def process_mail_message(self, user_id: str, email_id: str, *, organization_id: str | None = None) -> Dict[str, Any]:
        return self.runtime.process_mail(user_id, email_id, organization_id=organization_id)

    def refresh_mail(self, user_id: str, *, organization_id: str | None = None) -> Dict[str, Any]:
        return self.runtime.sync_mail(user_id, organization_id=organization_id)

    def begin_mail_authorization(self, *, user_id: str, provider: str, redirect_uri: str, state: str) -> str:
        return self.runtime.begin_mail_authorization(user_id=user_id, provider=provider, redirect_uri=redirect_uri, state=state)

    def get_integration_events(self, user_id: str) -> List[Dict[str, Any]]:
        return self.runtime.integration_events(user_id)

    def get_fleet_document_candidates(self, organization_id: str) -> List[Dict[str, Any]]:
        return self.runtime.fleet_document_candidates(organization_id)


@dataclass(frozen=True)
class PushEvent:
    event_id: str
    event_type: str
    title: str
    body: str
    route: str
    entity_id: Optional[str] = None
    priority: str = "normal"


class PushEventPolicy:
    IMPORTANT_MAIL_CLASSES = {"transport_request", "parts_invoice_candidate", "financial_document", "client_request", "supplier_offer_or_procurement", "payment_or_finance_notice"}

    def from_mail(self, message: Dict[str, Any]) -> Optional[PushEvent]:
        classification = message.get("classification")
        if classification not in self.IMPORTANT_MAIL_CLASSES and message.get("importance") != "high":
            return None
        return PushEvent(event_id=f"mail:{message['email_id']}", event_type="mail_attention", title=message.get("subject") or "Новое письмо", body=message.get("attention_reason") or message.get("sender") or "Входящая почта", route=f"/mail/{message['email_id']}", entity_id=message["email_id"], priority="high" if message.get("importance") == "high" else "normal")
