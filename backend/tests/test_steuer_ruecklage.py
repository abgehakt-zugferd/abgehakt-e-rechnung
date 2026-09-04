"""Tests fuer konfigurierbare GmbH-Steuer-Ruecklage."""

from decimal import Decimal

from app.models.company import Company
from app.services.steuer_ruecklage import (
    DEFAULT_GEWERBE_HEBESATZ,
    DEFAULT_KST_PERCENT,
    DEFAULT_SOLI_AUF_KST_PERCENT,
    pruefe_eingaben,
    steuerruecklage_anteil,
    steuerruecklage_anteil_prozent,
)


def _company(**kwargs) -> Company:
    return Company(
        id=1,
        name="Test GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        kst_satz_percent=kwargs.get("kst", DEFAULT_KST_PERCENT),
        soli_auf_kst_percent=kwargs.get("soli", DEFAULT_SOLI_AUF_KST_PERCENT),
        gewerbe_hebesatz=kwargs.get("hebesatz", DEFAULT_GEWERBE_HEBESATZ),
    )


def test_default_anteil_ist_kst_plus_gewst():
    assert steuerruecklage_anteil(None) == Decimal("0.29825")
    assert steuerruecklage_anteil_prozent(None) == Decimal("29.83")


def test_anteil_nutzt_firmeneinstellungen():
    firma = _company(kst=Decimal("15.00"), soli=Decimal("5.50"), hebesatz=490)
    # 0,15 * 1,055 + 0,035 * 4,9 = 0,15825 + 0,1715 = 0,32975
    assert steuerruecklage_anteil(firma) == Decimal("0.32975")


def test_pruefe_eingaben_akzeptiert_gueltige_werte():
    assert pruefe_eingaben("15", "5,5", "400") is None


def test_pruefe_eingaben_lehnt_hebesatz_ab():
    assert "Gewerbehebesatz" in pruefe_eingaben("15", "5.5", "50")
