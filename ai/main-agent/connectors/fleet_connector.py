from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


class FleetBackend(Protocol):
    """Контракт backend-приложения «Управление автопарком».

    Реальная реализация позже будет обращаться к API приложения или сервисному слою.
    Главный агент не получает прямой доступ к БД.
    """

    def list_vehicles(self) -> List[Dict[str, Any]]: ...
    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]: ...
    def get_vehicle_history(self, vehicle_id: str) -> List[Dict[str, Any]]: ...
    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]: ...
    def create_repair(self, vehicle_id: str, problem: str, mileage: Optional[int] = None,
                      notes: Optional[str] = None) -> Dict[str, Any]: ...
    def get_attention_items(self) -> List[Dict[str, Any]]: ...


@dataclass
class FleetConnector:
    backend: FleetBackend
    source_system: str = "fleet_management"

    def get_fleet(self) -> List[Dict[str, Any]]:
        return [self._wrap("vehicle", item) for item in self.backend.list_vehicles()]

    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        item = self.backend.get_vehicle(vehicle_id)
        return self._wrap("vehicle", item) if item else None

    def get_vehicle_history(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._wrap("vehicle_history_event", item)
                for item in self.backend.get_vehicle_history(vehicle_id)]

    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._wrap("repair", item)
                for item in self.backend.get_repairs(vehicle_id)]

    def create_repair(self, vehicle_id: str, problem: str,
                      mileage: Optional[int] = None,
                      notes: Optional[str] = None) -> Dict[str, Any]:
        item = self.backend.create_repair(vehicle_id, problem, mileage, notes)
        return self._wrap("repair", item)

    def get_attention_items(self) -> List[Dict[str, Any]]:
        return [self._wrap("attention_item", item)
                for item in self.backend.get_attention_items()]

    def _wrap(self, record_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        source_record_id = (
            payload.get("vehicle_id")
            or payload.get("repair_id")
            or payload.get("event_id")
            or payload.get("attention_id")
            or payload.get("id")
        )
        return {
            "source_system": self.source_system,
            "source_record_id": source_record_id,
            "record_type": record_type,
            "payload": payload,
        }
