"""Migration 030 (Bauschritt 7a, Entscheidung 8): Die Abrechnungsaufstellung
als EIGENES Modell — Tabellen, Anlagen, Nummernkreis-Felder an company,
GoBD-Trigger gegen DELETE/TRUNCATE.

Eigene Datei neben test_migrationskette.py (Muster test_migration_021_...
positionszeitraum.py): Die Kette ist schon die groesste Testdatei, und die
Aufstellung bringt ihre eigenen Helfer mit — INSERT, Anlagen, Lage-Abfrage.

Die CHECKs und Indizes werden direkt beprobt, weil sie die Zusagen auch ohne
Anwendung sichern: Die Aufstellung ist keine Rechnung, aber ihre Invarianten
(Summengleichheit, Sperre des Auftragsschluessels, Hash-Form der Anlagen)
gelten genauso wie bei ihr.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, InternalError

import pytest

from tests.test_migrationskette import migrationsdatenbank  # noqa: F401


def _aufstellungs_lage(conn):
    """Spalten, CHECKs, Indizes und GoBD-Trigger nach upgrade head."""
    def namen(sql):
        return {zeile[0] for zeile in conn.execute(text(sql))}

    return (
        namen("SELECT column_name FROM information_schema.columns "
              "WHERE table_name = 'aufstellungen'"),
        namen("SELECT column_name FROM information_schema.columns "
              "WHERE table_name = 'aufstellung_anlagen'"),
        namen("SELECT column_name FROM information_schema.columns "
              "WHERE table_name = 'company'"),
        namen("SELECT conname FROM pg_constraint "
              "WHERE conrelid = 'aufstellungen'::regclass AND contype = 'c'"),
        namen("SELECT conname FROM pg_constraint "
              "WHERE conrelid = 'aufstellung_anlagen'::regclass AND contype = 'c'"),
        namen("SELECT indexname FROM pg_indexes WHERE tablename = 'aufstellungen'"),
        namen("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
              "AND tgname LIKE 'gobd_%'"),
    )


def _aufstellung_insert(nummer: str, *, status=None, netto="920.00", kurs=None):
    """INSERT fuer eine Aufstellung; die Kundennummer K-7A-MIG muss stehen."""
    spalten = ("id, nummer, customer_id, leistung_von, leistung_bis, "
               "zahlungsnummer, zahlungsdatum, waehrung, brutto, quellensteuer, netto")
    werte = ("gen_random_uuid(), :nr, "
             "(SELECT id FROM customers WHERE customer_number = 'K-7A-MIG'), "
             "'2026-09-01', '2026-09-30', '4711', '2026-09-30', 'EUR', "
             "1000.00, 80.00, :netto")
    params = {"nr": nummer, "netto": netto}
    if status is not None:
        spalten += ", status"
        werte += ", :status"
        params["status"] = status
    if kurs is not None:
        spalten += ", kurs"
        werte += ", :kurs"
        params["kurs"] = kurs
    return text(f"INSERT INTO aufstellungen ({spalten}) VALUES ({werte})"), params


def _aufstellung_anlage_insert(quelle: str, sha256: str):
    return text(
        "INSERT INTO aufstellung_anlagen "
        "(id, aufstellung_id, quelle, dateiname, sha256, groesse, medientyp) "
        "VALUES (gen_random_uuid(), :a, :quelle, 'bericht.xlsx', :sha, 2048, "
        "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')"
    ), {"quelle": quelle, "sha": sha256}


def _gueltige_aufstellung_mit_anlage(conn, probe_hash: str):
    """Eine gueltige Aufstellung mit einer Anlage — der Normalfall, an dem
    die CHECKs nicht anschlagen duerfen."""
    conn.execute(text(
        "INSERT INTO customers (id, customer_number, name, address_line1, "
        "zip_code, city, country) "
        "VALUES (gen_random_uuid(), 'K-7A-MIG', 'Kunde GmbH', 'Weg 1', "
        "'10115', 'Berlin', 'DE') ON CONFLICT DO NOTHING"
    ))
    stmt, params = _aufstellung_insert("AA-MIG-1")
    conn.execute(stmt, params)
    aufstellung = conn.execute(text(
        "SELECT id FROM aufstellungen WHERE nummer = 'AA-MIG-1'"
    )).scalar()
    anlage, anlage_params = _aufstellung_anlage_insert(
        "abrechnungsbericht", probe_hash)
    conn.execute(anlage, {**anlage_params, "a": aufstellung})
    conn.commit()
    return aufstellung


def _schlaegt_fehl(engine, stmt, params, fehler=IntegrityError):
    """CHECK/Unique verletzen sich als IntegrityError; der GoBD-Trigger
    dagegen als InternalError (P0001 RaiseException) — der Aufrufer nennt
    die erwartete Art."""
    with pytest.raises(fehler):
        with engine.connect() as conn:
            conn.execute(stmt, params)
            conn.commit()


def _unzulaessige_zeilen_schlagen_fehl(engine, aufstellung):
    """Jede Zeile verstoesst gegen genau eine Invariante; die Nummer nennt sie."""
    _schlaegt_fehl(engine, *_aufstellung_insert("AA-MIG-2", status="bezahlt"))
    _schlaegt_fehl(engine, *_aufstellung_insert("AA-MIG-3", netto="999.00"))
    _schlaegt_fehl(engine, *_aufstellung_insert("AA-MIG-4", kurs="1.0"))
    stmt, params = _aufstellung_anlage_insert("abrechnungsbericht", "b" * 64)
    _schlaegt_fehl(engine, stmt, {**params, "a": aufstellung})
    # Hard-DELETE schlaegt am GoBD-Trigger fehl — auch fuer den Administrator.
    _schlaegt_fehl(engine, text("DELETE FROM aufstellungen WHERE id = :a"),
                   {"a": aufstellung}, fehler=InternalError)


def test_aufstellung_nach_upgrade_head(migrationsdatenbank):
    url, _ = migrationsdatenbank
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            lage = _aufstellungs_lage(conn)
            aufstellung = _gueltige_aufstellung_mit_anlage(conn, "a" * 64)
        _unzulaessige_zeilen_schlagen_fehl(engine, aufstellung)
    finally:
        engine.dispose()

    spalten, anlagen, firma, checks, anlage_checks, indizes, trigger = lage
    assert {"nummer", "status", "customer_id", "leistung_von", "leistung_bis",
            "zahlungsnummer", "zahlungsdatum", "waehrung", "brutto",
            "quellensteuer", "netto", "kurs", "zahlbetrag_eur",
            "auftragsschluessel", "auftragsschluessel_offen",
            "uebergabe_beleg_id", "uebergabe_beleg_sha256", "bemerkung",
            "ausstellungsdatum", "pdf_filename", "datev_sent_at",
            "archive_until", "storniert_id", "created_at",
            "updated_at"} <= spalten
    assert {"aufstellung_id", "quelle", "dateiname", "sha256", "groesse",
            "medientyp"} <= anlagen
    assert {"aufstellung_prefix", "aufstellung_counter"} <= firma
    assert {"ck_aufstellungen_status_wertevorrat",
            "ck_aufstellungen_summe",
            "ck_aufstellungen_umrechnung_nur_bei_fremdwaehrung",
            "ck_aufstellungen_auftragsschluessel_offen_wie_nachweis"} <= checks
    assert {"ck_aufstellung_anlagen_quelle_wertevorrat",
            "ck_aufstellung_anlagen_sha256_form"} <= anlage_checks
    assert "uq_aufstellungen_auftragsschluessel_offen" in indizes
    assert {"gobd_no_delete_aufstellungen",
            "gobd_no_delete_aufstellung_anlagen",
            "gobd_no_truncate_aufstellungen",
            "gobd_no_truncate_aufstellung_anlagen"} <= trigger
