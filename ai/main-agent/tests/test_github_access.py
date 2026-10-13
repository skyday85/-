from ecosystem.github_access import RepositoryAccessPolicy


def test_registered_active_repositories_are_readable():
    policy = RepositoryAccessPolicy()
    assert policy.can_read("skyday85/fleet-management").allowed
    assert policy.can_read("skyday85/finance-planning").allowed


def test_unknown_repository_is_denied_by_default():
    policy = RepositoryAccessPolicy()
    decision = policy.can_read("skyday85/random-project")
    assert decision.allowed is False
    assert decision.reason == "repository_not_registered"


def test_direct_main_write_is_denied():
    policy = RepositoryAccessPolicy()
    decision = policy.can_write("skyday85/fleet-management", "main", path="src/app/page.tsx")
    assert decision.allowed is False
    assert decision.reason == "protected_branch"


def test_feature_branch_write_is_allowed_for_active_project():
    policy = RepositoryAccessPolicy()
    decision = policy.can_write("skyday85/fleet-management", "feature/agent-integration", path="src/lib/agent.ts")
    assert decision.allowed is True


def test_sensitive_files_are_never_written_by_main_agent():
    policy = RepositoryAccessPolicy()
    assert policy.can_write("skyday85/fleet-management", "feature/x", path=".env.production").allowed is False
    assert policy.can_write("skyday85/fleet-management", "feature/x", path="certs/service.key").allowed is False
    assert policy.can_write("skyday85/fleet-management", "feature/x", path=".vercel/project.json").allowed is False


def test_planned_mail_repository_is_not_writable_until_active():
    policy = RepositoryAccessPolicy()
    decision = policy.can_write("skyday85/mail-service", "feature/mail", path="src/index.ts")
    assert decision.allowed is False
    assert decision.reason == "project_not_active"
