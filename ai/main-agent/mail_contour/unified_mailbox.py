from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class MailAccount:
    account_id: str
    address: str
    provider: str
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
    business_case_id: Optional[str] = None
    customer_id: Optional[str] = None
    counterparty_id: Optional[str] = None
    invoice_id: Optional[str] = None


class UnifiedMailbox:
    """Provider-neutral mailbox used by the Mail Collector agent."""

    def __init__(self) -> None:
        self.accounts: Dict[str, MailAccount] = {}
        self.messages: Dict[str, UnifiedMailMessage] = {}
        self._provider_keys: Dict[Tuple[str, str, str], str] = {}

    def register_account(self, account: MailAccount) -> Dict[str, Any]:
        self.accounts[account.account_id] = account
        return asdict(account)

    def ingest(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        imported: List[Dict[str, Any]] = []
        for row in rows:
            account_id = str(row["account_id"])
            if account_id not in self.accounts:
                raise KeyError(f"Unknown mail account: {account_id}")

            account = self.accounts[account_id]
            provider_message_id = str(row["provider_message_id"])
            provider_key = (account.provider, account_id, provider_message_id)
            if provider_key in self._provider_keys:
                continue

            email_id = str(row.get("email_id") or f"{account.provider}:{account_id}:{provider_message_id}")
            if email_id in self.messages:
                continue

            attachments = [
                MailAttachment(
                    attachment_id=str(x["attachment_id"]),
                    filename=str(x.get("filename", "attachment")),
                    mime_type=str(x.get("mime_type", "application/octet-stream")),
                    size_bytes=x.get("size_bytes"),
                    content_ref=x.get("content_ref"),
                )
                for x in row.get("attachments", [])
            ]

            message = UnifiedMailMessage(
                email_id=email_id,
                account_id=account_id,
                provider_message_id=provider_message_id,
                thread_id=row.get("thread_id"),
                sender=str(row.get("sender", "")),
                recipients=[str(x) for x in row.get("recipients", [])],
                subject=str(row.get("subject", "")),
                received_at=str(row["received_at"]),
                body_text=str(row.get("body_text", "")),
                body_html=row.get("body_html"),
                attachments=attachments,
                labels=[str(x) for x in row.get("labels", [])],
                unread=bool(row.get("unread", True)),
                direction=str(row.get("direction", "incoming")),
            )
            self.messages[email_id] = message
            self._provider_keys[provider_key] = email_id
            imported.append(self._serialize(message))
        return imported

    def unified_inbox(self, *, unread_only: bool = False) -> List[Dict[str, Any]]:
        rows = list(self.messages.values())
        if unread_only:
            rows = [x for x in rows if x.unread]
        rows.sort(key=lambda x: x.received_at, reverse=True)
        return [self._serialize(x) for x in rows]

    def classify_and_route(self, email_id: str) -> Dict[str, Any]:
        message = self.messages[email_id]
        text = f"{message.subject} {message.body_text}".lower()
        filenames = " ".join(a.filename.lower() for a in message.attachments)
        combined = f"{text} {filenames}"

        invoice_terms = ["счет", "счёт", "invoice", "упд", "счет-фактура", "счёт-фактура"]
        procurement_terms = ["запчаст", "артикул", "детал", "коммерческое предложение", "кп ", "quotation"]
        sales_terms = ["заявка", "заказ", "клиент", "ставка", "перевозк", "доставка", "request for quote"]
        contract_terms = ["договор", "contract", "соглашение"]
        finance_notice_terms = ["оплата", "платеж", "платёж", "payment", "банк", "зачисление", "списание"]
        marketing_terms = ["рассылка", "реклама", "campaign", "лид", "lead", "unsubscribe"]
        spam_terms = ["casino", "lottery", "вы выиграли", "крипто доход", "easy money"]

        if any(x in combined for x in spam_terms):
            message.classification = "spam_or_noise"
            message.route_to = "mail_collector"
            message.review_status = "classified"
        elif any(x in combined for x in invoice_terms):
            message.classification = "supplier_invoice_candidate"
            message.route_to = "mail_collector>finance_agent"
            message.review_status = "needs_review"
        elif any(x in combined for x in procurement_terms):
            message.classification = "supplier_offer_or_procurement"
            message.route_to = "mail_collector>buyer_agent"
            message.review_status = "needs_review"
        elif any(x in combined for x in contract_terms):
            message.classification = "contract_or_document"
            message.route_to = "mail_collector>main_agent"
            message.review_status = "needs_review"
        elif any(x in combined for x in finance_notice_terms):
            message.classification = "payment_or_finance_notice"
            message.route_to = "mail_collector>finance_agent"
            message.review_status = "needs_review"
        elif any(x in combined for x in sales_terms):
            message.classification = "client_request"
            message.route_to = "mail_collector>sales_agent"
            message.review_status = "needs_review"
        elif any(x in combined for x in marketing_terms):
            message.classification = "marketing"
            message.route_to = "mail_collector>marketing_agent"
            message.review_status = "needs_review"
        else:
            message.classification = "general_operational"
            message.route_to = "mail_collector>main_agent"
            message.review_status = "needs_review"

        return self._serialize(message)

    def get_message(self, email_id: str) -> Dict[str, Any]:
        return self._serialize(self.messages[email_id])

    @staticmethod
    def _serialize(message: UnifiedMailMessage) -> Dict[str, Any]:
        data = asdict(message)
        data["source_system"] = "unified_mail"
        data["source_record_id"] = message.provider_message_id
        return data
