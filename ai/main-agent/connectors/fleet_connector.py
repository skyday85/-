from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


class FleetBackend(Protocol):
    """Контракт backend-приложения «Управление автопарком».

    Реальная реализация обращается к API приложения или сервисному слою.
    Главный агент не получает прямой доступ к БД.
    """

    # Техника и история
    def list_vehicles(self) -> List[Dict[str, Any]]: ...
    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]: ...
    def get_vehicle_history(self, vehicle_id: str) -> List[Dict[str, Any]]: ...

    # Ремонты
    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]: ...
    def create_repair(
        self,
        vehicle_id: str,
        problem: str,
        mileage: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    # ТО
    def get_maintenance_status(self, vehicle_id: str) -> Dict[str, Any]: ...

    # Документы
    def get_vehicle_documents(self, vehicle_id: str) -> List[Dict[str, Any]]: ...

    # Топливо
    def get_fuel_transactions(self, vehicle_id: str) -> List[Dict[str, Any]]: ...

    # Запчасти
    def get_vehicle_parts(self, vehicle_id: str) -> List[Dict[str, Any]]: ...

    # Закупки
    def get_vehicle_purchases(self, vehicle_id: str) -> List[Dict[str, Any]]: ...

    # Контроль
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
        return [
            self._wrap("vehicle_history_event", item)
            for item in self.backend.get_vehicle_history(vehicle_id)
        ]

    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._wrap("repair", item) for item in self.backend.get_repairs(vehicle_id)]

    def create_repair(
        self,
        vehicle_id: str,
        problem: str,
        mileage: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        item = self.backend.create_repair(vehicle_id, problem, mileage, notes)
        return self._wrap("repair", item)

    def get_maintenance_status(self, vehicle_id: str) -> Dict[str, Any]:
        return self._wrap("maintenance_status", self.backend.get_maintenance_status(vehicle_id))

    def get_vehicle_documents(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [
            self._wrap("vehicle_document", item)
            for item in self.backend.get_vehicle_documents(vehicle_id)
        ]

    def get_fuel_transactions(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [
            self._wrap("fuel_transaction", item)
            for item in self.backend.get_fuel_transactions(vehicle_id)
        ]

    def get_vehicle_parts(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [
            self._wrap("vehicle_part", item)
            for item in self.backend.get_vehicle_parts(vehicle_id)
        ]

    def get_vehicle_purchases(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [
            self._wrap("purchase", item)
            for item in self.backend.get_vehicle_purchases(vehicle_id)
        ]

    def get_attention_items(self) -> List[Dict[str, Any]]:
        return [
            self._wrap("attention_item", item)
            for item in self.backend.get_attention_items()
        ]

    def get_vehicle_overview(self, vehicle_id: str) -> Dict[str, Any]:
        """Сводка для Главного агента по одной единице техники."""
        return {
            "vehicle": self.get_vehicle(vehicle_id),
            "maintenance": self.get_maintenance_status(vehicle_id),
            "documents": self.get_vehicle_documents(vehicle_id),
            "repairs": self.get_repairs(vehicle_id),
            "fuel": self.get_fuel_transactions(vehicle_id),
            "parts": self.get_vehicle_parts(vehicle_id),
            "purchases": self.get_vehicle_purchases(vehicle_id),
        }

    def _wrap(self, record_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        source_record_id = (
            payload.get("vehicle_id")
            or payload.get("repair_id")
            or payload.get("event_id")
            or payload.get("attention_id")
            or payload.get("maintenance_id")
            or payload.get("document_id")
            or payload.get("fuel_transaction_id")
            or payload.get("part_id")
            or payload.get("purchase_id")
            or payload.get("id")
        )
        return {
            "source_system": self.source_system,
            "source_record_id": source_record_id,
            "record_type": record_type,
            "payload": payload,
        }
