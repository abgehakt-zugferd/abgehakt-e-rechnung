"""Detailseite einer Aufstellung: Versandstatus an die Buchhaltung sichtbar.

Oeffentliche Grenze: GET /aufstellungen/{id} (TestClient), gerendertes HTML.
Anlass: Der Versand gelang, die Seite sah aus wie vorher; ein roher
Zeitstempel in der Angabenliste war der einzige Hinweis (Gefahr: Doppelversand).
"""

import re
from datetime import date, datetime, timezone

from tests.factories_aufstellung import speichere_aufstellung

# 23:30 UTC am 11.11. ist in Berlin 00:30 am 12.11. (Winterzeit, UTC+1)
VERSENDET = datetime(2026, 11, 11, 23, 30, 5, 123456, tzinfo=timezone.utc)


def _seite(client, pg_session, **over):
    a = speichere_aufstellung(pg_session, status="issued", **over)
    return client.get(f"/aufstellungen/{a.id}").text


def test_nicht_versendet_zeigt_gedimmte_statuszeile_und_primaeren_knopf(client, pg_session):
    text = _seite(client, pg_session)

    assert "Buchhaltung: nicht versendet" in text
    zeile = re.search(r'<p[^>]*>\s*Buchhaltung: nicht versendet', text)
    assert zeile and "var(--text-dim)" in zeile.group(0)
    knopf = re.search(r'<button class="([^"]*)">AN BUCHHALTUNG SENDEN</button>', text)
    assert knopf and "btn-primary" in knopf.group(1)
    assert "ERNEUT" not in text


def test_versendet_zeigt_grunes_datum_in_ortszeit(client, pg_session):
    text = _seite(client, pg_session, datev_sent_at=VERSENDET)

    zeile = re.search(r'<p[^>]*>\s*Buchhaltung: versendet am 12\.11\.2026', text)
    assert zeile, "Statuszeile mit Berliner Datum fehlt"
    assert "var(--green)" in zeile.group(0)
    assert "nicht versendet" not in text


def test_versendet_macht_den_knopf_zurueckhaltend_und_nennt_erneut(client, pg_session):
    text = _seite(client, pg_session, datev_sent_at=VERSENDET)

    assert "ERNEUT AN BUCHHALTUNG SENDEN" in text
    knopf = re.search(r'<button class="([^"]*)">ERNEUT AN BUCHHALTUNG SENDEN', text)
    assert knopf and "btn-secondary" in knopf.group(1)
    assert "btn-primary\">AN BUCHHALTUNG" not in text
    assert 'action="/aufstellungen/' in text


def test_statuszeile_steht_direkt_unter_den_knoepfen(client, pg_session):
    text = _seite(client, pg_session, datev_sent_at=VERSENDET)

    assert text.index("STORNIEREN") < text.index("Buchhaltung: versendet am")
    assert text.index("Buchhaltung: versendet am") < text.index("<h2>ANGABEN</h2>")


def test_angabenliste_zeigt_deutsche_zeitstempel_ohne_rohformat(client, pg_session):
    text = _seite(
        client, pg_session, datev_sent_at=VERSENDET,
        ausstellungsdatum=date(2026, 11, 3), archive_until=date(2036, 12, 31),
    )

    angaben = text.split("<h2>ANGABEN</h2>")[1].split("<h2>ANLAGEN</h2>")[0]
    assert "12.11.2026 00:30" in angaben
    assert "03.11.2026" in angaben
    assert "31.12.2036" in angaben
    assert "+00:00" not in angaben
    assert "2026-11-03" not in angaben
    assert "123456" not in angaben
    # Erstellt/Aktualisiert: Zeitpunkt der Anlage, deutsch und ohne Sekundenbruchteile
    assert re.search(r"Erstellt</dt><dd[^>]*>\d\d\.\d\d\.\d{4} \d\d:\d\d</dd>", angaben)
