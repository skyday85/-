from pathlib import Path

import pytest

from mail_contour.mail_access import AccessDenied, MailAccessDirectory
from mail_contour.text_routing import MailTextRouter, attachment_text, message_text

ORG = "test-organization"
OTHER = "other-organization"


@pytest.fixture
def directory(tmp_path: Path):
    store = MailAccessDirectory(str(tmp_path / "mail.sqlite3"))
    store.bootstrap_owner(ORG, "boss", "boss@example.com")
    store.bootstrap_owner(OTHER, "different-boss", "different@example.com")
    store.create_user(ORG, "boss", user_id="employee", email="staff@example.com", display_name="Employee")
    store.create_user(ORG, "boss", user_id="unassigned", email="outsider@example.com", display_name="Outsider")
    store.grant_account(ORG, "boss", owner_user_id="boss", provider="gmail", account_id="work",
                        recipient_user_id="boss", address="office@example.com", can_forward=True)
    store.grant_account(ORG, "boss", owner_user_id="boss", provider="gmail", account_id="work",
                        recipient_user_id="employee", address="office@example.com", can_forward=True)
    return store


def test_admin_user_creation_and_cross_org_isolation(directory):
    assert directory.require_member(ORG, "employee")["role"] == "member"
    assert len(directory.users(ORG, "boss")) == 3
    with pytest.raises(AccessDenied):
        directory.users(ORG, "employee")
    with pytest.raises(AccessDenied):
        directory.require_member(OTHER, "employee")
    with pytest.raises(AccessDenied):
        directory.create_user(ORG, "employee", user_id="bad", display_name="bad", email="bad@example.com")
    with pytest.raises(ValueError):
        directory.create_user(ORG, "boss", user_id="bad", display_name="bad", email="example.org")


def test_assigned_mailboxes_are_private_and_revocable(directory):
    allowed = directory.assert_grant(ORG, "employee", owner="boss", provider="gmail", account_id="work", forwarding=True)
    assert allowed["address"] == "office@example.com"
    with pytest.raises(AccessDenied):
        directory.assert_grant(ORG, "unassigned", owner="boss", provider="gmail", account_id="work")
    with pytest.raises(AccessDenied):
        directory.assert_grant(OTHER, "different-boss", owner="boss", provider="gmail", account_id="work")
    directory.revoke_account(ORG, "boss", owner_user_id="boss", provider="gmail", account_id="work",
                             recipient_user_id="employee")
    with pytest.raises(AccessDenied):
        directory.assert_grant(ORG, "employee", owner="boss", provider="gmail", account_id="work")


def test_routing_reads_text_and_deduplicates_review_jobs(directory):
    rule = directory.create_rule(ORG, "boss", owner="boss", provider="gmail", account_id="work",
                                 match_text="заявка на перевозку", destination="dispatcher@example.com")
    router = MailTextRouter(directory, lambda *_: pytest.fail("No attachment expected"))
    message = {"email_id": "mail-1", "account_id": "work", "subject": "Заявка на перевозку",
               "body_text": "Москва - Казань", "attachments": []}
    first = router.inspect(organization_id=ORG, owner_user_id="boss", provider="gmail", message=message)
    second = router.inspect(organization_id=ORG, owner_user_id="boss", provider="gmail", message=message)
    assert first["jobs"][0]["job_id"] == second["jobs"][0]["job_id"]
    assert first["jobs"][0]["status"] == "pending_review"
    with pytest.raises(AccessDenied):
        directory.get_job(ORG, "unassigned", first["jobs"][0]["job_id"])
    approved = directory.claim_job(ORG, "employee", first["jobs"][0]["job_id"])
    assert approved["destination"] == rule["destination"]
    directory.finish_job(first["jobs"][0]["job_id"], success=True, provider_result="accepted")
    with pytest.raises(ValueError):
        directory.claim_job(ORG, "employee", first["jobs"][0]["job_id"])
    assert directory.get_job(ORG, "employee", first["jobs"][0]["job_id"])["status"] == "forwarded"


def test_no_routing_on_nonmatches_and_no_unauthorized_auto_forward(directory):
    rule = directory.create_rule(ORG, "boss", owner="boss", provider="gmail", account_id="work",
                                 match_text="special delivery", destination="team@example.com", mode="auto")
    router = MailTextRouter(directory, lambda *_: pytest.fail("No attachment expected"))
    assert router.inspect(organization_id=ORG, owner_user_id="boss", provider="gmail",
                          message={"email_id": "n1", "account_id": "work", "subject": "Hello",
                                   "body_text": "No orders", "attachments": []})["jobs"] == []
    data = router.inspect(organization_id=ORG, owner_user_id="boss", provider="gmail",
                          message={"email_id": "n2", "account_id": "work", "subject": "Special delivery",
                                   "body_text": "", "attachments": []})
    job_id = data["jobs"][0]["job_id"]
    with pytest.raises(AccessDenied):
        directory.claim_job(ORG, "employee", job_id, automated=True)
    assert directory.claim_job(ORG, "boss", job_id, automated=True)["mode"] == "auto"


def test_html_message_text_excludes_scripts():
    raw = message_text({"subject": "Order", "body_html": "<script>Secret ignored</script><p>Перевозка груза</p>"})
    assert "Перевозка груза" in raw
    assert "Secret ignored" not in raw


def test_attachment_text_without_ocr_never_fabricates_match(monkeypatch):
    monkeypatch.setattr("mail_contour.text_routing.shutil.which", lambda _: None)
    content, status = attachment_text(b"not-an-image", "image/png")
    assert (content, status) == ("", "ocr_unavailable")


def test_failed_ocr_creates_review_only_never_claims_auto(directory, monkeypatch):
    monkeypatch.setattr("mail_contour.text_routing.attachment_text",
                        lambda *_: ("", "ocr_unavailable"))
    directory.create_rule(ORG, "boss", owner="boss", provider="gmail", account_id="work",
                          match_text="invoice 123", destination="finance@example.com",
                          scan_attachments=True, mode="auto")
    router = MailTextRouter(directory, lambda *_: {"content_bytes": b"image"})
    data = router.inspect(organization_id=ORG, owner_user_id="boss", provider="gmail",
                          message={"email_id": "scanned-1", "account_id": "work",
                                   "subject": "Document", "body_text": "", "attachments": [
                                       {"attachment_id": "a", "filename": "scan.png", "mime_type": "image/png"}
                                   ]})
    assert data["jobs"][0]["matched_in"] == "unverified_attachment"
    assert data["recognition"][0]["status"] == "ocr_unavailable"
    assert directory.system_job(ORG, data["jobs"][0]["job_id"])["status"] == "pending_review"
