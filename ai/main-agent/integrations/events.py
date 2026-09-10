from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from uuid import uuid4


@dataclass(frozen=True)
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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IntegrationOutbox:
    def __init__(self) -> None:
        self._events: List[IntegrationEvent] = []

    def publish(self, *, user_id: str, event_type: str, source: str, source_id: str, title: str, payload: Dict[str, Any], destinations: Iterable[str] = (), priority: str = "normal") -> Dict[str, Any]:
        event = IntegrationEvent(event_id=str(uuid4()), user_id=user_id, event_type=event_type, source=source, source_id=source_id, title=title, payload=payload, destinations=tuple(destinations), priority=priority)
        self._events.append(event)
        return asdict(event)

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        return [asdict(x) for x in self._events if x.user_id == user_id]
