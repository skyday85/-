from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class InvoiceLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    sku: Optional[str] = None
    category_proposal: Optional[str] = None
    vehicle_id: Optional[str] = None
    confidence: float = 0.0
    review_status: str = "needs_review"


@dataclass
class RecognizedInvoice:
    invoice_id: str
    supplier_name: str
    number: str
    issued_at: str
    total: Decimal
    lines: List[InvoiceLine]
    source_document_id: Optional[str] = None


class InvoiceWorkflow:
    """Cross-module invoice workflow for the Main Agent.

    Recognition output is treated as a proposal. Financial category and vehicle
    allocation are never finalized automatically until the user confirms them.
    """

    PART_KEYWORDS = (
        "запчаст", "детал", "фильтр", "масло", "подшип", "ремень", "колод",
        "диск", "форсунк", "стартер", "генератор", "радиатор", "амортиз",
    )

    def normalize_recognition(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        required = ["invoice_id", "supplier_name", "number", "issued_at", "total", "lines"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"Missing invoice recognition fields: {', '.join(missing)}")

        lines: List[InvoiceLine] = []
        for raw in payload["lines"]:
            line = InvoiceLine(
                description=str(raw.get("description", "")).strip(),
                quantity=Decimal(str(raw.get("quantity", 1))),
                unit_price=Decimal(str(raw.get("unit_price", raw.get("amount", 0)))),
                amount=Decimal(str(raw.get("amount", 0))),
                sku=(str(raw["sku"]).strip() if raw.get("sku") else None),
            )
            self._propose_line_classification(line)
            lines.append(line)

        invoice = RecognizedInvoice(
            invoice_id=str(payload["invoice_id"]),
            supplier_name=str(payload["supplier_name"]).strip(),
            number=str(payload["number"]).strip(),
            issued_at=str(payload["issued_at"]),
            total=Decimal(str(payload["total"])),
            lines=lines,
            source_document_id=payload.get("source_document_id"),
        )
        return self._serialize(invoice)

    def confirm_line(self, invoice: Dict[str, Any], line_index: int, *, category: str,
                     vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        lines = invoice.get("lines", [])
        if line_index < 0 or line_index >= len(lines):
            raise IndexError("Invoice line index out of range")
        line = lines[line_index]
        line["category_proposal"] = category
        line["vehicle_id"] = vehicle_id
        line["review_status"] = "confirmed"
        line["confidence"] = 1.0
        return invoice

    def build_posting_plan(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        lines = invoice.get("lines", [])
        pending = [i for i, line in enumerate(lines) if line.get("review_status") != "confirmed"]
        return {
            "invoice_id": invoice.get("invoice_id"),
            "ready": not pending,
            "pending_line_indexes": pending,
            "financial_entries": [
                {
                    "category": line.get("category_proposal"),
                    "amount": line.get("amount"),
                    "supplier_name": invoice.get("supplier_name"),
                    "invoice_number": invoice.get("number"),
                }
                for line in lines if line.get("review_status") == "confirmed"
            ],
            "fleet_cost_entries": [
                {
                    "vehicle_id": line.get("vehicle_id"),
                    "category": line.get("category_proposal"),
                    "amount": line.get("amount"),
                    "description": line.get("description"),
                    "sku": line.get("sku"),
                    "invoice_id": invoice.get("invoice_id"),
                }
                for line in lines
                if line.get("review_status") == "confirmed" and line.get("vehicle_id")
            ],
        }

    def _propose_line_classification(self, line: InvoiceLine) -> None:
        text = line.description.lower()
        matched = [keyword for keyword in self.PART_KEYWORDS if keyword in text]
        if matched:
            line.category_proposal = "Запчасти"
            line.confidence = min(0.95, 0.65 + len(matched) * 0.08)
        else:
            line.category_proposal = None
            line.confidence = 0.25
        line.review_status = "needs_review"

    @staticmethod
    def _serialize(invoice: RecognizedInvoice) -> Dict[str, Any]:
        data = asdict(invoice)
        data["total"] = str(invoice.total)
        for line in data["lines"]:
            line["quantity"] = str(line["quantity"])
            line["unit_price"] = str(line["unit_price"])
            line["amount"] = str(line["amount"])
        return data
