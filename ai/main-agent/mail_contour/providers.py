from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class MailProviderAccount:
    account_id: str
    address: str
    provider: str
    display_name: Optional[str] = None
    auth_mode: str = "oauth"


@dataclass(frozen=True)
class MailProviderConnectionState:
    provider: str
    account_id: str
    connected: bool
    scopes: tuple[str, ...] = ()
    reauth_required: bool = False


class MailProviderBackend(Protocol):
    """Provider adapter contract for Gmail, Outlook and future providers.

    OAuth refresh tokens, client secrets and provider credentials stay inside
    the secure integration layer and are never exposed to agents or clients.
    """

    provider: str

    def list_accounts(self) -> Iterable[MailProviderAccount]: ...

    def connection_state(self, account_id: str) -> MailProviderConnectionState: ...

    def build_authorization_url(self, *, redirect_uri: str, state: str) -> str: ...

    def complete_authorization(self, *, code: str, redirect_uri: str, state: str) -> MailProviderAccount: ...

    def fetch_messages(
        self,
        account_id: str,
        *,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Dict: ...

    def fetch_attachment(
        self,
        account_id: str,
        provider_message_id: str,
        attachment_id: str,
    ) -> Dict: ...


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

    def list_accounts(self) -> List[MailProviderAccount]:
        accounts: List[MailProviderAccount] = []
        for backend in self._providers.values():
            accounts.extend(backend.list_accounts())
        return accounts

    def connection_states(self) -> List[MailProviderConnectionState]:
        states: List[MailProviderConnectionState] = []
        for backend in self._providers.values():
            for account in backend.list_accounts():
                states.append(backend.connection_state(account.account_id))
        return states
