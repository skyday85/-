import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpFleetBackend:
    """Service-to-service backend for the real fleet-management application.

    Requires FLEET_API_BASE_URL and FLEET_MAIN_AGENT_API_KEY. The Main Agent
    never connects to the fleet database directly.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or os.getenv("FLEET_API_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("FLEET_MAIN_AGENT_API_KEY", "")
        if not self.base_url:
            raise RuntimeError("FLEET_API_BASE_URL is required")
        if not self.api_key:
            raise RuntimeError("FLEET_MAIN_AGENT_API_KEY is required")

    def _get(self, vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        query = f"?{urlencode({'vehicleId': vehicle_id})}" if vehicle_id else ""
        request = Request(
            f"{self.base_url}/api/agent/fleet{query}",
            headers={"x-main-agent-key": self.api_key, "accept": "application/json"},
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_vehicles(self) -> List[Dict[str, Any]]:
        rows = self._get().get("vehicles", [])
        return [self._vehicle_shape(row) for row in rows]

    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        row = self._get(vehicle_id).get("vehicle")
        return self._vehicle_shape(row) if row else None

    def get_vehicle_history(self, vehicle_id: str) -> List[Dict[str, Any]]:
        row = self._get(vehicle_id).get("vehicle", {})
        events: List[Dict[str, Any]] = []
        for repair in row.get("repairs", []):
            events.append({"event_id": repair["id"], "vehicle_id": vehicle_id, "event_type": "repair", **repair})
        for maintenance in row.get("maintenanceRecords", []):
            events.append({"event_id": maintenance["id"], "vehicle_id": vehicle_id, "event_type": "maintenance", **maintenance})
        for fuel in row.get("fuelRecords", []):
            events.append({"event_id": fuel["id"], "vehicle_id": vehicle_id, "event_type": "fuel", **fuel})
        return events

    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._id_shape(x, "repair_id") for x in self._get(vehicle_id).get("vehicle", {}).get("repairs", [])]

    def create_repair(self, vehicle_id: str, problem: str, mileage: Optional[int] = None,
                      notes: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError("Repair writes are not enabled for the Main Agent service API yet")

    def get_maintenance_status(self, vehicle_id: str) -> Dict[str, Any]:
        vehicle = self._get(vehicle_id).get("vehicle", {})
        return {
            "maintenance_id": f"maintenance-status:{vehicle_id}",
            "vehicle_id": vehicle_id,
            "current_mileage": vehicle.get("currentMileage"),
            "maintenance_interval_km": vehicle.get("maintenanceIntervalKm"),
            "next_maintenance_mileage": vehicle.get("nextMaintenanceMileage"),
            "records": vehicle.get("maintenanceRecords", []),
        }

    def get_vehicle_documents(self, vehicle_id: str) -> List[Dict[str, Any]]:
        vehicle = self._get(vehicle_id).get("vehicle", {})
        documents: List[Dict[str, Any]] = [{
            "document_id": f"diagnostic-card:{vehicle_id}",
            "vehicle_id": vehicle_id,
            "document_type": "diagnostic_card",
            "number": vehicle.get("diagnosticCardNumber"),
            "valid_until": vehicle.get("diagnosticCardUntil"),
        }]
        for policy in vehicle.get("insurancePolicies", []):
            documents.append({"document_id": policy["id"], "vehicle_id": vehicle_id, "document_type": "osago", **policy})
        for permit in vehicle.get("moscowPasses", []):
            documents.append({"document_id": permit["id"], "vehicle_id": vehicle_id, "document_type": "moscow_pass", **permit})
        return documents

    def get_fuel_transactions(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._id_shape(x, "fuel_transaction_id") for x in self._get(vehicle_id).get("vehicle", {}).get("fuelRecords", [])]

    def get_vehicle_parts(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._id_shape(x, "part_id") for x in self._get(vehicle_id).get("vehicle", {}).get("partInstallations", [])]

    def get_vehicle_purchases(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [self._id_shape(x, "purchase_id") for x in self._get(vehicle_id).get("vehicle", {}).get("purchaseRequests", [])]

    def get_attention_items(self) -> List[Dict[str, Any]]:
        # Dedicated alert endpoint will replace this derived MVP implementation.
        items: List[Dict[str, Any]] = []
        for vehicle in self._get().get("vehicles", []):
            current = vehicle.get("currentMileage")
            next_service = vehicle.get("nextMaintenanceMileage")
            if current is not None and next_service is not None and next_service - current <= 2000:
                items.append({
                    "attention_id": f"maintenance:{vehicle['id']}",
                    "vehicle_id": vehicle["id"],
                    "type": "maintenance_due",
                    "current_mileage": current,
                    "next_maintenance_mileage": next_service,
                })
        return items

    @staticmethod
    def _vehicle_shape(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **row,
            "vehicle_id": row.get("id"),
            "type": row.get("vehicleType"),
            "plate_number": row.get("stateNumber"),
            "current_mileage": row.get("currentMileage"),
        }

    @staticmethod
    def _id_shape(row: Dict[str, Any], target: str) -> Dict[str, Any]:
        return {**row, target: row.get("id")}
