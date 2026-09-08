from typing import Any, Dict, List


class ExpenseBridge:
    """Builds auditable cross-module postings without merging module ownership.

    Finance owns the financial entry. Fleet owns vehicle cost/history. The Main
    Agent only orchestrates and correlates them by stable source identifiers.
    """

    def build_parts_invoice_postings(self, posting_plan: Dict[str, Any]) -> Dict[str, Any]:
        if not posting_plan.get("ready"):
            return {
                "ready": False,
                "reason": "invoice_lines_require_user_confirmation",
                "pending_line_indexes": posting_plan.get("pending_line_indexes", []),
                "operations": [],
            }

        operations: List[Dict[str, Any]] = []
        invoice_id = posting_plan.get("invoice_id")

        for entry in posting_plan.get("financial_entries", []):
            operations.append({
                "target": "finance",
                "operation": "record_expense",
                "idempotency_key": f"invoice:{invoice_id}:finance:{len(operations)}",
                "payload": {
                    **entry,
                    "source_type": "supplier_invoice",
                    "source_id": invoice_id,
                },
            })

        for entry in posting_plan.get("fleet_cost_entries", []):
            operations.append({
                "target": "fleet",
                "operation": "record_vehicle_cost",
                "idempotency_key": f"invoice:{invoice_id}:fleet:{entry.get('vehicle_id')}:{len(operations)}",
                "payload": {
                    **entry,
                    "source_type": "supplier_invoice",
                    "source_id": invoice_id,
                },
            })

        return {
            "ready": True,
            "invoice_id": invoice_id,
            "operations": operations,
            "invariants": [
                "financial source remains the invoice",
                "fleet receives only vehicle-attributed costs",
                "the same invoice is not counted twice in consolidated analytics",
                "all operations must be idempotent and audited by target modules",
            ],
        }
