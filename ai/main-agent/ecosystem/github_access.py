from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ecosystem.project_registry import ProjectRegistry


PROTECTED_BRANCHES = {"main", "master", "production", "prod"}
SENSITIVE_PARTS = {
    ".env",
    ".env.production",
    ".env.local",
    "secrets",
    "credentials",
    "private_keys",
    ".vercel",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


@dataclass(frozen=True)
class RepositoryAccessDecision:
    allowed: bool
    operation: str
    repository: str
    branch: str | None
    reason: str


class RepositoryAccessPolicy:
    """Local safety policy; provider-side GitHub permissions remain authoritative."""

    def __init__(self, registry: ProjectRegistry | None = None) -> None:
        self.registry = registry or ProjectRegistry()

    def can_read(self, repository: str) -> RepositoryAccessDecision:
        project = self.registry.by_repository(repository)
        if project is None:
            return RepositoryAccessDecision(False, "read", repository, None, "repository_not_registered")
        if project.status not in {"active", "target_repository"}:
            return RepositoryAccessDecision(False, "read", repository, None, "project_not_available")
        return RepositoryAccessDecision(True, "read", repository, None, "registered_repository")

    def can_write(self, repository: str, branch: str, *, path: str | None = None) -> RepositoryAccessDecision:
        project = self.registry.by_repository(repository)
        if project is None:
            return RepositoryAccessDecision(False, "write", repository, branch, "repository_not_registered")
        if project.status != "active" and project.project_id != "main-agent":
            return RepositoryAccessDecision(False, "write", repository, branch, "project_not_active")
        if not self.registry.can_write(project.project_id):
            return RepositoryAccessDecision(False, "write", repository, branch, "write_not_granted")
        normalized_branch = branch.strip().lower()
        if normalized_branch in PROTECTED_BRANCHES:
            return RepositoryAccessDecision(False, "write", repository, branch, "protected_branch")
        if not normalized_branch:
            return RepositoryAccessDecision(False, "write", repository, branch, "branch_required")
        if path and self._sensitive_path(path):
            return RepositoryAccessDecision(False, "write", repository, branch, "sensitive_path")
        return RepositoryAccessDecision(True, "write", repository, branch, "controlled_feature_branch_write")

    @staticmethod
    def _sensitive_path(path: str) -> bool:
        normalized = path.strip().replace("\\", "/")
        pure = PurePosixPath(normalized)
        parts = {part.lower() for part in pure.parts}
        if parts & SENSITIVE_PARTS:
            return True
        if pure.suffix.lower() in SENSITIVE_SUFFIXES:
            return True
        filename = pure.name.lower()
        return filename in {"id_rsa", "id_ed25519"} or filename.startswith(".env.")
