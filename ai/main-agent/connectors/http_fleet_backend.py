import json
import os
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpFleetBackend:
    """Service-to-service backend for the real fleet-management application."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or os.getenv("FLEET_API_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("FLEET_MAIN_AGENT_API_KEY", "")
        if not self.base_url:
            raise RuntimeError("FLEET_API_BASE_URL is required")
        if not self.api_key:
            raise RuntimeError("FLEET_MAIN_AGENT_API_KEY is required")
        if not self.base_url.startswith("https://") and not (
            self.base_url.startswith("http://localhost") or self.base_url.startswith("http://127.0.0.1")
        ):
            raise RuntimeError("Fleet API must use HTTPS outside localhost")

    def _request(self, method: str, *, vehicle_id: Optional[str] = None,
                 view: Optional[str] = None, organization_id: Optional[str] = None,
                 payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params: Dict[str, str] = {}
        if vehicle_id:
            params["vehicleId"] = vehicle_id
        if view:
            params["view"] = view
        if organization_id:
            params["organizationId"] = organization_id
        query = f"?{urlencode(params)}" if params else ""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"x-main-agent-key": self.api_key, "accept": "application/json"}
        if payload is not None:
            headers["content-type"] = "application/json"
        request = Request(f"{self.base_url}/api/agent/fleet{query}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, vehicle_id: Optional[str] = None, view: Optional[str] = None,
             organization_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", vehicle_id=vehicle_id, view=view, organization_id=organization_id)

    def list_vehicles(self, organization_id: str) -> List[Dict[str, Any]]:
        return [self._vehicle_shape(row) for row in self._get(organization_id=organization_id).get("vehicles", [])]

    def get_vehicle(self, vehicle_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self._get(vehicle_id, organization_id=organization_id).get("vehicle")
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
        result = self._request("POST", payload={
            "action": "create_repair",
            "vehicleId": vehicle_id,
            "problem": problem,
            "mileage": mileage,
            "notes": notes,
        })
        repair = result["repair"]
        return {**repair, "repair_id": repair.get("id"), "audit_recorded": bool(result.get("audit", {}).get("recorded"))}

    def create_document_candidate(
        self,
        *,
        organization_id: str,
        source_user_id: str,
        source_email_id: str,
        source_attachment_id: str,
        original_name: str,
        mime_type: Optional[str] = None,
        size_bytes: Optional[int] = None,
        document_type: str = "parts_invoice",
        metadata: Optional[Dict[str, Any]] = None,
        content_bytes: bytes,
    ) -> Dict[str, Any]:
        if not content_bytes:
            raise ValueError("content_bytes is required for fleet document transfer")
        if len(content_bytes) > 25 * 1024 * 1024:
            raise ValueError("attachment exceeds 25 MB fleet transfer limit")

        boundary = f"----MainAgent{uuid.uuid4().hex}"
        fields = {
            "action": "create_document_candidate",
            "organizationId": organization_id,
            "sourceUserId": source_user_id,
            "sourceEmailId": source_email_id,
            "sourceAttachmentId": source_attachment_id,
            "originalName": original_name,
            "mimeType": mime_type or "application/octet-stream",
            "documentType": document_type,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        }
        chunks: List[bytes] = []
        for name, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ])
        safe_name = original_name.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode(),
            f"Content-Type: {(mime_type or 'application/octet-stream')}\r\n\r\n".encode(),
            content_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        request = Request(
            f"{self.base_url}/api/agent/fleet",
            data=b"".join(chunks),
            headers={
                "x-main-agent-key": self.api_key,
                "accept": "application/json",
                "content-type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["candidate"]

    def list_document_candidates(self, organization_id: str) -> List[Dict[str, Any]]:
        return list(self._get(view="document_candidates", organization_id=organization_id).get("items", []))

    def get_document_candidate_content(self, organization_id: str, candidate_id: str) -> tuple[bytes, str, str]:
        query = urlencode({"view": "document_candidate_content", "organizationId": organization_id, "candidateId": candidate_id})
        request = Request(f"{self.base_url}/api/agent/fleet?{query}", headers={"x-main-agent-key": self.api_key}, method="GET")
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            disposition = response.headers.get("Content-Disposition", "")
            return response.read(), content_type, disposition

    def get_vehicle_work_items(self, organization_id: str, vehicle_id: str) -> Dict[str, Any]:
        vehicle = self._get(vehicle_id, organization_id=organization_id).get("vehicle") or {}
        return {
            "vehicle_id": vehicle_id,
            "repairs": [self._id_shape(x, "repair_id") for x in vehicle.get("repairs", [])],
            "purchases": [self._id_shape(x, "purchase_id") for x in vehicle.get("purchaseRequests", [])],
        }

    def assign_document_candidate(self, *, organization_id: str, candidate_id: str, vehicle_id: str,
                                  purchase_request_id: Optional[str] = None,
                                  repair_id: Optional[str] = None) -> Dict[str, Any]:
        result = self._request("POST", payload={
            "action": "assign_document_candidate",
            "organizationId": organization_id,
            "candidateId": candidate_id,
            "vehicleId": vehicle_id,
            "purchaseRequestId": purchase_request_id,
            "repairId": repair_id,
        })
        return result["candidate"]

    def dismiss_document_candidate(self, *, organization_id: str, candidate_id: str) -> Dict[str, Any]:
        result = self._request("POST", payload={
            "action": "dismiss_document_candidate",
            "organizationId": organization_id,
            "candidateId": candidate_id,
        })
        return result["candidate"]

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
            "document_id": f"diagnostic-card:{vehicle_id}", "vehicle_id": vehicle_id,
            "document_type": "diagnostic_card", "number": vehicle.get("diagnosticCardNumber"),
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
        rows = self._get(view="attention").get("items", [])
        result = []
        for row in rows:
            normalized = dict(row)
            normalized["attention_id"] = row.get("attentionId")
            normalized["vehicle_id"] = row.get("vehicleId")
            result.append(normalized)
        return result

    @staticmethod
    def _vehicle_shape(row: Dict[str, Any]) -> Dict[str, Any]:
        return {**row, "vehicle_id": row.get("id"), "type": row.get("vehicleType"),
                "plate_number": row.get("stateNumber"), "current_mileage": row.get("currentMileage")}

    @staticmethod
    def _id_shape(row: Dict[str, Any], target: str) -> Dict[str, Any]:
        return {**row, target: row.get("id")}
