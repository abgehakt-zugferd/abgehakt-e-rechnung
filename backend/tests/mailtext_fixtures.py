"""Gemeinsame Einrichtung fuer Mailtext-Integrationstests."""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice


def client_fuer(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def config_setzen(pg_session, **werte):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in werte.items():
        setattr(cfg, k, v)
    pg_session.commit()
    return cfg


def firma_setzen(pg_session, **kw):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    werte = dict(
        name="Kanzlei Musterfrau",
        address_line1="Musterweg 3",
        zip_code="80331",
        city="München",
    )
    werte.update(kw)
    for k, v in werte.items():
        setattr(firma, k, v)
    pg_session.commit()
    return firma


def rechnung_anlegen(pg_session, *, document_language="de", nummer=None):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
        email="kunde@example.de",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=nummer or f"RE-MT-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 28),
        currency="EUR",
        net_total=Decimal("1000.00"),
        tax_total=Decimal("234.56"),
        gross_total=Decimal("1234.56"),
        status="issued",
        pdf_filename="RE.pdf",
        document_language=document_language,
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    return inv


def smtp_doppel():
    """Fängt die EmailMessage; gibt (gesendet-dict, SMTP-Klasse) zurück."""
    gesendet = {}

    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            gesendet["msg"] = msg
            gesendet["body"] = msg.get_body(preferencelist=("plain",)).get_content()
            gesendet["subject"] = msg["Subject"]

    return gesendet, _SMTP
