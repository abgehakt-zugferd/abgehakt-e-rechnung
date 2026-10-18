"""Storno nennt das Original und verweist auf dessen unveraenderte Anlagen."""
from datetime import date

import pytest

from app.services.aufstellung_pdf import erzeuge_pdf
from tests.factories_aufstellung import orm_aufstellung
from tests.test_aufstellung_pdf import _aufstellung, _firma
from tests.helpers.pdf import text


@pytest.mark.parametrize("sprache,titel,datum,anlagen", [
    ("de", "Stornierung der Abrechnungsaufstellung Nr. AA-ORIGINAL", "01.10.2026", "Anlagen des Originals"),
    ("en", "Cancellation of settlement statement no. AA-ORIGINAL", "2026-10-01", "Attachments of the original"),
])
def test_storno_pdf_original_und_anlagen(tmp_path, sprache, titel, datum, anlagen):
    original = _aufstellung(sprache=sprache, nummer="AA-ORIGINAL",
                           ausstellungsdatum=date(2026, 10, 1))
    s = orm_aufstellung(nummer="AA-STORNO", customer=original.customer,
                        ausstellungsdatum=date(2026, 10, 18))
    s.original = original
    ziel = tmp_path / "storno.pdf"
    erzeuge_pdf(s, _firma(), ziel)
    inhalt = " ".join(text(ziel).split())
    assert titel in inhalt and datum in inhalt and "AA-STORNO" in inhalt
    assert anlagen in inhalt
    for anlage in original.anlagen:
        assert anlage.dateiname in inhalt and anlage.sha256 in inhalt
    assert not s.anlagen
