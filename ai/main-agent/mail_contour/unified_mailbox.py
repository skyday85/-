from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class MailAccount:
    account_id: str
    address: str
    provider: str
    owner_user_id: str
    display_name: Optional[str] = None
    active: bool = True


@dataclass
class MailAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: Optional[int] = None
    content_ref: Optional[str] = None


@dataclass
class UnifiedMailMessage:
    email_id: str
    user_id: str
    account_id: str
    provider_message_id: str
    thread_id: Optional[str]
    sender: str
    recipients: List[str]
    subject: str
    received_at: str
    body_text: str = ""
    body_html: Optional[str] = None
    attachments: List[MailAttachment] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    unread: bool = True
    direction: str = "incoming"
    classification: Optional[str] = None
    route_to: Optional[str] = None
    review_status: Optional[str] = None
    smart_folder: str = "other"
    importance: str = "normal"
    attention_reason: Optional[str] = None
    integration_event_type: Optional[str] = None
    business_case_id: Optional[str] = None
    customer_id: Optional[str] = None
    counterparty_id: Optional[str] = None
    invoice_id: Optional[str] = None


class UnifiedMailbox:
    """Provider-neutral multi-user mailbox with virtual business folders."""

    def __init__(self) -> None:
        self.accounts: Dict[Tuple[str, str], MailAccount] = {}
        self.messages: Dict[Tuple[str, str], UnifiedMailMessage] = {}
        self._provider_keys: Dict[Tuple[str, str, str, str], str] = {}

    def register_account(self, account: MailAccount) -> Dict[str, Any]:
        self.accounts[(account.owner_user_id, account.account_id)] = account
        return asdict(account)

    def ingest(self, user_id: str, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        imported: List[Dict[str, Any]] = []
        for row in rows:
            account_id = str(row["account_id"])
            account_key = (user_id, account_id)
            if account_key not in self.accounts:
                raise KeyError(f"Unknown mail account for user: {account_id}")
            account = self.accounts[account_key]
            provider_message_id = str(row["provider_message_id"])
            provider_key = (user_id, account.provider, account_id, provider_message_id)
            if provider_key in self._provider_keys:
                continue
            email_id = str(row.get("email_id") or f"{account.provider}:{account_id}:{provider_message_id}")
            message_key = (user_id, email_id)
            if message_key in self.messages:
                continue
            attachments = [MailAttachment(attachment_id=str(x["attachment_id"]), filename=str(x.get("filename", "attachment")), mime_type=str(x.get("mime_type", "application/octet-stream")), size_bytes=x.get("size_bytes"), content_ref=x.get("content_ref")) for x in row.get("attachments", [])]
            message = UnifiedMailMessage(email_id=email_id, user_id=user_id, account_id=account_id, provider_message_id=provider_message_id, thread_id=row.get("thread_id"), sender=str(row.get("sender", "")), recipients=[str(x) for x in row.get("recipients", [])], subject=str(row.get("subject", "")), received_at=str(row["received_at"]), body_text=str(row.get("body_text", "")), body_html=row.get("body_html"), attachments=attachments, labels=[str(x) for x in row.get("labels", [])], unread=bool(row.get("unread", True)), direction=str(row.get("direction", "incoming")))
            self.messages[message_key] = message
            self._provider_keys[provider_key] = email_id
            imported.append(self._serialize(message))
        return imported

    def unified_inbox(self, user_id: str, *, unread_only: bool = False, smart_folder: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = [x for (owner, _), x in self.messages.items() if owner == user_id]
        if unread_only:
            rows = [x for x in rows if x.unread]
        if smart_folder:
            rows = [x for x in rows if x.smart_folder == smart_folder]
        rows.sort(key=lambda x: (x.importance == "high", x.received_at), reverse=True)
        return [self._serialize(x) for x in rows]

    def classify_and_route(self, user_id: str, email_id: str) -> Dict[str, Any]:
        message = self.messages[(user_id, email_id)]
        text = f"{message.subject} {message.body_text}".lower()
        filenames = " ".join(a.filename.lower() for a in message.attachments)
        combined = f"{text} {filenames}"
        invoice_terms = ["счет", "счёт", "invoice", "упд", "счет-фактура", "счёт-фактура"]
        procurement_terms = ["запчаст", "артикул", "детал", "коммерческое предложение", "кп ", "quotation"]
        transport_terms = ["заявка", "перевозк", "груз", "маршрут", "погрузк", "выгрузк", "ставка", "request for quote"]
        contract_terms = ["договор", "contract", "соглашение"]
        finance_terms = ["оплата", "платеж", "платёж", "payment", "банк", "зачисление", "списание", "акт", "усн", "налог"]
        marketing_terms = ["рассылка", "реклама", "campaign", "лид", "lead", "unsubscribe"]
        spam_terms = ["casino", "lottery", "вы выиграли", "крипто доход", "easy money"]

        if any(x in combined for x in spam_terms):
            message.classification, message.route_to, message.review_status = "spam_or_noise", "mail_collector", "classified"
            message.smart_folder = "other"
        elif any(x in combined for x in transport_terms):
            message.classification, message.route_to, message.review_status = "transport_request", "mail_collector>sales_agent", "needs_review"
            message.smart_folder, message.importance = "important_requests", "high"
            message.attention_reason = "Получена заявка/запрос на перевозку"
            message.integration_event_type = "transport_request_received"
        elif any(x in combined for x in procurement_terms) and any(x in combined for x in invoice_terms):
            message.classification, message.route_to, message.review_status = "parts_invoice_candidate", "mail_collector>buyer_agent", "needs_review"
            message.smart_folder, message.importance = "procurement", "high"
            message.attention_reason = "Счёт/документ по запчастям"
            message.integration_event_type = "parts_invoice_received"
        elif any(x in combined for x in procurement_terms):
            message.classification, message.route_to, message.review_status = "supplier_offer_or_procurement", "mail_collector>buyer_agent", "needs_review"
            message.smart_folder = "procurement"
        elif any(x in combined for x in invoice_terms) or any(x in combined for x in finance_terms):
            message.classification, message.route_to, message.review_status = "financial_document", "mail_collector>finance_agent", "needs_review"
            message.smart_folder = "finance"
            if any(x in combined for x in invoice_terms):
                message.importance = "high"
                message.attention_reason = "Получен финансовый документ/счёт"
        elif any(x in combined for x in contract_terms):
            message.classification, message.route_to, message.review_status = "contract_or_document", "mail_collector>main_agent", "needs_review"
            message.smart_folder = "documents"
        elif any(x in combined for x in marketing_terms):
            message.classification, message.route_to, message.review_status = "marketing", "mail_collector>marketing_agent", "needs_review"
            message.smart_folder = "marketing"
        else:
            message.classification, message.route_to, message.review_status = "general_operational", "mail_collector>main_agent", "needs_review"
            message.smart_folder = "other"
        return self._serialize(message)

    def get_message(self, user_id: str, email_id: str) -> Dict[str, Any]:
        return self._serialize(self.messages[(user_id, email_id)])

    @staticmethod
    def _serialize(message: UnifiedMailMessage) -> Dict[str, Any]:
        data = asdict(message)
        data["source_system"] = "unified_mail"
        data["source_record_id"] = message.provider_message_id
        return data
