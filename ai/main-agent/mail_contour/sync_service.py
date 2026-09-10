from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mail_contour.providers import MailProviderRegistry
from mail_contour.unified_mailbox import MailAccount, UnifiedMailbox


@dataclass
class MailSyncState:
    user_id: str
    account_id: str
    provider: str
    cursor: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None


class UnifiedMailSyncService:
    """Provider synchronization only; business processing happens in runtime."""

    def __init__(self, mailbox: UnifiedMailbox, providers: MailProviderRegistry) -> None:
        self.mailbox = mailbox
        self.providers = providers
        self._sync_state: Dict[Tuple[str, str], MailSyncState] = {}

    def refresh_accounts(self, user_id: str) -> List[Dict[str, Any]]:
        registered: List[Dict[str, Any]] = []
        for account in self.providers.list_accounts(user_id):
            result = self.mailbox.register_account(MailAccount(account_id=account.account_id, address=account.address, provider=account.provider, owner_user_id=user_id, display_name=account.display_name))
            self._sync_state.setdefault((user_id, account.account_id), MailSyncState(user_id=user_id, account_id=account.account_id, provider=account.provider))
            registered.append(result)
        return registered

    def sync_account(self, user_id: str, account_id: str, *, limit: int = 100) -> Dict[str, Any]:
        account = self.mailbox.accounts[(user_id, account_id)]
        backend = self.providers.get(account.provider)
        state = self._sync_state.setdefault((user_id, account_id), MailSyncState(user_id=user_id, account_id=account_id, provider=account.provider))
        try:
            page = backend.fetch_messages(user_id, account_id, cursor=state.cursor, limit=limit)
            imported_rows = self.mailbox.ingest(user_id, page.get("messages", []))
            imported_ids = [str(row["email_id"]) for row in imported_rows]
            state.cursor = page.get("next_cursor") or state.cursor
            state.last_sync_at = datetime.now(timezone.utc).isoformat()
            state.last_error = None
            return {
                "account_id": account_id,
                "provider": account.provider,
                "imported": len(imported_ids),
                "imported_email_ids": imported_ids,
                "cursor": state.cursor,
                "last_sync_at": state.last_sync_at,
            }
        except Exception:
            state.last_sync_at = datetime.now(timezone.utc).isoformat()
            state.last_error = "Mail synchronization failed"
            raise

    def sync_all(self, user_id: str, *, limit_per_account: int = 100) -> Dict[str, Any]:
        results = []
        imported_email_ids: List[str] = []
        for (owner, account_id), account in list(self.mailbox.accounts.items()):
            if owner == user_id and account.active:
                result = self.sync_account(user_id, account_id, limit=limit_per_account)
                results.append(result)
                imported_email_ids.extend(result["imported_email_ids"])
        return {
            "accounts": results,
            "total_imported": len(imported_email_ids),
            "imported_email_ids": imported_email_ids,
        }

    def inbox(self, user_id: str, *, account_ids: Optional[Iterable[str]] = None, unread_only: bool = False, classification: Optional[str] = None, routed_to: Optional[str] = None, search: Optional[str] = None, smart_folder: Optional[str] = None) -> List[Dict[str, Any]]:
        allowed = set(account_ids or [])
        query = (search or "").strip().lower()
        rows = self.mailbox.unified_inbox(user_id, unread_only=unread_only, smart_folder=smart_folder)
        result: List[Dict[str, Any]] = []
        for row in rows:
            if allowed and row["account_id"] not in allowed:
                continue
            if classification and row.get("classification") != classification:
                continue
            if routed_to and row.get("route_to") != routed_to:
                continue
            if query:
                haystack = " ".join([str(row.get("sender", "")), str(row.get("subject", "")), str(row.get("body_text", ""))]).lower()
                if query not in haystack:
                    continue
            result.append(row)
        return result

    def state(self, user_id: str) -> Dict[str, Any]:
        return {
            "accounts": [asdict(x) for (owner, _), x in self.mailbox.accounts.items() if owner == user_id],
            "providers": self.providers.list_providers(),
            "connections": [asdict(x) for x in self.providers.connection_states(user_id)],
            "sync": {account_id: asdict(value) for (owner, account_id), value in self._sync_state.items() if owner == user_id},
            "message_count": len([1 for owner, _ in self.mailbox.messages if owner == user_id]),
        }
