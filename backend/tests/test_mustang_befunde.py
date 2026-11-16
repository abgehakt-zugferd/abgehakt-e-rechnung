"""Mustang-Meldungen in Regel und Text zerlegen: eine Stelle (mustang.py).

Nähte: mustang.befunde_aus_bericht / mustang.validate (Rohbericht rein, Befunde
raus) und rechnung.pruefung.run_validation (was im Prüfergebnis steht). Der
Kreuztest zeigt, dass Prüfergebnis und angezeigtes Protokoll dieselben
Regelkennungen tragen.
"""
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.invoice import ValidationResult
from app.services import mustang, zugferd_xml
from app.services.rechnung import pruefung
from tests.helpers.ersatzrechnung import beleg, kunde
from tests.test_lieferblock_leer import BERICHT_FEHLER, BERICHT_WARNUNG, _invoice, _company, _kunde

ANHANG = " [ID {r}] from /xslt/ZF_250/FACTUR-X_EN16931.xslt)"


def _bericht(*elemente):
    return "<validation><xml><messages>" + "".join(elemente) + "</messages></xml></validation>"


def test_warnung_wird_in_regel_und_text_zerlegt():
    befunde = mustang.befunde_aus_bericht(BERICHT_WARNUNG)

    assert befunde == [{
        "regel": "PEPPOL-EN16931-R008", "schwere": "warning",
        "text": "Document MUST not contain empty elements. (still status warning)",
        "ort": "/*:CrossIndustryInvoice[1]/*:ApplicableHeaderTradeDelivery[1]",
    }]


def test_fehler_und_warnung_ohne_regelkennung():
    befunde = mustang.befunde_aus_bericht(BERICHT_FEHLER)

    assert {(b["schwere"], b["regel"]) for b in befunde} == {("error", "BR-07"), ("warning", "")}
    ohne = [b for b in befunde if b["regel"] == ""][0]
    assert ohne["text"] == "Arithmetical issue:Payable total in XML is 999.00"


def test_gleiche_meldung_als_element_und_zeile_zaehlt_einmal():
    text = "Mustang sagt etwas Eigenes."
    bericht = _bericht(f'<error type="4">{text}</error>') + f"\n[error] {text}\n"

    befunde = mustang.befunde_aus_bericht(bericht)

    assert [(b["schwere"], b["text"]) for b in befunde] == [("error", text)]


def test_zeilenmarker_ohne_element_wird_gelesen():
    befunde = mustang.befunde_aus_bericht("[error] Etwas ist kaputt\n[warning] Etwas ist fraglich\n")

    assert [(b["schwere"], b["text"]) for b in befunde] == [
        ("error", "Etwas ist kaputt"), ("warning", "Etwas ist fraglich")]


def test_validate_liefert_befunde_und_wertet_ein_fehlerelement_als_ungueltig():
    with patch.object(mustang, "_run", return_value=(BERICHT_FEHLER, "", 0)):
        ergebnis = mustang.validate(Path("x.xml"))

    assert [b["regel"] for b in ergebnis["befunde"] if b["schwere"] == "error"] == ["BR-07"]
    # Ein Fehler im Bericht macht das Ergebnis ungültig, auch bei Rückgabecode 0
    # (die Leser widersprechen sich nicht; echtes Mustang liefert bei Fehlern rc 255).
    assert ergebnis["is_valid"] is False


def test_nicht_ausfuehrbar_ist_ein_befund_mit_schwere_fehler():
    with patch.object(mustang, "_run", side_effect=mustang.MustangNichtAusfuehrbar("JAR fehlt")):
        ergebnis = mustang.validate(Path("x.xml"))

    assert [(b["schwere"], b["regel"]) for b in ergebnis["befunde"]] == [("error", "")]
    assert "nicht gemessen" in ergebnis["befunde"][0]["text"]


