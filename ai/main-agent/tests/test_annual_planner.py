import pytest
from ecosystem.annual_planner import AnnualPlanner, PlanConflict

@pytest.fixture
def planner(tmp_path):
    return AnnualPlanner(str(tmp_path / "planner.sqlite3"))

def test_approval_and_milestone_progress(planner):
    plan = planner.create("org1", 2027, "План организации", "owner")
    pid = plan["plan_id"]
    with pytest.raises(PlanConflict):
        planner.approve("org1", pid, "owner")
    milestone = planner.add_milestone("org1", pid, 10, "Сверить расходы", "owner")
    planner.approve("org1", pid, "owner")
    proposal = planner.propose_milestone_status("org1", pid, milestone["milestone_id"], "done", "Проверено", "agent")
    assert planner.get("org1", pid)["progress"]["done"] == 0
    assert planner.decide_proposal("org1", pid, proposal["proposal_id"], "owner", True)["progress"]["done"] == 1
    assert AnnualPlanner(planner.path).get("org1", pid)["progress"]["done"] == 1

def test_organization_isolation_and_rejected_proposal(planner):
    pid = planner.create("org1", 2027, "Цель", "owner")["plan_id"]
    milestone = planner.add_milestone("org1", pid, 3, "Этап", "owner")
    with pytest.raises(KeyError):
        planner.get("org2", pid)
    planner.approve("org1", pid, "owner")
    with pytest.raises(PlanConflict):
        planner.add_milestone("org1", pid, 4, "Новая цель", "agent")
    proposal = planner.propose_milestone_status("org1", pid, milestone["milestone_id"], "blocked", "Риск", "agent")
    with pytest.raises(KeyError):
        planner.decide_proposal("org2", pid, proposal["proposal_id"], "other", True)
    assert planner.decide_proposal("org1", pid, proposal["proposal_id"], "owner", False)["milestones"][0]["status"] == "planned"

def test_case_monitoring_never_changes_plan_automatically(planner):
    pid = planner.create("org1", 2027, "Цель", "owner")["plan_id"]
    planner.add_milestone("org1", pid, 10, "ТО", "owner", "case1")
    planner.approve("org1", pid, "owner")
    result = planner.overview("org1", pid, [{"case_id": "case1", "status": "blocked"}])
    assert result["requires_attention"]
    assert result["milestones"][0]["status"] == "planned"
