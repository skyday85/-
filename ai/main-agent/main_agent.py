from typing import Any, Dict, Optional, Protocol

from connectors.fleet_connector import FleetConnector


SYSTEM_PROMPT = """
Ты — Главный ИИ-агент всей цифровой экосистемы организации.

Твоя роль — центральный оркестратор. Ты анализируешь информацию из подключённых приложений,
связываешь данные между доменами, делегируешь работу специализированным агентам, контролируешь
сквозные бизнес-процессы, план/факт, риски, сроки и качество данных. Ты не являешься частью
автопарка, финансов, почты или другого отдельного приложения и не заменяешь их бизнес-логику.

Подключаемые домены:
- Управление автопарком;
- Финансы и планирование;
- Почтовый сервис и документооборот;
- Закупки и агент «Закупщик»;
- Продажи;
- Маркетинг;
- будущие приложения, зарегистрированные в реестре проектов.

Правила:
1. Не придумывай факты, идентификаторы, цены, документы, статьи, контрагентов или результаты операций.
2. Бизнес-приложения являются владельцами своих данных. Получай и изменяй данные через разрешённые,
   версионируемые API/инструменты, а не через прямой доступ к их БД.
3. Используй реестр проектов и агентов для выбора домена, приложения и специализированного агента.
4. Сохраняй сквозной business_case_id, если операция проходит через несколько приложений.
5. Любые неуверенные связи между сущностями помечай needs_review вместо автоматического подтверждения.
6. Финансовая классификация до включения доверенного режима требует подтверждения пользователя.
7. Существенные изменения согласованных бизнес-правил, планов и финансовой методологии требуют
   подтверждения пользователя. Технические изменения в согласованной архитектуре могут выполняться
   в разрешённых feature-ветках с тестами и Pull Request.
8. Репозитории приложений можно читать только если они зарегистрированы и выдан доступ.
9. Изменения исходного кода выполняй только в разрешённых рабочих ветках. Не обходи защиту main,
   не переписывай историю, не удаляй репозитории и не получай доступ к секретам.
10. Репозиторий Главного агента хранит оркестрацию, контракты, коннекторы, агентный реестр,
    планирование и аналитику. Предметная логика приложений остаётся в их репозиториях.
11. Почтовый сервис хранит OAuth, токены, синхронизацию, письма и вложения в собственном приложении.
    Агент «Сборщик писем» анализирует и маршрутизирует события под управлением Главного агента.
12. Подбор запчастей и закупка — разные процессы. Сначала идентификация и применяемость,
    затем предложения поставщиков и закупка.
13. Для ГАЗ при возможности начинай поиск оригинальных номеров с Detali15, затем проверяй по другим
    официальным и рабочим каталогам. Сохраняй источник и доказательство применяемости.
14. Не допускай двойного учёта одной суммы между приложениями. Источник финансовой истины и источник
    эксплуатационной истины должны быть явно определены интеграционным контрактом.
15. При межпроектной задаче сначала собери факты из всех затронутых приложений, затем сформируй
    согласованный план действий и только после этого выполняй разрешённые записи.
16. Главный агент обязан журналировать изменяющие действия: agent_id, пользователь/инициатор,
    проект, действие, объект, результат и время.
17. Критические функции независимого Security Control («Красная кнопка») недоступны Главному агенту.
    Он не может отключать защитный контур, выполнять полное удаление данных или обходить его права.
18. Если нужный проект или инструмент не зарегистрирован либо недоступен, не подменяй его догадкой:
    сообщи об ограничении и сформируй безопасный следующий шаг.
""".strip()


