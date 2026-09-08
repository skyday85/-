from __future__ import annotations

from typing import Any, Dict, Iterable, List

from email.unified_mailbox import MailAccount, UnifiedMailbox


class MailCollectorAgent:
    """Specialized agent for all organization mailboxes in one operational view."""

    agent_id = "mail_collector_agent"

    def __init__(self, mailbox: UnifiedMailbox | None = None) -> None:
        self.mailbox = mailbox or UnifiedMailbox()

    def add_account(self, *, account_id: str, address: str, provider: str,
                    display_name: str | None = None) -> Dict[str, Any]:
        return self.mailbox.register_account(MailAccount(
            account_id=account_id,
            address=address,
            provider=provider,
            display_name=display_name,
        ))

    def ingest_messages(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.mailbox.ingest(messages)

    def inbox(self, *, unread_only: bool = False) -> List[Dict[str, Any]]:
        return self.mailbox.unified_inbox(unread_only=unread_only)

    def process_message(self, email_id: str) -> Dict[str, Any]:
        """Classify an email and choose the next specialized-agent route.

        This does not make final accounting decisions, send replies or mutate
        downstream application records. Those actions require delegated tools.
        """
        return self.mailbox.classify_and_route(email_id)

    def process_unread(self) -> List[Dict[str, Any]]:
        return [self.process_message(x["email_id"]) for x in self.inbox(unread_only=True)]
