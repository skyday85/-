from importlib import import_module

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ecosystem.business_cases import BusinessCaseStore


@pytest.fixture
def case_api(tmp_path, monkeypatch):
    api = import_module("http_api.app")
    store = BusinessCaseStore(str(tmp_path / "api-business-cases.sqlite3"))
    monkeypatch.setattr(api.runtime, "business_cases", store)
    return api


def test_business_case_endpoints_are_tenant_scoped(case_api):
    payload = case_api.BusinessCaseCreateRequest(title="Заявка клиента", case_type="transport_request")
    created = case_api.create_business_case(payload, user_id="user-1", organization_id="org-1")
    assert created["case_type"] == "transport_request"
    case_id = created["case_id"]
    assert len(case_api.list_business_cases(organization_id="org-1", _user="user-1")) == 1
    assert case_api.list_business_cases(organization_id="org-2", _user="user-2")["items"] == []
    with pytest.raises(HTTPException) as err:
        case_api.get_business_case(case_id, organization_id="org-2", _user="user-2")
    assert err.value.status_code == 404


def test_review_cannot_be_autoapproved_by_source_signal(case_api):
    created = case_api.create_business_case(
        case_api.BusinessCaseCreateRequest(title="Финансовое согласование", case_type="finance_review"),
        user_id="u1", organization_id="org-1",
    )
    case_id = created["case_id"]
    signal = case_api.ingest_business_case_signal(
        case_id,
        case_api.BusinessCaseSignalRequest(
            project_id="finance-planning", source_record_id="txn-1",
            source_event_id="external-1", event_type="review_requested",
        ),
        _integration=None, _user="service", organization_id="org-1",
    )
    assert signal["event_type"] == "review_requested"
    with pytest.raises(HTTPException) as blocked:
        case_api.close_business_case(case_id, user_id="u1", organization_id="org-1")
    assert blocked.value.status_code == 409
    review_id = case_api.get_business_case(case_id, _user="u1", organization_id="org-1")["reviews"][0]["review_id"]
    decided = case_api.decide_business_case_review(
        case_id, review_id,
        case_api.BusinessCaseReviewDecisionRequest(approved=True),
        user_id="u1", organization_id="org-1",
    )
    assert decided["status"] == "in_progress"


def test_signal_integration_requires_explicit_secret(case_api, monkeypatch):
    monkeypatch.delenv("APP_CASE_INGEST_KEY", raising=False)
    request = Request({"type": "http", "method": "POST", "path": "/business-cases/id/signals", "headers": []})
    with pytest.raises(HTTPException) as missing:
        case_api.authenticated_case_integration(request)
    assert missing.value.status_code == 401

    monkeypatch.setenv("APP_CASE_INGEST_KEY", "example-secret-value")
    request = Request({
        "type": "http", "method": "POST", "path": "/business-cases/id/signals",
        "headers": [(b"x-case-integration-key", b"example-secret-value")],
    })
    assert case_api.authenticated_case_integration(request) is None
