from agents.delegation import DelegationEngine
from agents.registry import AgentRegistry
from app_shell.client_api import UnifiedClientApi
from app_shell.mail_accounts import MailAccountsViewModel
from app_shell.navigation import AppShellRegistry
from connectors.http_fleet_backend import HttpFleetBackend
from ecosystem.expense_bridge import ExpenseBridge
from mail_contour.mail_collector_agent import MailCollectorAgent
from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter
from mail_contour.providers import MailProviderRegistry
from mail_contour.sync_service import UnifiedMailSyncService
from finance.banking import BankingModule
from finance.invoices import InvoiceWorkflow
from main_agent import build_main_agent
from parts.catalogs import PartsCatalogRegistry


class MainAgentRuntime:
    """Production assembly for the organization-level Main Agent.

    The Main Agent coordinates fleet, finance, parts, unified mail, shared client
    navigation and specialized agents. Source applications retain ownership of
    their data; no direct database access is granted to the Main Agent or its
    child agents.
    """

    def __init__(self):
        self.agent = build_main_agent(HttpFleetBackend())
        self.banking = BankingModule()
        self.invoices = InvoiceWorkflow()
        self.parts_catalogs = PartsCatalogRegistry()
        self.expense_bridge = ExpenseBridge()
        self.agent_registry = AgentRegistry()
        self.delegation = DelegationEngine(self.agent_registry)
        self.mail_collector = MailCollectorAgent()
        self.mail_providers = MailProviderRegistry()
        self.mail_sync = UnifiedMailSyncService(
            self.mail_collector.mailbox,
            self.mail_providers,
        )
        self.app_shell = AppShellRegistry()
        self.client_api = UnifiedClientApi(self)
        self.mail_accounts_view = MailAccountsViewModel(self)

    def build_parts_search_plan(self, *, brand: str, query: str,
                                model: str | None = None,
                                vin: str | None = None):
        return self.parts_catalogs.build_search_plan(
            brand=brand,
            model=model,
            vin=vin,
            query=query,
        )

    def recognize_invoice(self, payload):
        return self.invoices.normalize_recognition(payload)

    def build_invoice_postings(self, invoice):
        plan = self.invoices.build_posting_plan(invoice)
        return self.expense_bridge.build_parts_invoice_postings(plan)

    def import_bank_transactions(self, rows):
        return self.banking.import_transactions(rows)

    def list_bank_transactions(self):
        return self.banking.get_bank_transactions()

    def propose_bank_classification(self, transaction_id: str):
        return self.banking.classify_bank_transaction(transaction_id)

    def confirm_bank_classification(self, transaction_id: str, **changes):
        return self.banking.confirm_classification(transaction_id, **changes)

    def finance_review_queue(self):
        return self.banking.get_needs_review()

    def list_specialized_agents(self):
        return self.agent_registry.list_agents()

    def delegate_task(self, *, agent_id: str, capability: str,
                      instruction: str, context=None):
        return self.delegation.delegate(
            agent_id=agent_id,
            capability=capability,
            instruction=instruction,
            context=context,
        )

    def complete_delegated_task(self, delegation_id: str, result):
        return self.delegation.complete(delegation_id, result)

    def add_mail_account(self, *, account_id: str, address: str, provider: str,
                         display_name: str | None = None):
        return self.mail_collector.add_account(
            account_id=account_id,
            address=address,
            provider=provider,
            display_name=display_name,
        )

    def ingest_mail(self, messages):
        return self.mail_collector.ingest_messages(messages)

    def unified_inbox(self, *, unread_only: bool = False):
        return self.mail_sync.inbox(unread_only=unread_only)

    def process_mail(self, email_id: str):
        return self.mail_collector.process_message(email_id)

    def register_mail_provider(self, backend):
        self.mail_providers.register(backend)
        return self.mail_sync.refresh_accounts()

    def register_standard_mail_providers(self, gateway):
        """Register Gmail and Outlook over one secure OAuth gateway."""
        self.mail_providers.register(GmailProviderAdapter(gateway))
        self.mail_providers.register(OutlookProviderAdapter(gateway))
        return self.mail_sync.refresh_accounts()

    def begin_mail_authorization(self, *, provider: str, redirect_uri: str, state: str):
        backend = self.mail_providers.get(provider)
        return backend.build_authorization_url(redirect_uri=redirect_uri, state=state)

    def complete_mail_authorization(self, *, provider: str, code: str,
                                    redirect_uri: str, state: str):
        backend = self.mail_providers.get(provider)
        account = backend.complete_authorization(
            code=code,
            redirect_uri=redirect_uri,
            state=state,
        )
        self.mail_sync.refresh_accounts()
        return account

    def mail_connection_state(self):
        return self.mail_sync.state()

    def mail_accounts_overview(self):
        return self.mail_accounts_view.overview()

    def sync_mail(self):
        return self.mail_sync.sync_all()

    def list_mail_provider_accounts(self):
        return self.mail_providers.list_accounts()

    def client_manifest(self, device: str):
        """Return the shared application navigation contract for Mac/iPhone."""
        return self.app_shell.build_client_manifest(device)


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    """Backward-compatible helper returning the conversational agent only."""
    return build_runtime().agent
