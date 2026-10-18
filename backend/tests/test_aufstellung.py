"""Modell und Datenbank-Invarianten der Abrechnungsaufstellung (Bauschritt 7a).

Entscheidung 8 aus docs/specs/rechnungs-und-aufstellungsauftrag.md: Die
Aufstellung ist KEINE Rechnung — keine Steuer, kein Typcode, keine XML, kein
Mustang. Sie bildet die Invarianten der Rechnung in einer EIGENEN Tabelle
nach (Nummer beim Entwurf, Sperre des Auftragsschluessels, Unver-
aenderlichkeit nach dem Stellen), ohne die Rechnung zu verbiegen. Die
CHECKs stehen deshalb hier in der Datenbank und nicht nur im Code: Sie
gelten auch fuer psql, Skripte und die Migration einer fremden Installation.
"""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.models.invoice import AuditLog
from tests.factories_aufstellung import orm_anlage, orm_aufstellung

SCHLUESSEL = "plattform:2026-09:kanal-a:x1"


def _aufstellung(pg_session, **over):
    a = orm_aufstellung(**over)
    pg_session.add(a)
    pg_session.commit()
    return a


def _frisch(pg_session, a):
    pg_session.expire_all()
    return pg_session.query(Aufstellung).filter(Aufstellung.id == a.id).one()


# ── Wertevorraete und Summen als DB-CHECKs ────────────────────────────────────

def test_status_kennt_nur_vier_werte(pg_session):
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(status="bezahlt"))
        pg_session.commit()
    pg_session.rollback()


def test_brutto_minus_quellensteuer_gleicht_netto(pg_session):
    """Die Gleichung § 8b (brutto − quellensteuer == netto) ist keine
    Empfehlung an den Aufrufer, sondern Invariante der Zeile."""
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(
            brutto=Decimal("1000.00"), quellensteuer=Decimal("80.00"),
            netto=Decimal("999.00")))
        pg_session.commit()
    pg_session.rollback()


def test_eur_hat_weder_kurs_noch_zahlbetrag(pg_session):
    """Festlegung 21: Abgehakt rechnet keinen Wert in Euro um. Bei Berichts-
    waehrung EUR sind kurs und zahlbetrag_e leer — ein eingetragener Kurs
    waere eine Angabe, die niemand geprueft hat."""
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(kurs=Decimal("1.0000")))
        pg_session.commit()
    pg_session.rollback()


def test_fremdwaehrung_traegt_die_umrechnung(pg_session):
    a = _aufstellung(
        pg_session,
        waehrung="USD",
        kurs=Decimal("0.92"),
        zahlbetrag_eur=Decimal("846.40"),
    )
    assert _frisch(pg_session, a).waehrung == "USD"

    with pytest.raises(IntegrityError):
        # Fremdwaehrung ohne Umrechnung ist ein Bericht, dessen Zahlbetrag
        # niemand kennt.
        pg_session.add(orm_aufstellung(
            waehrung="USD", brutto=Decimal("10.00"), quellensteuer=Decimal("0.00"),
            netto=Decimal("10.00")))
        pg_session.commit()
    pg_session.rollback()


# ── Anlagen: genau zwei, jede Quelle einmal, Hash in Form ────────────────────

def test_anlagenquelle_kennt_nur_die_berichte(pg_session):
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(
            anlagen=[orm_anlage(quelle="rechnung")]))
        pg_session.commit()
    pg_session.rollback()


def test_anlagenhash_ist_kleinhex(pg_session):
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(
            anlagen=[orm_anlage(sha256="X" * 64)]))
        pg_session.commit()
    pg_session.rollback()


def test_je_quelle_eine_anlage_pro_aufstellung(pg_session):
    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(
            anlagen=[orm_anlage("abrechnungsbericht"),
                     orm_anlage("abrechnungsbericht")]))
        pg_session.commit()
    pg_session.rollback()


def test_beide_berichte_lassen_sich_anlegen(pg_session):
    a = _aufstellung(pg_session, anlagen=[
        orm_anlage("abrechnungsbericht"), orm_anlage("zahlungsbericht")])

    assert len(_frisch(pg_session, a).anlagen) == 2


# ── Auftragsschluessel: Sperre wie bei der Rechnung ──────────────────────────

def test_zwei_aufstellungen_sperren_nicht_denselben_schluessel(pg_session):
    _aufstellung(pg_session, schluessel=SCHLUESSEL)

    with pytest.raises(IntegrityError):
        pg_session.add(orm_aufstellung(schluessel=SCHLUESSEL))
        pg_session.commit()
    pg_session.rollback()


def test_die_sperre_muss_dem_nachweis_gleichen(pg_session):
    a = _aufstellung(pg_session, schluessel=SCHLUESSEL)
    with pytest.raises(IntegrityError):
        pg_session.execute(
            Aufstellung.__table__.update()
            .where(Aufstellung.id == a.id)
            .values(auftragsschluessel_offen="fremd:key")
        )
    pg_session.rollback()


# ── Audit: jede Aenderung an der Aufstellung landet im Protokoll ─────────────

def test_einfuegen_und_aendern_werden_protokolliert(pg_session):
    a = orm_aufstellung()
    pg_session.add(a)
    pg_session.commit()

    a.bemerkung = "Nachtrag des Kunden"
    pg_session.commit()

    einfuegen = (pg_session.query(AuditLog)
                 .filter_by(table_name="aufstellungen", action="insert")
                 .filter_by(record_id=str(a.id)).one())
    aendern = (pg_session.query(AuditLog)
               .filter_by(table_name="aufstellungen", action="update")
               .filter_by(record_id=str(a.id)).one())
    assert einfuegen.new_values["nummer"] == a.nummer
    assert aendern.old_values == {"bemerkung": None}
    assert aendern.new_values == {"bemerkung": "Nachtrag des Kunden"}


def test_anlagen_stehen_im_protokoll(pg_session):
    """Anders als die Rechnungsposition ist die Anlage ein gepruefter
    Dateinachweis (Hash und Groesse): Ihre Aenderung gehoert ins Protokoll."""
    a = _aufstellung(pg_session, anlagen=[orm_anlage()])

    anlage = (pg_session.query(AufstellungAnlage)
              .filter(AufstellungAnlage.aufstellung_id == a.id).one())
    assert (pg_session.query(AuditLog)
            .filter_by(table_name="aufstellung_anlagen",
                       record_id=str(anlage.id)).one().action == "insert")
