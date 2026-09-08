from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CatalogSource:
    code: str
    name: str
    url: str
    priority: int
    brands: List[str]
    source_type: str = "catalog"
    notes: Optional[str] = None


class PartsCatalogRegistry:
    """Registry of trusted parts sources used by the Main Agent / Buyer agent.

    This module stores source policy only. Actual web/API lookup is performed by
    the runtime search tool or a dedicated supplier/catalog connector.
    """

    def __init__(self) -> None:
        self.sources: Dict[str, CatalogSource] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        defaults = [
            CatalogSource(
                code="detali15",
                name="ГАЗ Детали15",
                url="https://detali15.ru/",
                priority=10,
                brands=["GAZ", "ГАЗ"],
                notes="Primary source for original GAZ part numbers when applicable.",
            ),
            CatalogSource(
                code="gaz_official",
                name="Официальный каталог ГАЗ",
                url="https://gaz.ru/",
                priority=20,
                brands=["GAZ", "ГАЗ"],
            ),
            CatalogSource(
                code="gaz_parts",
                name="ГАЗ Детали Машин",
                url="https://gaz-dm.ru/",
                priority=30,
                brands=["GAZ", "ГАЗ"],
            ),
            CatalogSource(
                code="yamz_official",
                name="ЯМЗ",
                url="https://www.ymzmotor.ru/",
                priority=20,
                brands=["YAMZ", "ЯМЗ"],
            ),
        ]
        for source in defaults:
            self.sources[source.code] = source

    def list_sources(self, brand: Optional[str] = None) -> List[dict]:
        rows = list(self.sources.values())
        if brand:
            normalized = brand.lower()
            rows = [s for s in rows if any(b.lower() in normalized or normalized in b.lower() for b in s.brands)]
        rows.sort(key=lambda item: item.priority)
        return [asdict(row) for row in rows]

    def build_search_plan(self, *, brand: str, model: Optional[str] = None,
                          vin: Optional[str] = None, query: str) -> dict:
        return {
            "query": query,
            "brand": brand,
            "model": model,
            "vin": vin,
            "sources": self.list_sources(brand),
            "requirements": [
                "identify original part number",
                "verify applicability to the exact vehicle/engine",
                "separate original numbers from analogs",
                "record source and evidence for every conclusion",
            ],
        }
