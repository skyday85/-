from finance.banking import BankingModule


def test_high_confidence_rule_still_requires_user_confirmation():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-1",
            "date": "2026-09-08",
            "amount": "150000.00",
            "direction": "expense",
            "counterparty_name": "ИП Гурьянов Олег Владимирович",
            "purpose": "Перевод средств",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-1")

    assert proposal["operation_type"] == "internal_ip_funding"
    assert proposal["category"] == "ИП"
    assert proposal["confidence"] >= 0.95
    assert proposal["review_status"] == "needs_review"
    assert proposal["confirmed_by_user"] is False

    confirmed = banking.confirm_classification("tx-1")
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["confirmed_by_user"] is True
    assert banking.get_needs_review() == []


def test_express_expedition_income_is_proposed_as_external_client_revenue():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-2",
            "date": "2026-09-08",
            "amount": "250000.00",
            "direction": "income",
            "counterparty_name": "ООО Экспресс Экспедиция",
            "purpose": "Оплата транспортных услуг",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-2")

    assert proposal["operation_type"] == "customer_revenue"
    assert proposal["category"] == "Выручка"
    assert proposal["review_status"] == "needs_review"


def test_fuel_payment_is_advance_not_actual_fuel_expense():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-3",
            "date": "2026-09-08",
            "amount": "80000.00",
            "direction": "expense",
            "counterparty_name": "Топливная компания",
            "purpose": "Пополнение топливной карты, дизель",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-3")

    assert proposal["operation_type"] == "supplier_advance_or_fuel_payment"
    assert proposal["category"] == "ГСМ: аванс/пополнение"
    assert proposal["review_status"] == "needs_review"
    assert "не фактическим расходом топлива" in proposal["rationale"]