class AgentConnector(Protocol):
    def get_fleet(self) -> list[Dict[str, Any]]: ...
    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]: ...
    def get_vehicle_history(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def get_repairs(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def create_repair(self, vehicle_id: str, problem: str,
                      mileage: Optional[int] = None,
                      notes: Optional[str] = None) -> Dict[str, Any]: ...
    def get_maintenance_status(self, vehicle_id: str) -> Dict[str, Any]: ...
    def get_vehicle_documents(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def get_fuel_transactions(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def get_vehicle_parts(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def get_vehicle_purchases(self, vehicle_id: str) -> list[Dict[str, Any]]: ...
    def get_attention_items(self) -> list[Dict[str, Any]]: ...
    def get_vehicle_overview(self, vehicle_id: str) -> Dict[str, Any]: ...


class MainAgent:
    def __init__(self, fleet: AgentConnector):
        self.fleet = fleet

    @staticmethod
    def _payload(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not record:
            return None
        return record.get("payload", record)

    def resolve_vehicle(self, text: str) -> Optional[Dict[str, Any]]:
        normalized = text.lower().replace(" ", "")
        matches = []

        for wrapped in self.fleet.get_fleet():
            vehicle = self._payload(wrapped) or {}
            keys = [
                vehicle.get("plate_number"),
                vehicle.get("vin"),
                vehicle.get("brand"),
                vehicle.get("model"),
            ]
            if any(
                value and str(value).lower().replace(" ", "") in normalized
                for value in keys
            ):
                matches.append(vehicle)

        return matches[0] if len(matches) == 1 else None

    def handle(self, text: str) -> Dict[str, Any]:
        """MVP command router. LLM tool calling will replace keyword routing."""
        lower = text.lower()
        vehicle = self.resolve_vehicle(text)

        if any(x in lower for x in ["автопарк", "какие машины", "вся техника"]):
            return {"action": "get_fleet", "result": self.fleet.get_fleet()}

        if any(x in lower for x in ["требует внимания", "что требует", "внимания"]):
            return {"action": "get_attention_items", "result": self.fleet.get_attention_items()}

        if not vehicle and any(x in lower for x in [
            "ремонт", "история", "то ", "техобслуж", "документ", "дк", "осаго",
            "пропуск", "топлив", "заправ", "запчаст", "детал", "закуп", "что по"
        ]):
            return {"action": "need_vehicle", "result": "Не удалось однозначно определить технику."}

        if vehicle:
            vehicle_id = vehicle["vehicle_id"]

            if any(x in lower for x in ["что по", "полная информация", "сводка"]):
                return {"action": "get_vehicle_overview", "result": self.fleet.get_vehicle_overview(vehicle_id)}

            if any(x in lower for x in ["создай ремонт", "открой ремонт", "зарегистрируй ремонт"]):
                return {"action": "create_repair", "result": self.fleet.create_repair(vehicle_id, problem=text)}

            if any(x in lower for x in ["ремонт", "неисправ", "стук", "шум", "сломал"]):
                return {"action": "get_repairs", "result": self.fleet.get_repairs(vehicle_id)}

            if any(x in lower for x in ["история", "что меняли", "что делали"]):
                return {"action": "get_vehicle_history", "result": self.fleet.get_vehicle_history(vehicle_id)}

            if any(x in lower for x in ["то ", "техобслуж", "следующее то", "до то"]):
                return {"action": "get_maintenance_status", "result": self.fleet.get_maintenance_status(vehicle_id)}

            if any(x in lower for x in ["документ", "дк", "осаго", "пропуск"]):
                return {"action": "get_vehicle_documents", "result": self.fleet.get_vehicle_documents(vehicle_id)}

            if any(x in lower for x in ["топлив", "заправ", "расход"]):
                return {"action": "get_fuel_transactions", "result": self.fleet.get_fuel_transactions(vehicle_id)}

            if any(x in lower for x in ["запчаст", "детал", "артикул"]):
                return {"action": "get_vehicle_parts", "result": self.fleet.get_vehicle_parts(vehicle_id)}

            if any(x in lower for x in ["закуп", "заказ поставщик", "что ждём"]):
                return {"action": "get_vehicle_purchases", "result": self.fleet.get_vehicle_purchases(vehicle_id)}

            return {"action": "get_vehicle", "result": self.fleet.get_vehicle(vehicle_id)}

        return {
            "action": "unknown",
            "result": "Запрос понят не полностью. Следующий этап — подключить LLM с вызовом инструментов.",
        }


def build_main_agent(fleet_backend: Any) -> MainAgent:
    return MainAgent(FleetConnector(fleet_backend))
