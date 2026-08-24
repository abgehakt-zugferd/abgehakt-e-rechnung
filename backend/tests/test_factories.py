"""Wächter: zentrale Factories tragen alle Felder, die die Stub-Nutzer brauchen (#40)."""
from tests import factories


def test_company_stub_traegt_alle_pflichtfelder():
    stub = factories.company_stub()
    for field in factories.COMPANY_STUB_FIELDS:
        assert hasattr(stub, field), f"company_stub fehlt Feld {field!r}"


def test_customer_stub_traegt_alle_pflichtfelder():
    stub = factories.customer_stub()
    for field in factories.CUSTOMER_STUB_FIELDS:
        assert hasattr(stub, field), f"customer_stub fehlt Feld {field!r}"


def test_validator_und_zugferd_invoice_stub_teilen_kernfelder():
    for field in factories.INVOICE_STUB_FIELDS:
        assert hasattr(factories.validator_invoice_stub(), field)
        assert hasattr(factories.zugferd_invoice_stub(), field)
