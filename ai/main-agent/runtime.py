from agents.delegation import DelegationEngine
from agents.registry import AgentRegistry
from app_shell.client_api import UnifiedClientApi
from app_shell.mail_accounts import MailAccountsViewModel
from app_shell.navigation import AppShellRegistry
from connectors.http_fleet_backend import HttpFleetBackend
from ecosystem.expense_bridge import ExpenseBridge
from finance.banking import BankingModule
from finance.invoices import InvoiceWorkflow
from integrations.events import IntegrationOutbox
from integrations.fleet_documents import FleetDocumentQueue
from mail_contour.mail_collector_agent import MailCollectorAgent
from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter
from mail_contour.providers import MailProviderRegistry
from mail_contour.sync_service import UnifiedMailSyncService
from main_agent import build_main_agent
from parts.catalogs import PartsCatalogRegistry


class MainAgentRuntime:
    def __init__(self):
        self.agent = build_main_agent(HttpFleetBackend())
        self.banking = BankingModule()
        self.invoices = InvoiceWorkflow()
        self.parts_catalogs = PartsCatalogRegistry()
        self.expense_bridge = ExpenseBridge()
        self.agent_registry = AgentRegistry()
        self.delegation = DelegationEngine(self.agent_registry)
        self.integration_outbox = IntegrationOutbox()
        self.fleet_document_queue = FleetDocumentQueue()
        self.mail_collector = MailCollectorAgent(integration_outbox=self.integration_outbox, fleet_document_queue=self.fleet_document_queue)
        self.mail_providers = MailProviderRegistry()
        self.mail_sync = UnifiedMailSyncService(self.mail_collector.mailbox, self.mail_providers)
        self.app_shell = AppShellRegistry()
        self.client_api = UnifiedClientApi(self)
        self.mail_accounts_view = MailAccountsViewModel(self)

    def build_parts_search_plan(self, *, brand: str, query: str, model: str | None = None, vin: str | None = None):
        return self.parts_catalogs.build_search_plan(brand=brand, model=model, vin=vin, query=query)

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

    def delegate_task(self, *, agent_id: str, capability: str, instruction: str, context=None):
        return self.delegation.delegate(agent_id=agent_id, capability=capability, instruction=instruction, context=context)

    def complete_delegated_task(self, delegation_id: str, result):
        return self.delegation.complete(delegation_id, result)

    def add_mail_account(self, *, user_id: str, account_id: str, address: str, provider: str, display_name: str | None = None):
        return self.mail_collector.add_account(user_id=user_id, account_id=account_id, address=address, provider=provider, display_name=display_name)

    def ingest_mail(self, user_id: str, messages):
        return self.mail_collector.ingest_messages(user_id, messages)

    def unified_inbox(self, user_id: str, *, unread_only: bool = False, smart_folder: str | None = None):
        return self.mail_sync.inbox(user_id, unread_only=unread_only, smart_folder=smart_folder)

    def process_mail(self, user_id: str, email_id: str):
        return self.mail_collector.process_message(user_id, email_id)

    def register_mail_provider(self, backend):
        self.mail_providers.register(backend)

    def register_standard_mail_providers(self, gateway):
        self.mail_providers.register(GmailProviderAdapter(gateway))
        self.mail_providers.register(OutlookProviderAdapter(gateway))

    def refresh_mail_accounts(self, user_id: str):
        return self.mail_sync.refresh_accounts(user_id)

    def begin_mail_authorization(self, *, user_id: str, provider: str, redirect_uri: str, state: str):
        return self.mail_providers.get(provider).build_authorization_url(user_id=user_id, redirect_uri=redirect_uri, state=state)

    def complete_mail_authorization(self, *, user_id: str, provider: str, code: str, redirect_uri: str, state: str):
        account = self.mail_providers.get(provider).complete_authorization(user_id=user_id, code=code, redirect_uri=redirect_uri, state=state)
        self.mail_sync.refresh_accounts(user_id)
        return account

    def mail_connection_state(self, user_id: str):
        return self.mail_sync.state(user_id)

    def mail_accounts_overview(self, user_id: str):
        return self.mail_accounts_view.overview(user_id)

    def sync_mail(self, user_id: str):
        return self.mail_sync.sync_all(user_id)

    def integration_events(self, user_id: str):
        return self.integration_outbox.list_for_user(user_id)

    def fleet_document_candidates(self, user_id: str):
        return self.fleet_document_queue.list_pending(user_id)

    def client_manifest(self, device: str):
        return self.app_shell.build_client_manifest(device)


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    return build_runtime().agent
