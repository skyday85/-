from runtime import MainAgentRuntime


class FakeCases:
    def __init__(self):
        self.links = []
        self.events = []

    def get_case(self, org, case_id):
        if org != "org-1" or case_id != "case-1":
            raise KeyError(case_id)
        return {"case_id": case_id, "organization_id": org}

    def link_record(self, org, case, project, kind, record_id, agent_id):
        self.links.append((org, case, project, kind, record_id, agent_id))

    def record_signal(self, org, case, project, record_id, source_event_id, event_type, metadata):
        self.events.append((org, case, project, record_id, source_event_id, event_type, metadata))


class FakeFleet:
    def __init__(self):
        self.calls = []

    def create_ua_agent_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"taskId": kwargs["task_id"], "organizationId": kwargs["organization_id"],
                "businessCaseId": kwargs["business_case_id"], "status": "completed",
                "reply": "Проверено"}

    def get_ua_agent_task(self, **kwargs):
        return {"taskId": kwargs["task_id"], "organizationId": kwargs["organization_id"],
                "businessCaseId": "case-1", "status": "completed", "reply": "Проверено"}


def test_main_agent_can_delegate_and_track_ua_task_under_business_case():
    runtime = MainAgentRuntime.__new__(MainAgentRuntime)
    runtime.business_cases = FakeCases()
    runtime.fleet_backend = FakeFleet()
    result = runtime.delegate_to_fleet_agent(
        "org-1", "Проверить ТО автопарка", task_id="task-1", business_case_id="case-1")
    assert result["status"] == "completed"
    assert runtime.fleet_backend.calls[0]["organization_id"] == "org-1"
    assert runtime.business_cases.links == [
        ("org-1", "case-1", "fleet-management", "ua_agent_task", "task-1", "main_agent")]
    assert runtime.business_cases.events[0][5] == "completed"
    again = runtime.get_fleet_agent_task("org-1", "task-1")
    assert again["reply"] == "Проверено"


def test_unknown_business_case_cannot_be_delegated():
    runtime = MainAgentRuntime.__new__(MainAgentRuntime)
    runtime.business_cases = FakeCases()
    runtime.fleet_backend = FakeFleet()
    try:
        runtime.delegate_to_fleet_agent(
            "other-org", "Проверить ТО", task_id="task-2", business_case_id="case-1")
        assert False, "Expected KeyError"
    except KeyError:
        pass
    assert runtime.fleet_backend.calls == []
