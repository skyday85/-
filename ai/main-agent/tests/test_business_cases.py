import pytest

from ecosystem.business_cases import BusinessCaseStore, CaseConflict


@pytest.fixture
def store(tmp_path):
    return BusinessCaseStore(str(tmp_path / "cases.sqlite3"))


def case(store, org="org-a"):
    return store.create_case(org, "user-a", "Счёт на ремонт ГАЗ", "procurement")


def test_case_persists_and_is_isolated_by_organization(store):
    item = case(store)
    identifier = item["case_id"]
    assert item["status"] == "open"
    assert len(store.list_cases("org-a")) == 1
    assert store.list_cases("org-b") == []
    with pytest.raises(KeyError):
        store.get_case("org-b", identifier)
    restarted = BusinessCaseStore(store.path)
    assert restarted.get_case("org-a", identifier)["title"] == "Счёт на ремонт ГАЗ"
    assert restarted.get_case("org-a", identifier)["audit"][0]["action"] == "case_created"


def test_links_are_idempotent_and_require_active_projects(store):
    identifier = case(store)["case_id"]
    kwargs = dict(organization_id="org-a", case_id=identifier, project_id="fleet-management",
                  record_type="vehicle", record_id="car-1", actor_id="user-a")
    first = store.link_record(**kwargs)
    again = store.link_record(**kwargs)
    assert first["link_id"] == again["link_id"]
    assert len(store.get_case("org-a", identifier)["links"]) == 1
    with pytest.raises(ValueError):
        store.link_record("org-a", identifier, "mail-service", "mail", "m1", "user-a")
    with pytest.raises(KeyError):
        store.link_record("org-b", identifier, "fleet-management", "vehicle", "car-1", "user-b")


def test_signals_are_deduplicated_durably_with_global_source_scope(store):
    first_case = case(store)["case_id"]
    other_case = case(store)["case_id"]
    kwargs = dict(organization_id="org-a", case_id=first_case, project_id="fleet-management",
                  source_record_id="repair-1", source_event_id="event-abc",
                  event_type="progress", metadata={"status": "started"})
    signal = store.record_signal(**kwargs)
    assert signal["duplicate"] is False
    assert store.record_signal(**kwargs)["duplicate"] is True
    assert store.get_case("org-a", first_case)["status"] == "in_progress"
    restarted = BusinessCaseStore(store.path)
    assert restarted.record_signal(**kwargs)["duplicate"] is True
    with pytest.raises(CaseConflict):
        restarted.record_signal(**{**kwargs, "case_id": other_case})
    with pytest.raises(CaseConflict):
        restarted.record_signal(**{**kwargs, "metadata": {"status": "changed"}})
    assert len(restarted.get_case("org-a", first_case)["signals"]) == 1


def test_source_event_scope_is_separate_per_organization(store):
    a, b = case(store, "org-a"), case(store, "org-b")
    for org, item in (("org-a", a), ("org-b", b)):
        store.record_signal(org, item["case_id"], "fleet-management",
                            "repair-1", "same-provider-event", "observed")
    assert len(store.get_case("org-a", a["case_id"])["signals"]) == 1
    assert len(store.get_case("org-b", b["case_id"])["signals"]) == 1


def test_review_requires_human_decision_before_closure(store):
    identifier = case(store)["case_id"]
    store.record_signal("org-a", identifier, "finance-planning",
                        "transaction-1", "signal-1", "review_requested",
                        {"proposal": "parts"})
    pending = store.get_case("org-a", identifier)
    assert pending["status"] == "needs_review"
    assert len(pending["reviews"]) == 1
    with pytest.raises(CaseConflict):
        store.close_case("org-a", identifier, "user-a")
    review_id = pending["reviews"][0]["review_id"]
    decided = store.decide_review("org-a", identifier, review_id, "user-a", True)
    assert decided["status"] == "in_progress"
    assert decided["reviews"][0]["decision_by"] == "user-a"
    with pytest.raises(CaseConflict):
        store.decide_review("org-a", identifier, review_id, "user-a", True)
    assert store.close_case("org-a", identifier, "user-a")["status"] == "closed"
    with pytest.raises(CaseConflict):
        store.record_signal("org-a", identifier, "finance-planning",
                            "transaction-2", "signal-2", "progress")
    with pytest.raises(CaseConflict):
        store.link_record("org-a", identifier, "fleet-management", "vehicle", "car-1", "user-a")


def test_rejected_review_blocks_case_until_explicit_resume(store):
    identifier = case(store)["case_id"]
    store.record_signal("org-a", identifier, "finance-planning",
                        "tx-1", "review-1", "review_requested")
    review_id = store.get_case("org-a", identifier)["reviews"][0]["review_id"]
    assert store.decide_review("org-a", identifier, review_id, "user-a", False)["status"] == "blocked"
    with pytest.raises(CaseConflict):
        store.close_case("org-a", identifier, "user-a")
    with pytest.raises(ValueError):
        store.resume_case("org-a", identifier, "user-a", " ")
    resumed = store.resume_case("org-a", identifier, "user-a", "Данные уточнены")
    assert resumed["status"] == "in_progress"
    assert resumed["audit"][-1]["details"]["reason"] == "Данные уточнены"


def test_multiple_reviews_and_failure_cannot_be_bypassed_by_approval(store):
    identifier = case(store)["case_id"]
    for n in (1, 2):
        store.record_signal("org-a", identifier, "finance-planning",
                            f"tx-{n}", f"review-{n}", "review_requested")
    reviews = store.get_case("org-a", identifier)["reviews"]
    assert store.decide_review("org-a", identifier, reviews[0]["review_id"], "user-a", True)["status"] == "needs_review"
    store.record_signal("org-a", identifier, "fleet-management", "repair-1", "failed-1", "failed")
    assert store.decide_review("org-a", identifier, reviews[1]["review_id"], "user-a", True)["status"] == "blocked"
    assert store.resume_case("org-a", identifier, "user-a", "Ошибка устранена")["status"] == "in_progress"


def test_invalid_events_rejected_without_side_effect(store):
    identifier = case(store)["case_id"]
    args = dict(organization_id="org-a", case_id=identifier, project_id="fleet-management",
                source_record_id="r1", source_event_id="s1", event_type="progress")
    with pytest.raises(ValueError):
        store.record_signal(**{**args, "event_type": "user_approved"})
    with pytest.raises(ValueError):
        store.record_signal(**{**args, "metadata": {"blob": "x" * 17000}})
    with pytest.raises(ValueError):
        store.record_signal(**{**args, "project_id": "nonexistent"})
    with pytest.raises(KeyError):
        store.record_signal(**{**args, "organization_id": "org-b"})
    assert store.get_case("org-a", identifier)["signals"] == []


def test_closed_case_close_is_idempotent_and_does_not_duplicate_audit(store):
    identifier = case(store)["case_id"]
    result = store.close_case("org-a", identifier, "user-a")
    assert result["status"] == "closed"
    again = store.close_case("org-a", identifier, "user-a")
    assert [e["action"] for e in again["audit"]].count("case_closed") == 1
