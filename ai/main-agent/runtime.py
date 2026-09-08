from connectors.http_fleet_backend import HttpFleetBackend
from ecosystem.expense_bridge import ExpenseBridge
from finance.invoices import InvoiceWorkflow
from main_agent import build_main_agent
from parts.catalogs import PartsCatalogRegistry


class MainAgentRuntime:
    """Production assembly for cross-module Main Agent capabilities.

    Fleet access is service-to-service. Finance invoice classification and parts
    catalog policy are orchestrated here without direct database access.
    """

    def __init__(self):
        self.agent = build_main_agent(HttpFleetBackend())
        self.invoices = InvoiceWorkflow()
        self.parts_catalogs = PartsCatalogRegistry()
        self.expense_bridge = ExpenseBridge()

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


def build_runtime():
    return MainAgentRuntime()


def build_runtime_agent():
    """Backward-compatible helper returning the conversational agent only."""
    return build_runtime().agent
