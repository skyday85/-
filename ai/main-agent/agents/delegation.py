from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from agents.registry import AgentRegistry


@dataclass
class DelegatedTask:
    delegation_id: str
    delegated_by: str
    delegated_to: str
    capability: str
    instruction: str
    context: Dict[str, Any]
    status: str
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class DelegationEngine:
    """Creates auditable tasks from Main Agent to specialized agents.

    Specialized agents do not become independent sources of truth. They work
    through application connectors and return results to the Main Agent.
    """

    def __init__(self, registry: Optional[AgentRegistry] = None) -> None:
        self.registry = registry or AgentRegistry()
        self.tasks: Dict[str, DelegatedTask] = {}

    def delegate(self, agent_id: str, capability: str, instruction: str,
                 context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        agent = self.registry.get(agent_id)
        if not agent:
            raise KeyError(f"Unknown specialized agent: {agent_id}")
        if capability not in agent.responsibilities:
            raise ValueError(f"Agent {agent_id} does not support capability: {capability}")

        task = DelegatedTask(
            delegation_id=str(uuid4()),
            delegated_by="main_agent",
            delegated_to=agent_id,
            capability=capability,
            instruction=instruction.strip(),
            context=context or {},
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.tasks[task.delegation_id] = task
        return asdict(task)

    def complete(self, delegation_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        task = self.tasks.get(delegation_id)
        if not task:
            raise KeyError(f"Delegation not found: {delegation_id}")
        task.status = "completed"
        task.result = result
        task.completed_at = datetime.now(timezone.utc).isoformat()
        return asdict(task)

    def get(self, delegation_id: str) -> Optional[Dict[str, Any]]:
        task = self.tasks.get(delegation_id)
        return asdict(task) if task else None

    def list_tasks(self) -> list[Dict[str, Any]]:
        return [asdict(task) for task in self.tasks.values()]
