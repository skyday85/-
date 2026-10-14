from runtime import MainAgentRuntime

def test_mail_to_business_case_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "mail.sqlite3"))
    monkeypatch.setenv("MAIN_AGENT_DATABASE_PATH", str(tmp_path / "agent.sqlite3"))
    monkeypatch.delenv("INTEGRATION_GATEWAY_BASE_URL", raising=False)
    runtime = MainAgentRuntime()
    runtime.add_mail_account(user_id="owner", account_id="box1", address="owner@example.com", provider="gmail")
    runtime.ingest_mail("owner", [{"account_id": "box1", "provider_message_id": "p1",
                                   "sender": "client@example.com", "received_at": "2026-10-14T08:00:00Z",
                                   "subject": "Заявка на перевозку", "body_text": "Доставка груза"}])
    eid = runtime.unified_inbox("owner")[0]["email_id"]
    first = runtime.process_mail("owner", eid, organization_id="org1")
    second = runtime.process_mail("owner", eid, organization_id="org1")
    assert first["business_case_id"] == second["business_case_id"]
    case = runtime.get_business_case("org1", first["business_case_id"])
    assert case["case_type"] == "transport_request"
    assert len(case["links"]) == 1
    assert len(case["signals"]) == 1
    assert runtime.business_cases.ensure_from_mail("org2", "owner", eid, "Другое")["case_id"] != case["case_id"]


def test_forwarded_invoice_creates_fleet_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_API_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("FLEET_MAIN_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("MAIL_DATABASE_PATH", str(tmp_path / "mail.sqlite3"))
    monkeypatch.setenv("MAIN_AGENT_DATABASE_PATH", str(tmp_path / "agent.sqlite3"))
    monkeypatch.delenv("INTEGRATION_GATEWAY_BASE_URL", raising=False)
    runtime = MainAgentRuntime()
    runtime.add_mail_account(user_id="owner", account_id="box1", address="owner@example.com", provider="gmail")
    runtime.ingest_mail("owner", [{
        "account_id": "box1", "provider_message_id": "p2",
        "sender": "supplier@example.com", "received_at": "2026-10-14T09:00:00Z",
        "subject": "Счёт на запчасти", "body_text": "Детали",
        "attachments": [{"attachment_id": "a2", "filename": "invoice.pdf",
                          "mime_type": "application/pdf"}],
    }])
    eid = runtime.unified_inbox("owner")[0]["email_id"]
    monkeypatch.setattr(runtime, "fetch_mail_attachment",
                        lambda *a: {"filename": "invoice.pdf", "mime_type": "application/pdf",
                                   "content_bytes": b"%PDF-test"})
    monkeypatch.setattr(runtime.fleet_backend, "create_document_candidate",
                        lambda **kw: {"candidate_id": "doc-1"})
    result = runtime.process_mail("owner", eid, organization_id="org1")
    case = runtime.get_business_case("org1", result["business_case_id"])
    assert case["case_type"] == "procurement"
    assert ("fleet-management", "document_candidate", "doc-1") in {
        (x["project_id"], x["record_type"], x["record_id"]) for x in case["links"]}
    assert case["status"] == "in_progress"
