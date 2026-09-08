from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    name: str
    domain: str
    responsibilities: tuple[str, ...]
    can_write: bool
    requires_main_agent: bool = True
    status: str = "planned"


DEFAULT_AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        agent_id="buyer",
        name="Закупщик",
        domain="procurement",
        responsibilities=("part_search", "applicability_check", "supplier_requests", "offer_comparison", "purchase_tracking"),
        can_write=True,
        status="active_design",
    ),
    AgentDefinition(
        agent_id="mail_collector",
        name="Сборщик писем",
        domain="communications",
        responsibilities=("mail_intake", "attachment_extraction", "invoice_detection", "request_detection", "routing"),
        can_write=False,
        status="active_design",
    ),
    AgentDefinition(
        agent_id="finance",
        name="Финансовый агент",
        domain="finance",
        responsibilities=("cashflow", "classification_proposal", "invoice_matching", "forecast", "plan_fact"),
        can_write=True,
        status="active_design",
    ),
    AgentDefinition(
        agent_id="sales",
        name="Агент продаж",
        domain="sales",
        responsibilities=("lead_qualification", "deal_support", "proposal_support", "pipeline_control", "follow_up"),
        can_write=True,
        status="planned",
    ),
    AgentDefinition(
        agent_id="marketing",
        name="Маркетинговый агент",
        domain="marketing",
        responsibilities=("campaign_analysis", "lead_source_analysis", "content_planning", "funnel_analysis", "marketing_tasks"),
        can_write=True,
        status="planned",
    ),
)


class AgentRegistry:
    def __init__(self, agents: Iterable[AgentDefinition] = DEFAULT_AGENTS) -> None:
        self._agents: Dict[str, AgentDefinition] = {agent.agent_id: agent for agent in agents}

    def list_agents(self) -> List[dict]:
        return [asdict(agent) for agent in self._agents.values()]

    def get(self, agent_id: str) -> Optional[AgentDefinition]:
        return self._agents.get(agent_id)

    def find_for_capability(self, capability: str) -> List[dict]:
        result = []
        for agent in self._agents.values():
            if capability in agent.responsibilities:
                result.append(asdict(agent))
        return result