def test_befunde_von_faellt_auf_den_rohbericht_zurueck():
    assert mustang.befunde_von({"raw": BERICHT_WARNUNG})[0]["regel"] == "PEPPOL-EN16931-R008"
    assert mustang.befunde_von({"raw": "", "befunde": [{"regel": "X", "text": "t", "schwere": "error"}]})[0]["regel"] == "X"


# -- Prüfergebnis ----------------------------------------------------------

class _Sitzung:
    def __init__(self):
        self.eintraege = []

    def add(self, eintrag):
        self.eintraege.append(eintrag)


def _pruefen(raw, *, is_valid=True):
    inv = _invoice(_kunde(), delivery_date=None,
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))
    inv.zugferd_xml = zugferd_xml.generate_xml(inv, _company())
    with patch.object(mustang, "_run", return_value=(raw, "", 0 if is_valid else 1)):
        return inv, pruefung.run_validation(_Sitzung(), inv, _company())


def test_mustang_fehler_stehen_im_pruefergebnis_und_machen_es_ungueltig():
    _, vr = _pruefen(BERICHT_FEHLER + "Parsed PDF:absent XML:valid\n")

    fehler = [e for e in vr.errors if e["code"].startswith("MUSTANG_")]
    assert [(e["code"], e["severity"]) for e in fehler] == [("MUSTANG_BR-07", "error")]
    assert "[ID" not in fehler[0]["message"]
    assert vr.is_valid is False   # ein Fehler im Bericht gilt, auch bei rc 0


def test_mustang_fehler_ohne_kennung_heissen_mustang_fehler():
    _, vr = _pruefen("[error] Etwas ist kaputt\n", is_valid=False)

    assert [e["code"] for e in vr.errors if e["code"].startswith("MUSTANG_")] == ["MUSTANG_FEHLER"]
    assert vr.is_valid is False


def test_fehler_als_element_und_zeile_stehen_nur_einmal_im_pruefergebnis():
    text = "Etwas Eigenes."
    _, vr = _pruefen(_bericht(f"<error>{text}</error>") + f"\n[error] {text}\n", is_valid=False)

    assert len([e for e in vr.errors if e["code"].startswith("MUSTANG_")]) == 1


def test_pruefergebnis_haelt_den_hash_des_geprueften_xml_fest():
    import hashlib
    inv, vr = _pruefen(BERICHT_WARNUNG)

    assert vr.xml_sha256 == hashlib.sha256(inv.zugferd_xml.encode("utf-8")).hexdigest()


# -- Kreuztest: Prüfergebnis gegen angezeigtes Protokoll --------------------

