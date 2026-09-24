import base64
import json
import os
from dataclasses import asdict

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
from mail_contour.mail_access import MailAccessDirectory, AccessDenied
from mail_contour.deduplication import collapse_for_view
from mail_contour.processing_dedup import MailProcessingDeduper
from mail_contour.text_routing import MailTextRouter
from mail_contour.mail_collector_agent import MailCollectorAgent
from mail_contour.persistence import MailPersistence
from mail_contour.provider_adapters import GmailProviderAdapter, OutlookProviderAdapter
from mail_contour.providers import MailProviderRegistry
from mail_contour.sync_service import UnifiedMailSyncService
from mail_contour.unified_mailbox import UnifiedMailbox
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
        db_path = os.getenv("MAIL_DATABASE_PATH", "./data/mail_contour.sqlite3")
        self.mail_persistence = MailPersistence(db_path)
        self.mail_directory = MailAccessDirectory(db_path)
        self.mail_processing_deduper = MailProcessingDeduper(db_path)
        bootstrap_org = os.getenv("APP_ORGANIZATION_ID", "").strip()
        bootstrap_user = os.getenv("MAIL_BOOTSTRAP_OWNER_USER_ID", "").strip()
        bootstrap_email = os.getenv("MAIL_BOOTSTRAP_OWNER_EMAIL", "").strip()
        if bootstrap_org and bootstrap_user and bootstrap_email:
            self.mail_directory.bootstrap_owner(bootstrap_org, bootstrap_user, bootstrap_email)
        self.mail_text_router = MailTextRouter(self.mail_directory, self.fetch_mail_attachment)
        self.integration_outbox = IntegrationOutbox(self.mail_persistence)
        self.integration_dispatcher = self._build_integration_dispatcher()
        self.fleet_document_queue = FleetDocumentQueue(self.mail_persistence)
        self.mail_collector = MailCollectorAgent(mailbox=UnifiedMailbox(self.mail_persistence), integration_outbox=self.integration_outbox, fleet_document_queue=self.fleet_document_queue)
        self.mail_providers = MailProviderRegistry()
        self.mail_sync = UnifiedMailSyncService(self.mail_collector.mailbox, self.mail_providers, self.mail_persistence)
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
        if not organization_id:
            return self._perform_mail_processing(user_id, email_id)
        original = self.mail_collector.mailbox.get_message(user_id, email_id)
        claim = self.mail_processing_deduper.claim(organization_id, user_id, original)
        if not claim["claimed"]:
            # Each physical copy retains its own classification; only business
            # side effects (events, documents, forwarding) run once per org.
            classified = self.mail_collector.mailbox.classify_and_route(user_id, email_id)
            return {**classified, "duplicate_suppressed": True,
                    "primary_source": {
                        "owner_user_id": claim["primary_owner"],
                        "email_id": claim["primary_email_id"],
                    }, "primary_processing_status": claim["state"]}
        try:
            result = self._perform_mail_processing(user_id, email_id, organization_id=organization_id)
        except Exception:
            # Do not automatically retry ambiguous external sends/transfers.
            self.mail_processing_deduper.finish(organization_id, claim["processing_key"],
                                                success=False, error="processing_failed")
            raise
        else:
            self.mail_processing_deduper.finish(organization_id, claim["processing_key"],
                                                success=True)
            return {**result, "duplicate_suppressed": False}

    def _perform_mail_processing(self, user_id: str, email_id: str, *,
                                 organization_id: str | None = None):
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
                    attachment = self.fetch_mail_attachment(user_id, email_id, candidate["attachment_id"])
                    persisted = self.fleet_backend.create_document_candidate(
                        organization_id=organization_id,
                        source_user_id=user_id,
                        source_email_id=email_id,
                        source_attachment_id=candidate["attachment_id"],
                        original_name=str(attachment.get("filename") or candidate["filename"]),
                        mime_type=attachment.get("mime_type") or candidate.get("mime_type"),
                        size_bytes=attachment.get("size_bytes") or candidate.get("size_bytes"),
                        document_type=candidate.get("document_type", "parts_invoice"),
                        metadata={"sender": message.get("sender"), "subject": message.get("subject"), "classification": message.get("classification"), "source_account_id": message.get("account_id")},
                        content_bytes=attachment["content_bytes"],
                    )
                    fleet_delivery.append({"status": "forwarded_to_fleet", "candidate": persisted})
                except Exception:
                    self.integration_outbox.publish(user_id=user_id, event_type="fleet_document_delivery_failed", source="unified_mail", source_id=email_id, title=candidate["filename"], payload={"organization_id": organization_id, "candidate_id": candidate["candidate_id"]}, destinations=("main_agent",), priority="high")
                    fleet_delivery.append({"status": "delivery_failed", "candidate_id": candidate["candidate_id"]})
        if integration_delivery:
            message["integration_delivery"] = integration_delivery
        if fleet_delivery:
            message["fleet_document_delivery"] = fleet_delivery
        if organization_id:
            message["text_routing"] = self.process_mail_routing(organization_id, user_id, message)
        return message

    def fetch_mail_attachment(self, user_id: str, email_id: str, attachment_id: str):
        message = self.mail_collector.mailbox.get_message(user_id, email_id)
        account_id = str(message["account_id"])
        provider = self.mail_collector.mailbox.accounts[(user_id, account_id)].provider
        attachment = self.mail_providers.get(provider).fetch_attachment(
            user_id,
            account_id,
            str(message["provider_message_id"]),
            attachment_id,
        )
        encoded = attachment.get("content_base64") or attachment.get("content_base64url") or ""
        if not encoded:
            raise ValueError("mail gateway returned empty attachment")
        try:
            content = base64.b64decode(encoded, validate=False)
        except Exception:
            content = base64.urlsafe_b64decode(str(encoded) + "=" * (-len(str(encoded)) % 4))
        return {**attachment, "content_bytes": content, "size_bytes": attachment.get("size_bytes") or len(content)}

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

    def fleet_vehicles(self, organization_id: str):
        return self.fleet_backend.list_vehicles(organization_id)

    def fleet_document_candidates(self, organization_id: str):
        return self.fleet_backend.list_document_candidates(organization_id)

    def fleet_document_candidate_content(self, organization_id: str, candidate_id: str):
        return self.fleet_backend.get_document_candidate_content(organization_id, candidate_id)

    def fleet_vehicle_work_items(self, organization_id: str, vehicle_id: str):
        return self.fleet_backend.get_vehicle_work_items(organization_id, vehicle_id)

    def assign_fleet_document_candidate(self, *, organization_id: str, candidate_id: str, vehicle_id: str, purchase_request_id: str | None = None, repair_id: str | None = None):
        return self.fleet_backend.assign_document_candidate(organization_id=organization_id, candidate_id=candidate_id, vehicle_id=vehicle_id, purchase_request_id=purchase_request_id, repair_id=repair_id)

    def dismiss_fleet_document_candidate(self, *, organization_id: str, candidate_id: str):
        return self.fleet_backend.dismiss_document_candidate(organization_id=organization_id, candidate_id=candidate_id)

    def client_manifest(self, device: str):
        return self.app_shell.build_client_manifest(device)


    @staticmethod
    def _scoped_mail_id(owner: str, email_id: str) -> str:
        payload = json.dumps([owner, email_id], separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_scoped_mail_id(value: str) -> tuple[str, str]:
        try:
            decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            owner, email_id = json.loads(decoded)
            if not isinstance(owner, str) or not isinstance(email_id, str):
                raise ValueError("Malformed identifier")
            return owner, email_id
        except (ValueError, TypeError, UnicodeError) as exc:
            raise KeyError("Invalid scoped email identifier") from exc

    @staticmethod
    def _source_account_id(owner: str, provider: str, account_id: str) -> str:
        encoded = json.dumps([owner, provider, account_id], separators=(",", ":"))
        return base64.urlsafe_b64encode(encoded.encode("utf-8")).rstrip(b"=").decode("ascii")

    def visible_mailbox(self, org: str, viewer: str, *, account_ids=None,
                        source_id=None, unread_only=False, classification=None,
                        routed_to=None, search=None, smart_folder=None):
        # Start with ONLY active grants belonging to this organization and viewer.
        # Never group against mailbox data the viewer cannot otherwise access.
        grants = self.mail_directory.grants(org, viewer)
        permitted_sources = {
            self._source_account_id(g["owner_user_id"], g["provider"], g["account_id"])
            for g in grants
        }
        if source_id is not None and source_id not in permitted_sources:
            raise AccessDenied("This mailbox has not been assigned to you")
        rows, seen = [], set()
        for grant in grants:
            owner, account_id, provider = (
                grant["owner_user_id"], grant["account_id"], grant["provider"]
            )
            current_source_id = self._source_account_id(owner, provider, account_id)
            key = (owner, provider, account_id)
            if key in seen or (source_id and current_source_id != source_id):
                continue
            if account_ids and account_id not in account_ids:
                continue
            seen.add(key)
            for msg in self.mail_sync.inbox(owner, account_ids=[account_id]):
                rows.append({
                    **msg, "email_id": self._scoped_mail_id(owner, msg["email_id"]),
                    "viewer_user_id": viewer, "source_owner_user_id": owner,
                    "source_account_address": grant["address"], "provider": provider,
                    "source_id": current_source_id,
                })
        # Collapse first; filter on the *logical* message, not on one copy,
        # so account badges and per-view unread counts remain consistent.
        merged = collapse_for_view(rows)
        selected = []
        query = str(search or "").casefold().strip()
        for item in merged:
            if unread_only and not item["unread"]:
                continue
            if classification and classification not in item["group_classifications"]:
                continue
            if routed_to and routed_to not in item["group_routes"]:
                continue
            if smart_folder and smart_folder not in item["group_folders"]:
                continue
            if query and query not in item["group_search_text"]:
                continue
            # Internal merged search text is not a separate user-facing field.
            selected.append({k: v for k, v in item.items() if not k.startswith("group_")})
        return selected

    def visible_mail_message(self, org: str, viewer: str, scoped_email_id: str):
        owner, email_id = self._decode_scoped_mail_id(scoped_email_id)
        original = self.mail_collector.mailbox.get_message(owner, email_id)
        account = self.mail_collector.mailbox.accounts[(owner, original["account_id"])]
        grant = self.mail_directory.assert_grant(org, viewer, owner=owner,
                 provider=account.provider, account_id=original["account_id"])
        return {**original, "email_id": scoped_email_id, "viewer_user_id": viewer,
                "source_owner_user_id": owner, "source_account_address": grant["address"]}

    def visible_process_mail(self, org: str, viewer: str, scoped_email_id: str):
        self.visible_mail_message(org, viewer, scoped_email_id)
        owner, email_id = self._decode_scoped_mail_id(scoped_email_id)
        result = self.process_mail(owner, email_id, organization_id=org)
        return {**result, "email_id": scoped_email_id, "source_owner_user_id": owner}

    def visible_mail_state(self, org: str, viewer: str):
        grants = self.mail_directory.grants(org, viewer)
        connections = []
        for grant in grants:
            try:
                state = self.mail_providers.get(grant["provider"]).connection_state(
                    grant["owner_user_id"], grant["account_id"])
                connections.append({**asdict(state), "address": grant["address"],
                                    "source_owner_user_id": grant["owner_user_id"]})
            except (KeyError, RuntimeError):
                connections.append({"provider": grant["provider"], "account_id": grant["account_id"],
                                    "connected": False, "reauth_required": True,
                                    "source_owner_user_id": grant["owner_user_id"]})
        exposed_grants = [
            {**g, "source_id": self._source_account_id(
                g["owner_user_id"], g["provider"], g["account_id"])}
            for g in grants
        ]
        return {"accounts": exposed_grants, "connections": connections}

    def sync_visible_mail(self, org: str, viewer: str):
        grants = self.mail_directory.grants(org, viewer)
        results, imported, failed, seen = [], [], [], set()
        for grant in grants:
            owner, account_id = grant["owner_user_id"], grant["account_id"]
            if (owner, account_id) in seen:
                continue
            seen.add((owner, account_id))
            try:
                self.refresh_mail_accounts(owner)
                result = self.mail_sync.sync_account(owner, account_id)
                results.append({"owner_user_id": owner, **result})
                for email_id in result["imported_email_ids"]:
                    try:
                        self.process_mail(owner, email_id, organization_id=org)
                        imported.append(self._scoped_mail_id(owner, email_id))
                    except Exception:
                        failed.append(self._scoped_mail_id(owner, email_id))
            except Exception:
                failed.append(f"{owner}:account_sync_failed")
        return {"accounts": results, "total_imported": len(imported),
                "imported_email_ids": imported, "processing_failed_email_ids": failed}

    def process_mail_routing(self, org: str, owner: str, original: dict):
        account = self.mail_collector.mailbox.accounts[(owner, original["account_id"])]
        inspection = self.mail_text_router.inspect(organization_id=org, owner_user_id=owner,
                                                    message=original, provider=account.provider)
        delivered = []
        for entry in inspection["jobs"]:
            job = self.mail_directory.system_job(org, entry["job_id"])
            rule = self.mail_directory.get_rule(job["rule_id"])
            if (rule["mode"] == "auto" and entry["matched_in"] != "unverified_attachment"
                    and job["status"] == "pending_review"):
                try:
                    self._deliver_forward(org, owner, entry["job_id"], automated=True)
                    delivered.append(entry["job_id"])
                except Exception:
                    pass
        return {**inspection, "auto_forwarded_job_ids": delivered}

    def _deliver_forward(self, org: str, actor: str, job_id: str, *, automated: bool = False):
        job = self.mail_directory.claim_job(org, actor, job_id, automated=automated)
        try:
            message = self.mail_collector.mailbox.get_message(job["owner_user_id"], job["email_id"])
            if message["account_id"] != job["account_id"]:
                raise AccessDenied("Forward job account does not match source email")
            result = self.mail_providers.get(job["provider"]).forward_message(
                job["owner_user_id"], job["account_id"], message["provider_message_id"],
                job["destination"])
            self.mail_directory.finish_job(job_id, success=True, provider_result=str(result))
            return {"job_id": job_id, "status": "forwarded", "provider": job["provider"]}
        except Exception:
            self.mail_directory.finish_job(job_id, success=False, error_code="verify_provider_delivery")
            raise

    def approve_forward(self, org: str, actor: str, job_id: str):
        return self._deliver_forward(org, actor, job_id)


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    return build_runtime().agent
