from finance.banking import BankingModule


def test_high_confidence_internal_ip_proposal_still_requires_user_confirmation():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-ip-1",
            "date": "2026-09-10",
            "amount": "250000.00",
            "direction": "expense",
            "counterparty_name": "ИП Гурьянов Олег Владимирович",
            "purpose": "Перевод денежных средств",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-ip-1")

    assert proposal["operation_type"] == "internal_ip_funding"
    assert proposal["category"] == "ИП"
    assert proposal["confidence"] >= 0.95
    assert proposal["review_status"] == "needs_review"
    assert proposal["confirmed_by_user"] is False
    assert len(banking.get_needs_review()) == 1

    confirmed = banking.confirm_classification("tx-ip-1")
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["confirmed_by_user"] is True
    assert banking.get_needs_review() == []


def test_external_client_income_is_revenue_proposal_not_internal_transfer():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-client-1",
            "date": "2026-09-10",
            "amount": "175000.00",
            "direction": "income",
            "counterparty_name": "ООО Экспресс Экспедиция",
            "purpose": "Оплата транспортных услуг",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-client-1")

    assert proposal["operation_type"] == "customer_revenue"
    assert proposal["category"] == "Выручка"
    assert proposal["review_status"] == "needs_review"


def test_fuel_payment_is_advance_not_actual_fuel_consumption():
    banking = BankingModule()
    banking.import_transactions([
        {
            "transaction_id": "tx-fuel-1",
            "date": "2026-09-10",
            "amount": "100000.00",
            "direction": "expense",
            "counterparty_name": "Топливная компания",
            "purpose": "Пополнение топливной карты дизель",
        }
    ])

    proposal = banking.classify_bank_transaction("tx-fuel-1")

    assert proposal["operation_type"] == "supplier_advance_or_fuel_payment"
    assert proposal["category"] == "ГСМ: аванс/пополнение"
    assert "не фактическим расходом топлива" in proposal["rationale"]
    assert proposal["review_status"] == "needs_review"
