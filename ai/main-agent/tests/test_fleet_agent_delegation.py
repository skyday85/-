import io
import json
from urllib.parse import urlparse

from connectors import http_fleet_backend as fleet_module
from connectors.http_fleet_backend import HttpFleetBackend


def test_delegation_uses_dedicated_ua_endpoint(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({"taskId":"abc","status":"completed"}).encode()

    def fake_open(request, timeout=None):
        requests.append(request)
        return Response()

    monkeypatch.setattr(fleet_module, "urlopen", fake_open)
    backend = HttpFleetBackend(base_url="http://localhost:3000", api_key="test-token")
    result = backend.create_ua_agent_task(
        organization_id="org-1", message="Check maintenance", task_id="task-1")
    assert result["status"] == "completed"
    request = requests[0]
    assert request.method == "POST"
    assert urlparse(request.full_url).path == "/api/agent/ua/tasks"
    assert json.loads(request.data)["organizationId"] == "org-1"
    assert json.loads(request.data)["taskId"] == "task-1"
    assert request.get_header("X-main-agent-key") == "test-token"
