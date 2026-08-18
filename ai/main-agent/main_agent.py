from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime

SYSTEM_PROMPT = """
Ты — Главный ИИ-агент проекта «Управление автопарком».
Твоя задача — понимать запрос пользователя, определять нужную единицу техники,
получать данные только через доступные инструменты, выполнять разрешённые действия
и возвращать краткий практичный результат.

Правила:
1. Не придумывай VIN, пробег, ремонты, документы, цены и артикулы.
2. Если нужна информация — сначала получи её через инструмент.
3. Перед изменением данных убедись, что техника определена однозначно.
4. Для вопросов по истории используй get_vehicle_history.
5. Для ремонтов используй get_repairs или create_repair.
6. Для общего контроля используй get_attention_items.
7. Если техника не определена, используй get_fleet и сопоставь её по госномеру, VIN,
   марке, модели или контексту пользователя.
8. В будущем специализированные задачи могут передаваться другим агентам.
""".strip()


@dataclass
class Vehicle:
    vehicle_id: str
    type: str
    brand: str
    model: str
    vin: str
    plate_number: str
    status: str = "active"
    current_mileage: Optional[int] = None


class FleetTools:
    """Временная in-memory реализация инструментов Главного агента.
    Позже методы заменяются вызовами реального Backend API / БД.
    """

    def __init__(self):
        self.vehicles: List[Vehicle] = [
            Vehicle("gaz-s714", "truck", "ГАЗ", "3010GD", "XZV3010GDN0001523", "С714РК797", current_mileage=None),
            Vehicle("gaz-u110", "truck", "ГАЗ", "3010GD", "XZV3010GDM0001063", "У110РМ797", current_mileage=None),
            Vehicle("gaz-r875", "truck", "ГАЗ", "LUIDOR 3010GD", "Z783010GDL0063098", "Р875УХ797", current_mileage=None),
            Vehicle("kamaz-e238", "tractor", "КАМАЗ", "5490-S5", "XTC549005K2529597", "Е238РС797", current_mileage=None),
            Vehicle("tonar-e065", "trailer", "ТОНАР", "9888", "X0T988800L0000664", "Е0657977", current_mileage=None),
        ]
        self.repairs: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []

    def get_fleet(self) -> List[Dict[str, Any]]:
        return [asdict(v) for v in self.vehicles]

    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        vehicle = next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)
        if not vehicle:
            return None
        data = asdict(vehicle)
        data.update({
            "engine": None,
            "last_mileage_date": None,
            "diagnostic_card_until": None,
            "moscow_pass_until": None,
            "notes": None,
        })
        return data

    def get_vehicle_history(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [x for x in self.history if x.get("vehicle_id") == vehicle_id]

    def get_repairs(self, vehicle_id: str) -> List[Dict[str, Any]]:
        return [x for x in self.repairs if x.get("vehicle_id") == vehicle_id]

    def get_attention_items(self) -> List[Dict[str, Any]]:
        # Пока заглушка. Позже здесь будет расчёт ТО, документов, ремонтов и закупок.
        return []

    def create_repair(
        self,
        vehicle_id: str,
        problem: str,
        mileage: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.get_vehicle(vehicle_id):
            raise ValueError("Техника не найдена")

        repair_id = f"R-{len(self.repairs)+1:05d}"
        item = {
            "repair_id": repair_id,
            "vehicle_id": vehicle_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "problem": problem,
            "status": "Новый",
            "mileage": mileage,
            "notes": notes,
            "work_performed": None,
            "parts_required": [],
            "parts_installed": [],
            "cost": None,
            "completed_at": None,
        }
        self.repairs.append(item)
        self.history.append({
            "event_id": f"E-{len(self.history)+1:05d}",
            "vehicle_id": vehicle_id,
            "date": item["created_at"],
            "event_type": "repair_created",
            "description": problem,
            "mileage": mileage,
            "repair_id": repair_id,
            "parts": [],
            "cost": None,
            "documents": [],
        })
        return item


class MainAgent:
    def __init__(self, tools: FleetTools):
        self.tools = tools

    def resolve_vehicle(self, text: str) -> Optional[Dict[str, Any]]:
        t = text.lower().replace(" ", "")
        matches = []
        for vehicle in self.tools.get_fleet():
            keys = [
                vehicle["plate_number"], vehicle["vin"], vehicle["brand"], vehicle["model"]
            ]
            if any(k and k.lower().replace(" ", "") in t for k in keys):
                matches.append(vehicle)
        return matches[0] if len(matches) == 1 else None

    def handle(self, text: str) -> Dict[str, Any]:
        """Простейший маршрутизатор для MVP.
        Позже это место заменит LLM с tool calling.
        """
        lower = text.lower()
        vehicle = self.resolve_vehicle(text)

        if "автопарк" in lower or "какие машины" in lower or "вся техника" in lower:
            return {"action": "get_fleet", "result": self.tools.get_fleet()}

        if any(x in lower for x in ["требует внимания", "что требует", "внимания"]):
            return {"action": "get_attention_items", "result": self.tools.get_attention_items()}

        if any(x in lower for x in ["ремонт", "неисправ", "стук", "шум", "сломал"]):
            if not vehicle:
                return {"action": "need_vehicle", "result": "Не удалось однозначно определить технику."}
            if any(x in lower for x in ["создай", "открой", "зарегистрируй"]):
                repair = self.tools.create_repair(vehicle["vehicle_id"], problem=text)
                return {"action": "create_repair", "result": repair}
            return {"action": "get_repairs", "result": self.tools.get_repairs(vehicle["vehicle_id"])}

        if any(x in lower for x in ["история", "что меняли", "что делали"]):
            if not vehicle:
                return {"action": "need_vehicle", "result": "Не удалось однозначно определить технику."}
            return {"action": "get_vehicle_history", "result": self.tools.get_vehicle_history(vehicle["vehicle_id"])}

        if vehicle:
            return {"action": "get_vehicle", "result": self.tools.get_vehicle(vehicle["vehicle_id"])}

        return {
            "action": "unknown",
            "result": "Запрос понят не полностью. Следующий этап — подключить LLM с вызовом инструментов."
        }


if __name__ == "__main__":
    tools = FleetTools()
    agent = MainAgent(tools)
    print("Главный агент MVP запущен. Для выхода: exit")
    while True:
        q = input("> ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        print(agent.handle(q))
