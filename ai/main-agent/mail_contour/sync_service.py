from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from mail_contour.providers import MailProviderRegistry
from mail_contour.unified_mailbox import MailAccount, UnifiedMailbox


@dataclass
class MailSyncState:
    account_id: str
    provider: str
    cursor: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None


class UnifiedMailSyncService:
    """Synchronizes all connected provider accounts into one inbox."""

    def __init__(self, mailbox: UnifiedMailbox, providers: MailProviderRegistry) -> None:
        self.mailbox = mailbox
        self.providers = providers
        self._sync_state: Dict[str, MailSyncState] = {}

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
            self._sync_state.setdefault(
                account.account_id,
                MailSyncState(account_id=account.account_id, provider=account.provider),
            )
            registered.append(result)
        return registered

    def sync_account(self, account_id: str, *, limit: int = 100) -> Dict[str, Any]:
        account = self.mailbox.accounts[account_id]
        backend = self.providers.get(account.provider)
        state = self._sync_state.setdefault(
            account_id,
            MailSyncState(account_id=account_id, provider=account.provider),
        )
        try:
            page = backend.fetch_messages(account_id, cursor=state.cursor, limit=limit)
            imported = self.mailbox.ingest(page.get("messages", []))
            state.cursor = page.get("next_cursor") or state.cursor
            state.last_sync_at = datetime.now(timezone.utc).isoformat()
            state.last_error = None
            return {
                "account_id": account_id,
                "provider": account.provider,
                "imported": len(imported),
                "cursor": state.cursor,
                "last_sync_at": state.last_sync_at,
            }
        except Exception as exc:
            state.last_sync_at = datetime.now(timezone.utc).isoformat()
            state.last_error = str(exc)
            raise

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
                    [str(row.get("sender", "")), str(row.get("subject", "")), str(row.get("body_text", ""))]
                ).lower()
                if query not in haystack:
                    continue
            result.append(row)
        return result

    def state(self) -> Dict[str, Any]:
        return {
            "accounts": [asdict(x) for x in self.mailbox.accounts.values()],
            "providers": self.providers.list_providers(),
            "connections": [asdict(x) for x in self.providers.connection_states()],
            "sync": {key: asdict(value) for key, value in self._sync_state.items()},
            "message_count": len(self.mailbox.messages),
        }
