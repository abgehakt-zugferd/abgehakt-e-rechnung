"""Protokollfassung (abgehakt#72): rechnen alle drei Anwendungen mit derselben Fassung?

`format_version` auf einem Beleg sagt, nach welchen Regeln DIESER Beleg gebaut ist.
Diese Konstante sagt, was diese Anwendung beherrscht. Der Abstimmungspunkt ist
`protokoll.json` im Ordner der Uebergabepapiere, nicht der Quelltext einer App; dass
beide nicht auseinanderlaufen, misst `tests/vektoren/test_protokoll_vektoren.py`
gegen die Datei.

Keine Aushandlung zur Laufzeit: die Anwendungen fragen einander nichts.
"""

import pytest

from app.services.protokoll import (
    ABGELEHNT_AB_MAJOR,
    AKZEPTIERTE_FASSUNGEN,
    BEFUNDCODES,
    NUTZLAST_ARTEN,
    PROTOKOLL_VERSION,
    fassung_annehmbar,
)


def test_die_beherrschte_fassung_ist_die_letzte_akzeptierte():
    assert AKZEPTIERTE_FASSUNGEN[-1] == PROTOKOLL_VERSION
    assert AKZEPTIERTE_FASSUNGEN[0] == "1.0"


@pytest.mark.parametrize("fassung", ["1.0", "1.4"])
def test_gleicher_oder_niedrigerer_minor_wird_angenommen(fassung):
    assert fassung_annehmbar(fassung)


def test_die_eigene_fassung_wird_angenommen():
    assert fassung_annehmbar(PROTOKOLL_VERSION)


@pytest.mark.parametrize("fassung", ["1.9", "1.12", "1.5000"])
def test_hoeherer_minor_wird_angenommen(fassung):
    """Ein Empfaenger, der bei unbekanntem minor abbricht, macht aus jeder
    Erweiterung einen major und aus dem Gleichschritt eine Blockade."""
    assert fassung_annehmbar(fassung)


@pytest.mark.parametrize("fassung", ["2.0", "2.1", "3.0", "10.0"])
def test_hoeherer_major_wird_abgelehnt(fassung):
    assert not fassung_annehmbar(fassung)


@pytest.mark.parametrize("fassung", ["", "1", "0.9", "eins.null", "1.x", "-1.0", None])
def test_unlesbare_oder_zu_alte_fassung_wird_abgelehnt(fassung):
    assert not fassung_annehmbar(fassung)


def test_ab_major_zwei_wird_abgelehnt():
    assert ABGELEHNT_AB_MAJOR == 2


def test_befundcodes_sind_ein_geschlossener_wertevorrat():
    assert isinstance(BEFUNDCODES, frozenset)
    assert "PARTNER_ID_UNBEKANNT" in BEFUNDCODES
    assert "FASSUNG_UNVERTRAEGLICH" in BEFUNDCODES
    # Ein selbst erfundenes Wort gibt es nicht mehr (#72).
    assert "AUFTRAG_KAPUTT" not in BEFUNDCODES


def test_nutzlast_arten_sind_die_drei_des_protokolls():
    assert set(NUTZLAST_ARTEN) == {"erloesmeldung", "abrechnungsauftrag", "quittung"}


def test_einstellungen_zeigen_app_version_und_protokollfassung(client, pg_session):
    """Wer eine Ablehnung untersucht, will zuerst wissen, welche Fassung hier laeuft.

    Beide Zahlen stehen nebeneinander, sobald die Beleg-Integration eingeschaltet
    ist. Ohne den Schalter waere "Protokollfassung 1.5" auf einer fremden
    Installation keine Auskunft, sondern eine Supportfrage - dass sie dann fehlt,
    misst tests/test_beleg_integration_schalter.py.
    """
    from app.config import get_settings
    from app.models.app_config import AppConfig

    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = True
    pg_session.commit()

    antwort = client.get("/settings/")
    assert antwort.status_code == 200
    assert "PROTOKOLLFASSUNG" in antwort.text.upper()
    assert PROTOKOLL_VERSION in antwort.text
    assert get_settings().app_version in antwort.text
