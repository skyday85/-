from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


@dataclass
class IntegrationEvent:
    event_id: str
    user_id: str
    event_type: str
    source: str
    source_id: str
    title: str
    payload: Dict[str, Any]
    destinations: tuple[str, ...] = ()
    priority: str = "normal"
    delivery_status: str = "pending"
    delivery_attempts: int = 0
    delivered_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IntegrationOutbox:
    """Idempotent provider-neutral outbox for external application events."""

    def __init__(self) -> None:
        self._events: List[IntegrationEvent] = []
        self._dedupe: Dict[Tuple[str, str, str, str, tuple[str, ...]], str] = {}

    def publish(self, *, user_id: str, event_type: str, source: str, source_id: str, title: str, payload: Dict[str, Any], destinations: Iterable[str] = (), priority: str = "normal") -> Dict[str, Any]:
        destination_tuple = tuple(destinations)
        key = (user_id, event_type, source, source_id, destination_tuple)
        existing_id = self._dedupe.get(key)
        if existing_id:
            return self.get(existing_id)
        event = IntegrationEvent(event_id=str(uuid4()), user_id=user_id, event_type=event_type, source=source, source_id=source_id, title=title, payload=payload, destinations=destination_tuple, priority=priority)
        self._events.append(event)
        self._dedupe[key] = event.event_id
        return asdict(event)

    def get(self, event_id: str) -> Dict[str, Any]:
        for event in self._events:
            if event.event_id == event_id:
                return asdict(event)
        raise KeyError(event_id)

    def mark_attempt(self, event_id: str, *, delivered: bool) -> Dict[str, Any]:
        for event in self._events:
            if event.event_id != event_id:
                continue
            event.delivery_attempts += 1
            event.delivery_status = "delivered" if delivered else "failed"
            event.delivered_at = datetime.now(timezone.utc).isoformat() if delivered else None
            return asdict(event)
        raise KeyError(event_id)

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        return [asdict(x) for x in self._events if x.user_id == user_id]

    def pending(self, *, destination: Optional[str] = None) -> List[Dict[str, Any]]:
        result = [x for x in self._events if x.delivery_status in {"pending", "failed"}]
        if destination:
            result = [x for x in result if destination in x.destinations]
        return [asdict(x) for x in result]
