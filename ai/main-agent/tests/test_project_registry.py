import pytest

from ecosystem.project_registry import ProjectDefinition, ProjectRegistry


def test_default_registry_contains_all_current_and_target_projects():
    registry = ProjectRegistry()
    projects = {item["project_id"]: item for item in registry.list_projects()}

    assert projects["fleet-management"]["repository"] == "skyday85/fleet-management"
    assert projects["finance-planning"]["repository"] == "skyday85/finance-planning"
    assert projects["main-agent"]["repository"] == "skyday85/main-agent"
    assert projects["mail-service"]["repository"] == "skyday85/mail-service"


def test_registry_defaults_to_registered_repositories_and_controlled_write():
    registry = ProjectRegistry()

    assert registry.can_write("fleet-management") is True
    assert registry.can_write("finance-planning") is True
    assert registry.can_write("unknown") is False
    assert "skyday85/fleet-management" in registry.repositories(active_only=True)
    assert "skyday85/main-agent" not in registry.repositories(active_only=True)


def test_repository_lookup_is_case_insensitive():
    registry = ProjectRegistry()
    project = registry.by_repository("SKYDAY85/FLEET-MANAGEMENT")
    assert project is not None
    assert project.project_id == "fleet-management"


def test_registry_rejects_duplicate_ids():
    duplicate = (
        ProjectDefinition("one", "One", "x", "skyday85/one", "application", "active", "read_only"),
        ProjectDefinition("one", "Two", "x", "skyday85/two", "application", "active", "read_only"),
    )
    with pytest.raises(ValueError):
        ProjectRegistry(duplicate)
