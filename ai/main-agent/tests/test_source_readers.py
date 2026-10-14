import io
import json

import pytest

from ecosystem.source_readers import CaseSourceReader, FinanceReadConnector, SourceUnavailable


class MockResponse:
    def __init__(self, payload):
        self.content = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.content.close()

    def read(self, count=-1):
        return self.content.read(count)


def test_finance_uses_scoped_bearer_and_only_verified_read_endpoints():
    requests = []

    def open_request(request, timeout):
        requests.append((request, timeout))
        return MockResponse({"total": 40, "rows": []})

    finance = FinanceReadConnector("https://finance.example.com", "secret-read-token", "org-1", open_request)
    report = finance.plan_fact("org-1", from_date="2026-10-01", to_date="2026-10-31")
    assert report["total"] == 40
    assert requests[0][0].full_url == "https://finance.example.com/api/reports/plan-fact?from=2026-10-01&to=2026-10-31"
    assert requests[0][0].get_header("Authorization") == "Bearer secret-read-token"
    assert requests[0][1] == 12
    with pytest.raises(SourceUnavailable):
        finance.plan_fact("org-2")
    with pytest.raises(ValueError):
        finance._get("org-1", "/api/admin/integration-keys")
    assert len(requests) == 1


def test_finance_legacy_api_is_disabled_without_single_org_pin():
    finance = FinanceReadConnector("https://finance.example.com", "secret", "", lambda *_a, **_k: None)
    with pytest.raises(SourceUnavailable):
        finance.plan_fact("org-1")


def test_finance_legacy_connector_enforces_https():
    with pytest.raises(ValueError):
        FinanceReadConnector("http://example.com", "secret", "org-1")


class FleetStub:
    def get_vehicle(self, record_id, org):
        return {"id": record_id, "vehicle_id": record_id, "plate_number": "Р875УХ797",
                "current_mileage": 367000, "status": "active", "nextMaintenanceMileage": 380000}

    def list_document_candidates(self, org):
        return [{"candidate_id": "file-1", "status": "pending_assignment"}]


class MailStub:
    def get_message(self, actor, message_id):
        if actor != "owner" or message_id != "mail-1":
            raise KeyError(message_id)
        return {"email_id": "mail-1", "subject": "Счёт на детали",
                "account_id": "a1", "classification": "parts_invoice_candidate",
                "review_status": "needs_review", "body_text": "private secret"}


def test_source_snapshot_reads_fleet_and_mail_without_mutations():
    r = CaseSourceReader(fleet_backend=FleetStub(), mailbox=MailStub(),
                         fleet_organization_id="org-1")
    case = {"case_id": "c1", "organization_id": "org-1", "created_by": "owner",
            "links": [
                {"project_id": "fleet-management", "record_type": "vehicle", "record_id": "vehicle-1"},
                {"project_id": "mail-contour", "record_type": "email", "record_id": "mail-1"},
            ]}
    data = r.snapshot(case, "owner")
    assert data["partial"] is False
    assert data["sources"][0]["data"]["state_number"] == "Р875УХ797"
    assert "body_text" not in data["sources"][1]["data"]
    assert data["sources"][1]["data"]["classification"] == "parts_invoice_candidate"


def test_untrusted_organization_and_other_mail_user_do_not_get_source_data():
    r = CaseSourceReader(fleet_backend=FleetStub(), mailbox=MailStub(),
                         fleet_organization_id="org-1")
    case = {"case_id": "c1", "organization_id": "org-2", "created_by": "owner",
            "links": [
                {"project_id": "fleet-management", "record_type": "vehicle", "record_id": "vehicle-1"},
                {"project_id": "mail-contour", "record_type": "email", "record_id": "mail-1"},
            ]}
    data = r.snapshot(case, "other")
    assert data["partial"] is True
    assert [x["status"] for x in data["sources"]] == ["unavailable", "unavailable"]
    assert all("data" not in x for x in data["sources"])


def test_finance_event_query_returns_only_matching_summary():
    queries = []

    def open_request(request, timeout):
        queries.append(request)
        return MockResponse([{"id": "e1", "status": "unmatched", "amount": 12, "secret": "no"},
                             {"id": "e2", "status": "matched", "amount": 20}])

    finance = FinanceReadConnector("https://finance.example.com", "token", "org-1", open_request)
    data = finance.read_link("org-1", "financial_event", "e2")
    assert data == {"id": "e2", "status": "matched", "source_type": None}
    with pytest.raises(KeyError):
        finance.read_link("org-1", "financial_event", "not-found")
