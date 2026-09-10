from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class FleetDocumentCandidate:
    candidate_id: str
    user_id: str
    source_email_id: str
    attachment_id: str
    filename: str
    document_type: str
    suggested_vehicle_id: Optional[str] = None
    suggested_purchase_id: Optional[str] = None
    suggested_repair_id: Optional[str] = None
    status: str = "pending_assignment"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FleetDocumentQueue:
    """Staging area before a mail attachment becomes a fleet document.

    A candidate may later be assigned to a vehicle/purchase/repair or dismissed.
    The queue intentionally does not write directly to the fleet database.
    """

    def __init__(self) -> None:
        self._items: Dict[str, FleetDocumentCandidate] = {}

    def add_invoice_candidate(self, *, user_id: str, source_email_id: str, attachment_id: str, filename: str, suggested_vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        item = FleetDocumentCandidate(candidate_id=str(uuid4()), user_id=user_id, source_email_id=source_email_id, attachment_id=attachment_id, filename=filename, document_type="parts_invoice", suggested_vehicle_id=suggested_vehicle_id)
        self._items[item.candidate_id] = item
        return asdict(item)

    def list_pending(self, user_id: str) -> List[Dict[str, Any]]:
        return [asdict(x) for x in self._items.values() if x.user_id == user_id and x.status == "pending_assignment"]

    def assign(self, user_id: str, candidate_id: str, *, vehicle_id: Optional[str] = None, purchase_id: Optional[str] = None, repair_id: Optional[str] = None) -> Dict[str, Any]:
        item = self._items[candidate_id]
        if item.user_id != user_id:
            raise KeyError(candidate_id)
        item.suggested_vehicle_id = vehicle_id or item.suggested_vehicle_id
        item.suggested_purchase_id = purchase_id
        item.suggested_repair_id = repair_id
        item.status = "ready_for_fleet_upload"
        return asdict(item)

    def dismiss(self, user_id: str, candidate_id: str) -> Dict[str, Any]:
        item = self._items[candidate_id]
        if item.user_id != user_id:
            raise KeyError(candidate_id)
        item.status = "dismissed"
        return asdict(item)
