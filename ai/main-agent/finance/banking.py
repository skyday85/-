from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class BankTransaction:
    transaction_id: str
    date: str
    amount: Decimal
    direction: str  # income | expense
    counterparty_name: str
    purpose: str
    bank_reference: Optional[str] = None


@dataclass
class TransactionClassification:
    transaction_id: str
    operation_type: str
    category: Optional[str]
    confidence: float
    review_status: str  # needs_review | confirmed
    rationale: str
    confirmed_by_user: bool = False


class BankingModule:
    """Financial core v0.2.

    Raw bank transactions are immutable inputs. Automatic rules only create a
    proposal. In the initial operating mode every proposal requires explicit
    user confirmation before it can be treated as a final classification.
    """

    INTERNAL_IP_NAMES = (
        "ип гурьянов о.в",
        "ип гурьянов олег владимирович",
    )
    EXTERNAL_CLIENT_NAMES = (
        "ооо экспресс экспедиция",
        "экспресс экспедиция",
    )

    def __init__(self) -> None:
        self.transactions: List[BankTransaction] = []
        self.classifications: Dict[str, TransactionClassification] = {}

    def import_transactions(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        imported: List[Dict[str, Any]] = []
        known_ids = {t.transaction_id for t in self.transactions}

        for row in rows:
            tx_id = str(row["transaction_id"]).strip()
            if tx_id in known_ids:
                continue

            tx = BankTransaction(
                transaction_id=tx_id,
                date=str(row["date"]),
                amount=Decimal(str(row["amount"])),
                direction=str(row["direction"]).lower(),
                counterparty_name=str(row.get("counterparty_name", "")).strip(),
                purpose=str(row.get("purpose", "")).strip(),
                bank_reference=row.get("bank_reference"),
            )
            if tx.direction not in {"income", "expense"}:
                raise ValueError(f"Unsupported direction: {tx.direction}")

            self.transactions.append(tx)
            known_ids.add(tx_id)
            imported.append(self._serialize_transaction(tx))

        return imported

    def get_bank_transactions(self) -> List[Dict[str, Any]]:
        return [self._serialize_transaction(t) for t in self.transactions]

    def classify_bank_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """Create a classification proposal; never auto-confirm it."""
        tx = self._get_transaction(transaction_id)
        text = f"{tx.counterparty_name} {tx.purpose}".lower()

        operation_type = "unclassified"
        category: Optional[str] = None
        confidence = 0.0
        rationale = "Не найдено надёжного правила классификации."

        if any(name in text for name in self.INTERNAL_IP_NAMES):
            operation_type = "internal_ip_funding"
            category = "ИП"
            confidence = 0.98
            rationale = (
                "Контрагент распознан как связанное ИП. Перевод является внутренним "
                "финансированием ИП-контура, а не конечным расходом компании."
            )
        elif tx.direction == "income" and any(name in text for name in self.EXTERNAL_CLIENT_NAMES):
            operation_type = "customer_revenue"
            category = "Выручка"
            confidence = 0.98
            rationale = (
                "ООО «Экспресс Экспедиция» распознано как внешний клиент; поступление "
                "предлагается учитывать как выручку от транспортных услуг."
            )
        else:
            rules = [
                (("азс", "топлив", "дизел", "бензин"), "supplier_advance_or_fuel_payment", "ГСМ: аванс/пополнение"),
                (("страх", "осаго"), "insurance_payment", "Страхование"),
                (("налог", "фнс", "казнач"), "tax_payment", "Налоги"),
                (("зарплат", "заработн"), "payroll", "Зарплата"),
                (("комисси", "рко"), "bank_fee", "Банковские расходы"),
                (("возврат",), "refund", None),
                (("запчаст", "детал"), "supplier_advance_or_parts_payment", "Запчасти: оплата/аванс"),
            ]

            for keywords, op_type, cat in rules:
                matched = [k for k in keywords if k in text]
                if matched:
                    operation_type = op_type
                    category = cat
                    confidence = min(0.95, 0.65 + 0.1 * len(matched))
                    rationale = f"Совпали ключевые признаки: {', '.join(matched)}."
                    if op_type == "supplier_advance_or_fuel_payment":
                        rationale += " Платёж является денежным авансом/пополнением, а не фактическим расходом топлива."
                    break

            if tx.direction == "income" and operation_type == "unclassified":
                operation_type = "customer_or_other_income"
                confidence = 0.45
                rationale = "Операция является поступлением, но назначение требует проверки."

        result = TransactionClassification(
            transaction_id=transaction_id,
            operation_type=operation_type,
            category=category,
            confidence=confidence,
            review_status="needs_review",
            rationale=rationale,
            confirmed_by_user=False,
        )
        self.classifications[transaction_id] = result
        return asdict(result)

    def confirm_classification(
        self,
        transaction_id: str,
        *,
        operation_type: Optional[str] = None,
        category: Optional[str] = None,
        rationale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicit confirmation boundary used after user review."""
        current = self.classifications.get(transaction_id)
        if current is None:
            current = TransactionClassification(
                transaction_id=transaction_id,
                operation_type="unclassified",
                category=None,
                confidence=0.0,
                review_status="needs_review",
                rationale="Классификация создана вручную при подтверждении.",
            )
        self._get_transaction(transaction_id)
        if operation_type is not None:
            current.operation_type = operation_type
        if category is not None:
            current.category = category
        if rationale is not None:
            current.rationale = rationale
        current.review_status = "confirmed"
        current.confirmed_by_user = True
        self.classifications[transaction_id] = current
        return asdict(current)

    def get_needs_review(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for tx in self.transactions:
            classification = self.classifications.get(tx.transaction_id)
            if classification is None or classification.review_status != "confirmed":
                item = self._serialize_transaction(tx)
                item["classification"] = asdict(classification) if classification else None
                result.append(item)
        return result

    def get_confirmed(self) -> List[Dict[str, Any]]:
        return [
            asdict(item)
            for item in self.classifications.values()
            if item.review_status == "confirmed"
        ]

    def _get_transaction(self, transaction_id: str) -> BankTransaction:
        for tx in self.transactions:
            if tx.transaction_id == transaction_id:
                return tx
        raise KeyError(f"Bank transaction not found: {transaction_id}")

    @staticmethod
    def _serialize_transaction(tx: BankTransaction) -> Dict[str, Any]:
        data = asdict(tx)
        data["amount"] = str(tx.amount)
        return data
