from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from mail_contour.providers import MailProviderAccount, MailProviderConnectionState


class OAuthMailGateway(Protocol):
    def list_accounts(self, provider: str, user_id: str) -> Iterable[Dict[str, Any]]: ...
    def connection_state(self, provider: str, user_id: str, account_id: str) -> Dict[str, Any]: ...
    def build_authorization_url(self, provider: str, *, user_id: str, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str: ...
    def complete_authorization(self, provider: str, *, user_id: str, code: str, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> Dict[str, Any]: ...
    def fetch_messages(self, provider: str, user_id: str, account_id: str, *, cursor: Optional[str], limit: int) -> Dict[str, Any]: ...
    def fetch_attachment(self, provider: str, user_id: str, account_id: str, provider_message_id: str, attachment_id: str) -> Dict[str, Any]: ...


@dataclass
class OAuthMailProviderAdapter:
    gateway: OAuthMailGateway
    provider: str
    scopes: tuple[str, ...]

    def list_accounts(self, user_id: str) -> Iterable[MailProviderAccount]:
        for raw in self.gateway.list_accounts(self.provider, user_id):
            yield self._account(raw, user_id)

    def connection_state(self, user_id: str, account_id: str) -> MailProviderConnectionState:
        raw = self.gateway.connection_state(self.provider, user_id, account_id)
        return MailProviderConnectionState(provider=self.provider, account_id=account_id, owner_user_id=user_id, connected=bool(raw.get("connected", False)), scopes=tuple(raw.get("scopes", self.scopes)), reauth_required=bool(raw.get("reauth_required", False)))

    def build_authorization_url(self, *, user_id: str, redirect_uri: str, state: str) -> str:
        return self.gateway.build_authorization_url(self.provider, user_id=user_id, redirect_uri=redirect_uri, state=state, scopes=self.scopes)

    def complete_authorization(self, *, user_id: str, code: str, redirect_uri: str, state: str) -> MailProviderAccount:
        raw = self.gateway.complete_authorization(self.provider, user_id=user_id, code=code, redirect_uri=redirect_uri, state=state, scopes=self.scopes)
        return self._account(raw, user_id)

    def fetch_messages(self, user_id: str, account_id: str, *, cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        page = self.gateway.fetch_messages(self.provider, user_id, account_id, cursor=cursor, limit=limit)
        return {"messages": [self._normalize_message(user_id, account_id, row) for row in page.get("messages", [])], "next_cursor": page.get("next_cursor")}

    def fetch_attachment(self, user_id: str, account_id: str, provider_message_id: str, attachment_id: str) -> Dict[str, Any]:
        return self.gateway.fetch_attachment(self.provider, user_id, account_id, provider_message_id, attachment_id)

    def _account(self, raw: Dict[str, Any], user_id: str) -> MailProviderAccount:
        return MailProviderAccount(account_id=str(raw["account_id"]), address=str(raw["address"]), provider=self.provider, owner_user_id=user_id, display_name=raw.get("display_name"), auth_mode="oauth")

    def _normalize_message(self, user_id: str, account_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        provider_message_id = str(raw["provider_message_id"])
        return {"email_id": str(raw.get("email_id") or f"{self.provider}:{account_id}:{provider_message_id}"), "user_id": user_id, "account_id": account_id, "provider_message_id": provider_message_id, "thread_id": raw.get("thread_id"), "sender": str(raw.get("sender", "")), "recipients": [str(x) for x in raw.get("recipients", [])], "subject": str(raw.get("subject", "")), "received_at": str(raw["received_at"]), "body_text": str(raw.get("body_text", "")), "body_html": raw.get("body_html"), "attachments": list(raw.get("attachments", [])), "labels": [str(x) for x in raw.get("labels", [])], "unread": bool(raw.get("unread", True)), "direction": str(raw.get("direction", "incoming"))}


class GmailProviderAdapter(OAuthMailProviderAdapter):
    def __init__(self, gateway: OAuthMailGateway) -> None:
        super().__init__(gateway=gateway, provider="gmail", scopes=("openid", "email", "https://www.googleapis.com/auth/gmail.readonly"))


class OutlookProviderAdapter(OAuthMailProviderAdapter):
    def __init__(self, gateway: OAuthMailGateway) -> None:
        super().__init__(gateway=gateway, provider="outlook", scopes=("openid", "email", "offline_access", "Mail.Read"))
