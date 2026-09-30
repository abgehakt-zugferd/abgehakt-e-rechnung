"""Der Steuerstatus am Importweg: ein signierter Auftrag wirkt nur fuer geklaerte Kunden.

Auch 381 braucht den geklaerten Status: die Steuer eines Entwurfs aus dem
Auftrag kommt fuer beide TypeCodes aus `steuer_fuer`, und aus `ungeklaert`
laesst sich keine ableiten. Wer Abrechnungen aus der Integration bekommt, ist
per Definition Gutschriftempfaenger. Festgeschrieben, damit das eine Absicht
ist und kein Nebeneffekt.
"""
import pytest

from app.models.invoice import Invoice
from app.services.abrechnungsauftrag_wirkung import WirkungFehler, entwuerfe_anlegen
from tests.test_abrechnungsauftrag_wirkung import (
    PARTNER_A,
    PARTNER_B,
    _gutschrift,
    _kunde,
    _urteil,
)


@pytest.mark.parametrize("typcode", ["381", "389"])
def test_ungeklaerter_kunde_wird_abgewiesen(pg_session, typcode):
    kunde = _kunde(pg_session, PARTNER_A, ust_status="ungeklaert")
    gutschrift = _gutschrift(PARTNER_A)
    gutschrift["typcode"] = typcode

    with pytest.raises(WirkungFehler, match=f"ungeklaert bei Kunde {kunde.customer_number}"):
        entwuerfe_anlegen(pg_session, _urteil([gutschrift]))


@pytest.mark.parametrize("typcode", ["381", "389"])
def test_kunde_ohne_schalter_wird_abgewiesen(pg_session, typcode):
    kunde = _kunde(pg_session, PARTNER_A)
    kunde.gutschriftempfaenger = False
    pg_session.flush()
    gutschrift = _gutschrift(PARTNER_A)
    gutschrift["typcode"] = typcode

    with pytest.raises(WirkungFehler, match="kein Gutschriftempfaenger"):
        entwuerfe_anlegen(pg_session, _urteil([gutschrift]))


def test_ein_ungeklaerter_zweiter_empfaenger_laesst_auch_den_ersten_nicht_zurueck(pg_session):
    _kunde(pg_session, PARTNER_A)
    _kunde(pg_session, PARTNER_B, ust_status="ungeklaert", name="Autor B")
    pg_session.commit()

    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(pg_session, _urteil([_gutschrift(PARTNER_A), _gutschrift(PARTNER_B, nummer=2)]))
    pg_session.rollback()

    assert pg_session.query(Invoice).count() == 0
