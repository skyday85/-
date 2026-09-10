from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class MailAccountAction:
    action: str
    provider: str
    account_id: Optional[str] = None
    title: str = ""


class MailAccountsViewModel:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def overview(self, user_id: str) -> Dict[str, Any]:
        state = self.runtime.mail_connection_state(user_id)
        accounts = []
        for item in state.get("connections", []):
            accounts.append({"provider": item["provider"], "account_id": item["account_id"], "connected": item["connected"], "reauth_required": item.get("reauth_required", False), "scopes": item.get("scopes", []), "sync": state.get("sync", {}).get(item["account_id"], {})})
        return {"accounts": accounts, "available_providers": ["gmail", "outlook"], "actions": [asdict(MailAccountAction("connect", "gmail", title="Подключить Gmail")), asdict(MailAccountAction("connect", "outlook", title="Подключить Outlook"))], "credentials_policy": "oauth_only"}

    def begin_connect(self, *, user_id: str, provider: str, redirect_uri: str, state: str) -> Dict[str, str]:
        return {"provider": provider, "authorization_url": self.runtime.begin_mail_authorization(user_id=user_id, provider=provider, redirect_uri=redirect_uri, state=state)}
