"""Unified organization mail contour.

Provider credentials live in the integration layer. The Main Agent works only
with normalized mail records and delegated actions.
"""

from .mail_collector_agent import MailCollectorAgent
from .providers import MailProviderAccount, MailProviderBackend, MailProviderRegistry
from .sync_service import UnifiedMailSyncService
from .unified_mailbox import MailAccount, MailAttachment, UnifiedMailMessage, UnifiedMailbox

__all__ = [
    "MailAccount",
    "MailAttachment",
    "MailCollectorAgent",
    "MailProviderAccount",
    "MailProviderBackend",
    "MailProviderRegistry",
    "UnifiedMailMessage",
    "UnifiedMailbox",
    "UnifiedMailSyncService",
]
