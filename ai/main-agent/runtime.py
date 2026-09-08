from agents.delegation import DelegationEngine
from agents.registry import AgentRegistry
from app_shell.navigation import AppShellRegistry
from connectors.http_fleet_backend import HttpFleetBackend
from ecosystem.expense_bridge import ExpenseBridge
from email.mail_collector_agent import MailCollectorAgent
from email.providers import MailProviderRegistry
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
        self.invoices = InvoiceWorkflow()
        self.parts_catalogs = PartsCatalogRegistry()
        self.expense_bridge = ExpenseBridge()
        self.agent_registry = AgentRegistry()
        self.delegation = DelegationEngine(self.agent_registry)
        self.mail_collector = MailCollectorAgent()
        self.mail_providers = MailProviderRegistry()
        self.app_shell = AppShellRegistry()

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
        return self.mail_collector.inbox(unread_only=unread_only)

    def process_mail(self, email_id: str):
        return self.mail_collector.process_message(email_id)

    def register_mail_provider(self, backend):
        self.mail_providers.register(backend)

    def list_mail_provider_accounts(self):
        return self.mail_providers.list_accounts()

    def client_manifest(self, device: str):
        """Return the shared application navigation contract for macOS/iPhone."""
        return self.app_shell.build_client_manifest(device)


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    """Backward-compatible helper returning the conversational agent only."""
    return build_runtime().agent
