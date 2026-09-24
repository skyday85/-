from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class AppModule:
    module_id: str
    title: str
    routes: Tuple[str, ...]
    available_on: Tuple[str, ...] = ("mac", "iphone")
    requires_online: bool = True
    badge_source: Optional[str] = None


class AppShellRegistry:
    """Single navigation contract for the organization application.

    Mac and iPhone clients render different layouts over the same module and
    route registry. Business logic stays in backend services and agents.
    """

    def __init__(self):
        self._modules: Dict[str, AppModule] = {}
        self._seed()

    def _seed(self) -> None:
        modules = (
            AppModule("main_agent", "Главный агент", ("/agent",)),
            AppModule("mail", "Почта", ("/mail", "/mail/thread/:id"), badge_source="mail_unread"),
            AppModule("finance", "Финансы", ("/finance", "/finance/review"), badge_source="finance_review"),
            AppModule("fleet", "Автопарк", ("/fleet", "/fleet/vehicle/:id"), badge_source="fleet_attention"),
            AppModule("sales", "Продажи", ("/sales", "/sales/deal/:id"), badge_source="sales_attention"),
            AppModule("marketing", "Маркетинг", ("/marketing", "/marketing/campaign/:id")),
            AppModule("procurement", "Закупки", ("/procurement", "/procurement/request/:id"), badge_source="procurement_attention"),
            AppModule("tasks", "Задачи", ("/tasks",), badge_source="tasks_due"),
            AppModule("notifications", "Уведомления", ("/notifications",), badge_source="notifications_unread"),
        )
        for module in modules:
            self._modules[module.module_id] = module

    def get(self, module_id: str) -> AppModule:
        return self._modules[module_id]

    def list_modules(self, device: Optional[str] = None) -> List[AppModule]:
        modules: Iterable[AppModule] = self._modules.values()
        if device:
            modules = (module for module in modules if device in module.available_on)
        return list(modules)

    def build_client_manifest(self, device: str) -> dict:
        if device not in {"mac", "iphone"}:
            raise ValueError("Unsupported client device")
        return {
            "device": device,
            "navigation": [
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "routes": list(module.routes),
                    "badge_source": module.badge_source,
                }
                for module in self.list_modules(device)
            ],
            "backend_contract": "shared",
            "main_agent_entry": "/agent",
            "mail_entry": "/mail",
        }
