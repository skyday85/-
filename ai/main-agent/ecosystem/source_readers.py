"""Read-only adapters to registered application APIs for Business Case evidence.

Integration secrets stay server-side. Unscoped legacy application APIs may only
be used when explicitly pinned to one organization until native tenant isolation exists.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class SourceUnavailable(RuntimeError):
    pass


def _safe_base(url: str) -> str:
    url = url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Service URL must not include credentials, query or fragment")
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return url
    raise ValueError("Service API must use HTTPS outside localhost")


def _require_single_org(organization_id: str, pinned: str, service: str):
    if not pinned or pinned != organization_id:
        raise SourceUnavailable(f"{service}: organization isolation is not configured")


class FinanceReadConnector:
    """Read-only connector using an existing finance:read integration key."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 organization_id: str | None = None, opener=None):
        self.base_url = _safe_base(base_url) if base_url else ""
        self.token = token or ""
        self.organization_id = organization_id or ""
        self.opener = opener or urlopen

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("FINANCE_API_BASE_URL", "").strip(),
                   os.getenv("FINANCE_MAIN_AGENT_READ_TOKEN", "").strip(),
                   os.getenv("FINANCE_SINGLE_ORGANIZATION_ID", "").strip())

    def _get(self, organization_id: str, path: str, params: dict[str, str] | None = None):
        _require_single_org(organization_id, self.organization_id, "finance")
        if not self.base_url or not self.token:
            raise SourceUnavailable("finance: endpoint or finance:read key is not configured")
        allowed = {"/api/reports/plan-fact", "/api/reports/management-result",
                   "/api/integrations/fleet/financial-events"}
        if path not in allowed:
            raise ValueError("finance endpoint not permitted")
        uri = self.base_url + path
        if params:
            uri += "?" + urlencode(params)
        request = Request(uri, headers={"Authorization": "Bearer " + self.token,
                                         "Accept": "application/json"}, method="GET")
        try:
            with self.opener(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceUnavailable("finance: read request failed") from exc

    def plan_fact(self, organization_id: str, *, from_date: str | None = None,
                  to_date: str | None = None):
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._get(organization_id, "/api/reports/plan-fact", params)

    def management_result(self, organization_id: str):
        return self._get(organization_id, "/api/reports/management-result")

    def financial_events(self, organization_id: str):
        return self._get(organization_id, "/api/integrations/fleet/financial-events")

    def read_link(self, organization_id: str, record_type: str, record_id: str):
        if record_type == "report" and record_id == "plan_fact":
            return self.plan_fact(organization_id)
        if record_type == "financial_event":
            records = self.financial_events(organization_id)
            if isinstance(records, dict):
                records = records.get("items") or records.get("events") or []
            if not isinstance(records, list):
                raise SourceUnavailable("finance: unexpected financial events response")
            for row in records:
                if isinstance(row, dict) and str(row.get("id", "")) == record_id:
                    return {"id": row.get("id"), "status": row.get("status"),
                            "source_type": row.get("sourceType") or row.get("source_type")}
            raise KeyError(record_id)
        raise ValueError("finance record type unsupported")


class CaseSourceReader:
    """Evidence reader. Never posts to business applications or resolves reviews."""

    def __init__(self, *, fleet_backend=None, finance=None, mailbox=None,
                 fleet_organization_id: str = ""):
        self.fleet_backend = fleet_backend
        self.finance = finance or FinanceReadConnector()
        self.mailbox = mailbox
        self.fleet_organization_id = fleet_organization_id

    def read_link(self, organization_id: str, case_creator: str, actor_id: str, link: dict):
        project = link["project_id"]
        record_type = link["record_type"]
        record_id = link["record_id"]
        if project == "fleet-management":
            _require_single_org(organization_id, self.fleet_organization_id, "fleet")
            if not self.fleet_backend:
                raise SourceUnavailable("fleet: connector unavailable")
            if record_type == "vehicle":
                record = self.fleet_backend.get_vehicle(record_id, organization_id)
                if not record or str(record.get("vehicle_id") or record.get("id")) != record_id:
                    raise KeyError(record_id)
                return {"vehicle_id": record_id, "state_number": record.get("plate_number"),
                        "status": record.get("status"), "current_mileage": record.get("current_mileage"),
                        "next_maintenance_mileage": record.get("nextMaintenanceMileage")}
            if record_type == "document_candidate":
                rows = self.fleet_backend.list_document_candidates(organization_id)
                for row in rows:
                    if str(row.get("candidate_id") or row.get("id")) == record_id:
                        return {"candidate_id": record_id, "status": row.get("status")}
                raise KeyError(record_id)
            raise ValueError("fleet record type unsupported")
        if project == "finance-planning":
            return self.finance.read_link(organization_id, record_type, record_id)
        if project == "mail-contour":
            if not self.mailbox:
                raise SourceUnavailable("mail: mailbox unavailable")
            if actor_id != case_creator:
                raise SourceUnavailable("mail: only case owner may read this source")
            if record_type != "email":
                raise ValueError("mail record type unsupported")
            msg = self.mailbox.get_message(actor_id, record_id)
            return {"email_id": msg["email_id"], "subject": msg.get("subject"),
                    "classification": msg.get("classification"),
                    "review_status": msg.get("review_status"),
                    "account_id": msg.get("account_id")}
        raise SourceUnavailable("project connector not available")

    def snapshot(self, case: dict, actor_id: str):
        results = []
        for link in case["links"]:
            evidence = {"project_id": link["project_id"], "record_type": link["record_type"],
                        "record_id": link["record_id"]}
            try:
                evidence["status"] = "available"
                evidence["data"] = self.read_link(case["organization_id"],
                                                 case["created_by"], actor_id, link)
            except (KeyError, ValueError, SourceUnavailable, OSError, TimeoutError) as exc:
                evidence["status"] = "unavailable"
                evidence["reason"] = type(exc).__name__
            results.append(evidence)
        return {"business_case_id": case["case_id"], "organization_id": case["organization_id"],
                "sources": results, "partial": any(e["status"] != "available" for e in results)}
