from typing import Any, Dict, Optional, Protocol

from connectors.fleet_connector import FleetConnector


SYSTEM_PROMPT = """
Ты — Главный ИИ-агент экосистемы организации.
На текущем этапе к тебе подключено приложение «Управление автопарком».

Твоя задача — понимать запрос пользователя, определять нужную единицу техники,
получать данные только через FleetConnector, выполнять разрешённые действия
и возвращать краткий практичный результат.

Правила:
1. Не придумывай VIN, пробег, ремонты, документы, цены, статьи или артикулы.
2. Не обращайся к БД автопарка напрямую — только через FleetConnector.
3. Перед изменением данных убедись, что техника определена однозначно.
4. Для истории используй get_vehicle_history.
5. Для ремонтов используй get_repairs или create_repair.
6. Для ТО используй get_maintenance_status.
7. Для документов используй get_vehicle_documents.
8. Для топлива используй get_fuel_transactions.
9. Для запчастей используй get_vehicle_parts.
10. Для закупок используй get_vehicle_purchases.
11. Для общего контроля используй get_attention_items.
12. Если пользователь спрашивает «что по машине» — используй get_vehicle_overview.
13. Если техника не определена, используй get_fleet и сопоставь её по госномеру,
    VIN, марке или модели.
14. Другие приложения экосистемы будут подключаться позже отдельными коннекторами.
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
        """MVP-маршрутизатор.

        Позже его заменит LLM tool calling, но бизнес-доступ уже идёт через коннектор.
        """
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
                return {
                    "action": "create_repair",
                    "result": self.fleet.create_repair(vehicle_id, problem=text),
                }

            if any(x in lower for x in ["ремонт", "неисправ", "стук", "шум", "сломал"]):
                return {"action": "get_repairs", "result": self.fleet.get_repairs(vehicle_id)}

            if any(x in lower for x in ["история", "что меняли", "что делали"]):
                return {
                    "action": "get_vehicle_history",
                    "result": self.fleet.get_vehicle_history(vehicle_id),
                }

            if any(x in lower for x in ["то ", "техобслуж", "следующее то", "до то"]):
                return {
                    "action": "get_maintenance_status",
                    "result": self.fleet.get_maintenance_status(vehicle_id),
                }

            if any(x in lower for x in ["документ", "дк", "осаго", "пропуск"]):
                return {
                    "action": "get_vehicle_documents",
                    "result": self.fleet.get_vehicle_documents(vehicle_id),
                }

            if any(x in lower for x in ["топлив", "заправ", "расход"]):
                return {
                    "action": "get_fuel_transactions",
                    "result": self.fleet.get_fuel_transactions(vehicle_id),
                }

            if any(x in lower for x in ["запчаст", "детал", "артикул"]):
                return {
                    "action": "get_vehicle_parts",
                    "result": self.fleet.get_vehicle_parts(vehicle_id),
                }

            if any(x in lower for x in ["закуп", "заказ поставщик", "что ждём"]):
                return {
                    "action": "get_vehicle_purchases",
                    "result": self.fleet.get_vehicle_purchases(vehicle_id),
                }

            return {"action": "get_vehicle", "result": self.fleet.get_vehicle(vehicle_id)}

        return {
            "action": "unknown",
            "result": "Запрос понят не полностью. Следующий этап — подключить LLM с вызовом инструментов.",
        }


def build_main_agent(fleet_backend: Any) -> MainAgent:
    """Точка сборки: backend автопарка подключается через FleetConnector."""
    return MainAgent(FleetConnector(fleet_backend))
