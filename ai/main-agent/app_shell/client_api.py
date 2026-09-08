from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ClientContext:
    user_id: str
    device_id: str
    platform: str  # mac | iphone
    app_version: str


class UnifiedClientApi:
    """Provider-neutral application facade shared by Mac and iPhone clients."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def bootstrap(self, context: ClientContext) -> Dict[str, Any]:
        mail_state = self.runtime.mail_connection_state()
        return {
            "client": asdict(context),
            "manifest": self.runtime.client_manifest(context.platform),
            "mail": {
                "accounts": mail_state["accounts"],
                "connections": mail_state["connections"],
                "unread_count": len(self.runtime.mail_sync.inbox(unread_only=True)),
            },
            "agents": self.runtime.list_specialized_agents(),
        }

    def get_mailbox(
        self,
        *,
        account_ids: Optional[Iterable[str]] = None,
        unread_only: bool = False,
        classification: Optional[str] = None,
        routed_to: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.runtime.mail_sync.inbox(
            account_ids=account_ids,
            unread_only=unread_only,
            classification=classification,
            routed_to=routed_to,
            search=search,
        )

    def get_mail_message(self, email_id: str) -> Dict[str, Any]:
        return self.runtime.mail_collector.mailbox.get_message(email_id)

    def process_mail_message(self, email_id: str) -> Dict[str, Any]:
        return self.runtime.process_mail(email_id)

    def refresh_mail(self) -> Dict[str, Any]:
        return self.runtime.mail_sync.sync_all()

    def begin_mail_authorization(self, *, provider: str, redirect_uri: str, state: str) -> str:
        return self.runtime.begin_mail_authorization(
            provider=provider,
            redirect_uri=redirect_uri,
            state=state,
        )


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
    """Builds device-agnostic events; APNs delivery belongs to infrastructure."""

    IMPORTANT_MAIL_CLASSES = {
        "supplier_invoice_candidate",
        "client_request",
        "supplier_offer_or_procurement",
        "payment_or_finance_notice",
    }

    def from_mail(self, message: Dict[str, Any]) -> Optional[PushEvent]:
        classification = message.get("classification")
        if classification not in self.IMPORTANT_MAIL_CLASSES:
            return None
        return PushEvent(
            event_id=f"mail:{message['email_id']}",
            event_type="mail_attention",
            title=message.get("subject") or "Новое письмо",
            body=message.get("sender") or "Входящая почта",
            route=f"/mail/{message['email_id']}",
            entity_id=message["email_id"],
            priority="high" if classification == "supplier_invoice_candidate" else "normal",
        )
