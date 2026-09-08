from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional

from email.providers import MailProviderRegistry
from email.unified_mailbox import MailAccount, UnifiedMailbox


class UnifiedMailSyncService:
    """Synchronizes provider mailboxes into one provider-neutral inbox.

    Provider credentials remain inside provider adapters. The Main Agent and
    clients receive only normalized message/account data.
    """

    def __init__(self, mailbox: UnifiedMailbox, providers: MailProviderRegistry) -> None:
        self.mailbox = mailbox
        self.providers = providers
        self._cursors: Dict[str, Optional[str]] = {}

    def refresh_accounts(self) -> List[Dict[str, Any]]:
        registered: List[Dict[str, Any]] = []
        for account in self.providers.list_accounts():
            result = self.mailbox.register_account(
                MailAccount(
                    account_id=account.account_id,
                    address=account.address,
                    provider=account.provider,
                    display_name=account.display_name,
                )
            )
            registered.append(result)
        return registered

    def sync_account(self, account_id: str, *, limit: int = 100) -> Dict[str, Any]:
        account = self.mailbox.accounts[account_id]
        backend = self.providers.get(account.provider)
        page = backend.fetch_messages(
            account_id,
            cursor=self._cursors.get(account_id),
            limit=limit,
        )
        messages = page.get("messages", [])
        imported = self.mailbox.ingest(messages)
        self._cursors[account_id] = page.get("next_cursor")
        return {
            "account_id": account_id,
            "provider": account.provider,
            "imported": len(imported),
            "next_cursor": self._cursors[account_id],
        }

    def sync_all(self, *, limit_per_account: int = 100) -> Dict[str, Any]:
        results = []
        for account_id, account in self.mailbox.accounts.items():
            if account.active:
                results.append(self.sync_account(account_id, limit=limit_per_account))
        return {"accounts": results, "total_imported": sum(x["imported"] for x in results)}

    def inbox(
        self,
        *,
        account_ids: Optional[Iterable[str]] = None,
        unread_only: bool = False,
        classification: Optional[str] = None,
        routed_to: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        allowed = set(account_ids or [])
        query = (search or "").strip().lower()
        rows = self.mailbox.unified_inbox(unread_only=unread_only)
        result: List[Dict[str, Any]] = []
        for row in rows:
            if allowed and row["account_id"] not in allowed:
                continue
            if classification and row.get("classification") != classification:
                continue
            if routed_to and row.get("route_to") != routed_to:
                continue
            if query:
                haystack = " ".join(
                    [
                        str(row.get("sender", "")),
                        str(row.get("subject", "")),
                        str(row.get("body_text", "")),
                    ]
                ).lower()
                if query not in haystack:
                    continue
            result.append(row)
        return result

    def state(self) -> Dict[str, Any]:
        return {
            "accounts": [asdict(x) for x in self.mailbox.accounts.values()],
            "providers": self.providers.list_providers(),
            "cursors": dict(self._cursors),
            "message_count": len(self.mailbox.messages),
        }
