from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class MailProviderAccount:
    account_id: str
    address: str
    provider: str
    owner_user_id: str
    display_name: Optional[str] = None
    auth_mode: str = "oauth"


@dataclass(frozen=True)
class MailProviderConnectionState:
    provider: str
    account_id: str
    owner_user_id: str
    connected: bool
    scopes: tuple[str, ...] = ()
    reauth_required: bool = False


class MailProviderBackend(Protocol):
    provider: str

    def list_accounts(self, user_id: str) -> Iterable[MailProviderAccount]: ...
    def connection_state(self, user_id: str, account_id: str) -> MailProviderConnectionState: ...
    def build_authorization_url(self, *, user_id: str, redirect_uri: str, state: str) -> str: ...
    def complete_authorization(self, *, user_id: str, code: str, redirect_uri: str, state: str) -> MailProviderAccount: ...
    def fetch_messages(self, user_id: str, account_id: str, *, cursor: Optional[str] = None, limit: int = 100) -> Dict: ...
    def fetch_attachment(self, user_id: str, account_id: str, provider_message_id: str, attachment_id: str) -> Dict: ...


class MailProviderRegistry:
    SUPPORTED_PROVIDERS = {"gmail", "outlook"}

    def __init__(self) -> None:
        self._providers: Dict[str, MailProviderBackend] = {}

    def register(self, backend: MailProviderBackend) -> None:
        provider = backend.provider.lower()
        if provider in self._providers:
            raise ValueError(f"Mail provider already registered: {provider}")
        self._providers[provider] = backend

    def get(self, provider: str) -> MailProviderBackend:
        return self._providers[provider.lower()]

    def list_providers(self) -> List[str]:
        return sorted(self._providers)

    def list_accounts(self, user_id: str) -> List[MailProviderAccount]:
        accounts: List[MailProviderAccount] = []
        for backend in self._providers.values():
            accounts.extend(backend.list_accounts(user_id))
        return accounts

    def connection_states(self, user_id: str) -> List[MailProviderConnectionState]:
        states: List[MailProviderConnectionState] = []
        for backend in self._providers.values():
            for account in backend.list_accounts(user_id):
                states.append(backend.connection_state(user_id, account.account_id))
        return states
