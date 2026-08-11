"""
POST /settings/smtp-test (#98 P2): der SMTP-Testversand war ungetestet. SMTP selbst
wird gemockt (kein echter Mailserver); geprüft wird die Router-Verdrahtung:
Erfolg → Redirect mit ?saved=true, EmailError → Redirect mit ?error=…
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services import datev_email


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_smtp_test_success_redirects_saved(pg_session):
    with patch.object(datev_email, "send_test_email") as send:
        r = _client(pg_session).post("/settings/smtp-test", data={"test_email": "a@b.de"})
    assert r.status_code == 303
    assert "saved=true" in r.headers["location"]
    send.assert_called_once()
    assert send.call_args.args[0] == "a@b.de"


def test_smtp_test_error_redirects_with_message(pg_session):
    with patch.object(datev_email, "send_test_email",
                      side_effect=datev_email.EmailError("SMTP nicht konfiguriert.")):
        r = _client(pg_session).post("/settings/smtp-test", data={"test_email": "a@b.de"})
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
