import os

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
from integrations.http_dispatcher import HttpIntegrationDispatcher
from mail_contour.mail_collector_agent import MailCollectorAgent
from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter
from mail_contour.providers import MailProviderRegistry
from mail_contour.sync_service import UnifiedMailSyncService
from main_agent import build_main_agent
from parts.catalogs import PartsCatalogRegistry


class MainAgentRuntime:
    def __init__(self):
        self.fleet_backend = HttpFleetBackend()
        self.agent = build_main_agent(self.fleet_backend)
        self.banking = BankingModule()
        self.invoices = InvoiceWorkflow()
        self.parts_catalogs = PartsCatalogRegistry()
        self.expense_bridge = ExpenseBridge()
        self.agent_registry = AgentRegistry()
        self.delegation = DelegationEngine(self.agent_registry)
        self.integration_outbox = IntegrationOutbox()
        self.integration_dispatcher = self._build_integration_dispatcher()
        self.fleet_document_queue = FleetDocumentQueue()
        self.mail_collector = MailCollectorAgent(integration_outbox=self.integration_outbox, fleet_document_queue=self.fleet_document_queue)
        self.mail_providers = MailProviderRegistry()
        self.mail_sync = UnifiedMailSyncService(self.mail_collector.mailbox, self.mail_providers)
        self.app_shell = AppShellRegistry()
        self.client_api = UnifiedClientApi(self)
        self.mail_accounts_view = MailAccountsViewModel(self)

    @staticmethod
    def _build_integration_dispatcher():
        base_url = os.getenv("INTEGRATION_GATEWAY_BASE_URL", "").strip()
        token = os.getenv("INTEGRATION_GATEWAY_SERVICE_TOKEN", "").strip()
        if not base_url or not token:
            return None
        return HttpIntegrationDispatcher(base_url, token)

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

    def process_mail(self, user_id: str, email_id: str, *, organization_id: str | None = None):
        message = self.mail_collector.process_message(user_id, email_id, organization_id=organization_id)
        integration_delivery = []
        if self.integration_dispatcher is not None:
            for event in self.integration_outbox.pending(destination="messenger"):
                if event["user_id"] != user_id or event["source_id"] != email_id:
                    continue
                try:
                    response = self.integration_dispatcher.dispatch(event)
                    self.integration_outbox.mark_attempt(event["event_id"], delivered=True)
                    integration_delivery.append({"event_id": event["event_id"], "status": "delivered", "response": response})
                except Exception:
                    self.integration_outbox.mark_attempt(event["event_id"], delivered=False)
                    integration_delivery.append({"event_id": event["event_id"], "status": "failed"})

        fleet_delivery = []
        if organization_id and message.get("classification") == "parts_invoice_candidate":
            for candidate in self.fleet_document_queue.list_pending(user_id):
                if candidate["source_email_id"] != email_id or candidate["organization_id"] != organization_id:
                    continue
                try:
                    persisted = self.fleet_backend.create_document_candidate(
                        organization_id=organization_id,
                        source_user_id=user_id,
                        source_email_id=email_id,
                        source_attachment_id=candidate["attachment_id"],
                        original_name=candidate["filename"],
                        mime_type=candidate.get("mime_type"),
                        size_bytes=candidate.get("size_bytes"),
                        document_type=candidate.get("document_type", "parts_invoice"),
                        metadata={"sender": message.get("sender"), "subject": message.get("subject"), "classification": message.get("classification"), "source_account_id": message.get("account_id")},
                    )
                    fleet_delivery.append({"status": "forwarded_to_fleet", "candidate": persisted})
                except Exception:
                    self.integration_outbox.publish(user_id=user_id, event_type="fleet_document_delivery_failed", source="unified_mail", source_id=email_id, title=candidate["filename"], payload={"organization_id": organization_id, "candidate_id": candidate["candidate_id"]}, destinations=("main_agent",), priority="high")
                    fleet_delivery.append({"status": "delivery_failed", "candidate_id": candidate["candidate_id"]})
        if integration_delivery:
            message["integration_delivery"] = integration_delivery
        if fleet_delivery:
            message["fleet_document_delivery"] = fleet_delivery
        return message

    def sync_mail(self, user_id: str, *, organization_id: str | None = None):
        """Sync provider mail and immediately classify/route every newly imported message."""
        self.refresh_mail_accounts(user_id)
        sync_result = self.mail_sync.sync_all(user_id)
        processed = []
        failed = []
        for email_id in sync_result.get("imported_email_ids", []):
            try:
                processed.append(self.process_mail(user_id, email_id, organization_id=organization_id))
            except Exception:
                failed.append(email_id)
        return {
            **sync_result,
            "processed": len(processed),
            "processing_failed": len(failed),
            "processing_failed_email_ids": failed,
        }

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

    def integration_events(self, user_id: str):
        return self.integration_outbox.list_for_user(user_id)

    def fleet_document_candidates(self, organization_id: str):
        return self.fleet_backend.list_document_candidates(organization_id)

    def assign_fleet_document_candidate(self, *, organization_id: str, candidate_id: str, vehicle_id: str, purchase_request_id: str | None = None, repair_id: str | None = None):
        return self.fleet_backend.assign_document_candidate(organization_id=organization_id, candidate_id=candidate_id, vehicle_id=vehicle_id, purchase_request_id=purchase_request_id, repair_id=repair_id)

    def dismiss_fleet_document_candidate(self, *, organization_id: str, candidate_id: str):
        return self.fleet_backend.dismiss_document_candidate(organization_id=organization_id, candidate_id=candidate_id)

    def client_manifest(self, device: str):
        return self.app_shell.build_client_manifest(device)


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    return build_runtime().agent
