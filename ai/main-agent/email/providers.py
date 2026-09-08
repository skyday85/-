from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class MailProviderAccount:
    account_id: str
    address: str
    provider: str
    display_name: Optional[str] = None
    auth_mode: str = "oauth"


class MailProviderBackend(Protocol):
    """Provider adapter contract for the unified mailbox.

    Provider credentials and refresh tokens belong to the secure integration
    layer. They are never passed into the Main Agent or stored in messages.
    """

    provider: str

    def list_accounts(self) -> Iterable[MailProviderAccount]: ...

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
    def __init__(self) -> None:
        self._providers: Dict[str, MailProviderBackend] = {}

    def register(self, backend: MailProviderBackend) -> None:
        if backend.provider in self._providers:
            raise ValueError(f"Mail provider already registered: {backend.provider}")
        self._providers[backend.provider] = backend

    def get(self, provider: str) -> MailProviderBackend:
        return self._providers[provider]

    def list_providers(self) -> List[str]:
        return sorted(self._providers)

    def list_accounts(self) -> List[MailProviderAccount]:
        accounts: List[MailProviderAccount] = []
        for backend in self._providers.values():
            accounts.extend(backend.list_accounts())
        return accounts
