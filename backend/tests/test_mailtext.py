"""Mailtext je Belegsprache: reine Logik ohne Datenbank und ohne SMTP.

docs/specs/mailtext.md — Platzhalter, eingebaute Schablonen, Verantwortlichen-Fuss.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import mailtext
from app.services.belegsprache import UnknownDocumentLanguageError


def _invoice(**kw):
    werte = dict(
        invoice_number="RE-2026-001",
        document_language="de",
        gross_total=Decimal("1234.56"),
        currency="EUR",
        due_date=date(2026, 9, 28),
        customer=SimpleNamespace(name="Kunde GmbH"),
    )
    werte.update(kw)
    return SimpleNamespace(**werte)


def _firma(**kw):
    werte = dict(
        name="Kanzlei Musterfrau",
        address_line1="Musterweg 3",
        zip_code="80331",
        city="München",
    )
    werte.update(kw)
    return SimpleNamespace(**werte)


def _config(**kw):
    werte = dict(
        mail_betreff_de=None,
        mail_text_de=None,
        mail_betreff_en=None,
        mail_text_en=None,
    )
    werte.update(kw)
    return SimpleNamespace(**werte)


def test_fuenf_platzhalter_werden_ersetzt():
    inhalt = mailtext.rechnungsmail(
        _invoice(),
        _firma(),
        _config(
            mail_betreff_de="{rechnungsnummer} {kunde} {betrag} {faellig_am} {firma}",
            mail_text_de=(
                "Nr={rechnungsnummer};Kunde={kunde};Betrag={betrag};"
                "Faellig={faellig_am};Firma={firma}"
            ),
        ),
    )
    assert inhalt.betreff == (
        "RE-2026-001 Kunde GmbH 1.234,56 € 28.09.2026 Kanzlei Musterfrau"
    )
    assert inhalt.rumpf.startswith(
        "Nr=RE-2026-001;Kunde=Kunde GmbH;Betrag=1.234,56 €;"
        "Faellig=28.09.2026;Firma=Kanzlei Musterfrau"
    )


def test_unbekannter_platzhalter_wirft_beim_pruefen_und_nennt_ihn():
    with pytest.raises(mailtext.UnbekannterPlatzhalterError) as exc:
        mailtext.pruefe_schablone("Hallo {unbekannt}")
    assert exc.value.name == "unbekannt"


def test_geschweifte_klammern_ohne_regex_treffer_bleiben_stehen():
    """Ein einzelnes `{` oder `{Produkt X}` darf die Mail nicht unversendbar machen."""
    mailtext.pruefe_schablone("Preis {Produkt X} und lone {")
    inhalt = mailtext.rechnungsmail(
        _invoice(),
        _firma(),
        _config(mail_text_de="Preis {Produkt X} und lone {\n{firma}"),
    )
    assert "Preis {Produkt X} und lone {" in inhalt.rumpf


def test_betrag_und_datum_folgen_der_sprache():
    de = mailtext.rechnungsmail(
        _invoice(document_language="de"),
        _firma(),
        _config(mail_text_de="{betrag} am {faellig_am}"),
    )
    en = mailtext.rechnungsmail(
        _invoice(document_language="en"),
        _firma(),
        _config(mail_text_en="{betrag} on {faellig_am}"),
    )
    assert "1.234,56" in de.rumpf
    assert "28.09.2026" in de.rumpf
    assert "1,234.56" in en.rumpf
    assert "2026-09-28" in en.rumpf
    assert de.rumpf != en.rumpf


def test_leeres_firma_hinterlaesst_keine_leerzeile_am_ende():
    # Keine Anschrift: sonst maskiert der Verantwortlichen-Fuss das Ende.
    inhalt = mailtext.rechnungsmail(
        _invoice(),
        None,
        _config(mail_text_de="Gruss\n{firma}"),
    )
    rumpf = inhalt.rumpf.rstrip("\n")
    assert rumpf.endswith("Gruss")
    assert not inhalt.rumpf.endswith("\n\n")


def test_verantwortlichen_fuss_steht_unabhaengig_von_der_schablone():
    inhalt = mailtext.rechnungsmail(
        _invoice(),
        _firma(),
        _config(mail_text_de="Nur Text.\nVerantwortlich: Fremder"),
    )
    assert inhalt.rumpf.rstrip("\n").endswith(
        "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München"
    )
    assert inhalt.rumpf.count("Verantwortlich:") == 2


def test_englischer_fuss_heisst_responsible():
    inhalt = mailtext.rechnungsmail(
        _invoice(document_language="en"),
        _firma(),
        _config(),
    )
    assert "Responsible: Kanzlei Musterfrau, Musterweg 3, 80331 München" in inhalt.rumpf
    assert "Verantwortlich:" not in inhalt.rumpf


def test_ungueltige_belegsprache_faellt_nicht_auf_deutsch():
    with pytest.raises(UnknownDocumentLanguageError):
        mailtext.rechnungsmail(
            _invoice(document_language="xx"),
            _firma(),
            _config(),
        )


def test_eingebauter_deutscher_rumpf_zeichengleich_mit_heutigem():
    """Vergleichstext ausgeschrieben — nicht ueber dieselbe Funktion, die geprueft wird."""
    erwartet = (
        "Sehr geehrte Damen und Herren,\n"
        "\n"
        "anbei erhalten Sie Ihre Rechnung RE-2026-001.\n"
        "\n"
        "Das Dokument enthält die strukturierten ZUGFeRD-Rechnungsdaten "
        "(Factur-X EN16931) gemäß § 14 UStG.\n"
        "\n"
        "Bei Fragen stehen wir Ihnen gerne zur Verfügung.\n"
        "\n"
        "Mit freundlichen Grüßen\n"
        "Kanzlei Musterfrau\n"
        "\n"
        "---\n"
        "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München\n"
    )
    inhalt = mailtext.rechnungsmail(_invoice(), _firma(), _config())
    assert inhalt.betreff == "Rechnung RE-2026-001"
    assert inhalt.rumpf == erwartet


def test_eingebauter_englischer_betreff_und_anrede():
    inhalt = mailtext.rechnungsmail(
        _invoice(document_language="en"),
        _firma(),
        _config(),
    )
    assert inhalt.betreff == "Invoice RE-2026-001"
    assert inhalt.rumpf.startswith("Dear Sir or Madam,")
    assert "invoice RE-2026-001" in inhalt.rumpf


def test_platzhalter_liste_ist_die_einzige():
    assert mailtext.PLATZHALTER == (
        "rechnungsnummer",
        "kunde",
        "betrag",
        "faellig_am",
        "firma",
    )
