from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


@dataclass
class FleetDocumentCandidate:
    candidate_id: str
    organization_id: str
    user_id: str
    source_email_id: str
    attachment_id: str
    filename: str
    document_type: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    suggested_vehicle_id: Optional[str] = None
    suggested_purchase_id: Optional[str] = None
    suggested_repair_id: Optional[str] = None
    status: str = "pending_assignment"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FleetDocumentQueue:
    """User-originated, organization-scoped staging before fleet import."""

    def __init__(self) -> None:
        self._items: Dict[str, FleetDocumentCandidate] = {}
        self._source_index: Dict[Tuple[str, str, str, str], str] = {}

    def add_invoice_candidate(self, *, organization_id: str, user_id: str, source_email_id: str, attachment_id: str, filename: str, mime_type: Optional[str] = None, size_bytes: Optional[int] = None, suggested_vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        source_key = (organization_id, user_id, source_email_id, attachment_id)
        existing_id = self._source_index.get(source_key)
        if existing_id:
            return asdict(self._items[existing_id])
        item = FleetDocumentCandidate(candidate_id=str(uuid4()), organization_id=organization_id, user_id=user_id, source_email_id=source_email_id, attachment_id=attachment_id, filename=filename, document_type="parts_invoice", mime_type=mime_type, size_bytes=size_bytes, suggested_vehicle_id=suggested_vehicle_id)
        self._items[item.candidate_id] = item
        self._source_index[source_key] = item.candidate_id
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
