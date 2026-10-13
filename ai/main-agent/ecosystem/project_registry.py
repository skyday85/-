from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ProjectDefinition:
    project_id: str
    name: str
    domain: str
    repository: str
    ownership: str
    status: str
    main_agent_access: str
    api_contract: str | None = None
    notes: str | None = None


DEFAULT_PROJECTS: tuple[ProjectDefinition, ...] = (
    ProjectDefinition(
        project_id="main-agent",
        name="Главный агент",
        domain="orchestration",
        repository="skyday85/main-agent",
        ownership="main_agent",
        status="target_repository",
        main_agent_access="write_feature_branches",
        notes="Целевой отдельный репозиторий. Текущая реализация временно находится в skyday85/-.",
    ),
    ProjectDefinition(
        project_id="fleet-management",
        name="Управление автопарком",
        domain="fleet",
        repository="skyday85/fleet-management",
        ownership="application",
        status="active",
        main_agent_access="read_and_controlled_write",
        api_contract="fleet-service-api",
    ),
    ProjectDefinition(
        project_id="finance-planning",
        name="Финансы и планирование",
        domain="finance",
        repository="skyday85/finance-planning",
        ownership="application",
        status="active",
        main_agent_access="read_and_controlled_write",
        api_contract="finance-service-api",
    ),
    ProjectDefinition(
        project_id="mail-service",
        name="Почтовый сервис",
        domain="communications",
        repository="skyday85/mail-service",
        ownership="application",
        status="target_repository",
        main_agent_access="read_and_controlled_write",
        api_contract="mail-service-api",
        notes="OAuth, почтовые токены, синхронизация и пользовательский почтовый интерфейс принадлежат этому сервису, а не Главному агенту.",
    ),
)


class ProjectRegistry:
    def __init__(self, projects: Iterable[ProjectDefinition] = DEFAULT_PROJECTS) -> None:
        items = list(projects)
        ids = [item.project_id for item in items]
        repositories = [item.repository for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate project_id in project registry")
        if len(repositories) != len(set(repositories)):
            raise ValueError("Duplicate repository in project registry")
        self._projects: Dict[str, ProjectDefinition] = {item.project_id: item for item in items}

    def list_projects(self) -> List[dict]:
        return [asdict(item) for item in self._projects.values()]

    def get(self, project_id: str) -> Optional[ProjectDefinition]:
        return self._projects.get(project_id)

    def by_repository(self, repository: str) -> Optional[ProjectDefinition]:
        normalized = repository.strip().lower()
        for item in self._projects.values():
            if item.repository.lower() == normalized:
                return item
        return None

    def repositories(self, *, active_only: bool = False) -> List[str]:
        projects = self._projects.values()
        if active_only:
            projects = [item for item in projects if item.status == "active"]
        return [item.repository for item in projects]

    def can_write(self, project_id: str) -> bool:
        item = self._projects.get(project_id)
        return bool(item and item.main_agent_access in {"read_and_controlled_write", "write_feature_branches"})