@pytest.fixture
def web(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def test_angezeigtes_protokoll_traegt_dieselben_regeln_wie_das_pruefergebnis(pg_session, web):
    roh = _bericht(
        f'<error type="4">[BR-07]-An Invoice shall contain the Buyer name.{ANHANG.format(r="BR-07")}</error>',
        f'<warning type="4">[PEPPOL-EN16931-R008]-Document MUST not contain empty elements.{ANHANG.format(r="PEPPOL-EN16931-R008")}</warning>',
        '<warning type="10">Arithmetical issue:ohne Kennung</warning>',
    )
    inv = beleg(pg_session, kunde(pg_session), status="draft")
    inv.zugferd_xml = "<x/>"
    with patch.object(mustang, "_run", return_value=(roh, "", 0)):
        from app.routers.invoices.abbildung import firma_laden
        vr = pruefung.run_validation(pg_session, inv, firma_laden(pg_session))
    pg_session.commit()

    gespeichert = {e["code"].removeprefix("MUSTANG_") for e in vr.errors + vr.warnings
                   if e["code"].startswith("MUSTANG_")}
    seite = web.get(f"/invoices/{inv.id}").text
    angezeigt = set(re.findall(r'data-mustang-regel="([^"]*)"', seite))

    assert gespeichert == {"BR-07", "PEPPOL-EN16931-R008", "WARNUNG"}
    assert angezeigt == gespeichert


# -- Parser: mehrzeilig, maskiert, Ort, Altzeile ---------------------------

def test_mehrzeilige_meldung_wird_vollstaendig_gelesen():
    bericht = _bericht('<error type="4">[BR-09]-Erste Zeile\n      zweite Zeile'
                       ' [ID BR-09] from /xslt/x.xslt)</error>')

    (befund,) = mustang.befunde_aus_bericht(bericht)

    assert befund["regel"] == "BR-09"
    assert "zweite Zeile" in befund["text"]
    assert "[ID" not in befund["text"]


def test_maskierter_text_wird_entmaskiert():
    bericht = _bericht('<warning type="4">[BR-10]-Element &lt;ram:Name&gt; &amp; Co fehlt'
                       ' [ID BR-10] from /xslt/x.xslt)</warning>')

    (befund,) = mustang.befunde_aus_bericht(bericht)

    assert befund["text"] == "Element <ram:Name> & Co fehlt"


def test_ort_der_meldung_steht_im_feld_des_pruefeintrags():
    ort = "/*:CrossIndustryInvoice[1]/*:ApplicableHeaderTradeDelivery[1]"

    eintrag = pruefung.befund_als_eintrag(mustang.befunde_aus_bericht(BERICHT_WARNUNG)[0])

    assert eintrag["field"] == ort


def test_ort_mit_maskierten_zeichen_wird_entmaskiert():
    bericht = _bericht('<error location="/a[@x=&quot;1&quot;]" type="4">[BR-1]-t</error>')

    assert mustang.befunde_aus_bericht(bericht)[0]["ort"] == '/a[@x="1"]'


def test_altzeile_warning_bekommt_den_code_mustang_warnung():
    (befund,) = mustang.befunde_aus_bericht("[warning] Etwas ist fraglich\n")

    assert pruefung.befund_als_eintrag(befund)["code"] == "MUSTANG_WARNUNG"
    assert befund["ort"] == ""


# -- Die drei Leser widersprechen sich nicht --------------------------------

XML_VALID = "\nParsed PDF:absent XML:valid\n"
FEHLER_BEI_RC0 = _bericht('<error type="4">[BR-07]-Kaputt [ID BR-07] from x.xslt)</error>') + XML_VALID
SAUBER = _bericht() + XML_VALID
NUR_WARNUNG = BERICHT_WARNUNG
ZEILENFEHLER = "[error] Kaputt" + XML_VALID


@pytest.mark.parametrize("raw,rc,gueltig,fehlerbefund", [
    (SAUBER, 0, True, False), (NUR_WARNUNG, 0, True, False),
    (FEHLER_BEI_RC0, 0, False, True), (ZEILENFEHLER, 0, False, True),
    (SAUBER, 255, False, False), (FEHLER_BEI_RC0, 255, False, True),
])
def test_dieselbe_ausgabe_ergibt_in_allen_lesern_dasselbe_urteil(raw, rc, gueltig, fehlerbefund):
    with patch.object(mustang, "_run", return_value=(raw, "", rc)):
        ergebnis = mustang.validate(Path("x.xml"))
    hat_fehlerbefund = any(b["schwere"] == "error" for b in mustang.befunde_aus_bericht(raw))

    assert hat_fehlerbefund is fehlerbefund
    assert ergebnis["is_valid"] is gueltig
    assert mustang.ist_gueltige_e_rechnung(ergebnis) is gueltig
    # Kein Leser sagt „gültig“, während ein anderer einen Fehler gefunden hat.
    assert not (hat_fehlerbefund and mustang.ist_gueltige_e_rechnung(ergebnis))


def test_ist_gueltig_prueft_auch_ein_ergebnis_ohne_befundliste():
    """Ein Ergebnis, das nur is_valid und den Rohbericht trägt (Test-Doubles, ältere
    Aufrufer), wird nicht durchgewinkt, wenn der Rohbericht einen Fehler enthält."""
    ergebnis = {"is_valid": True, "nicht_ausfuehrbar": False, "raw": FEHLER_BEI_RC0}

    assert mustang.ist_gueltige_e_rechnung(ergebnis) is False
