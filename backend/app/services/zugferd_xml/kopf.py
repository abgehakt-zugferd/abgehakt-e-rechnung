"""Kopf der CII: ExchangedDocumentContext, ExchangedDocument, Notizen, TypeCode."""
from app.models.invoice import Invoice
from app.services.belegart import belegart

from app.services.zugferd_xml.format import esc, fmt_date


def systemnotizen(invoice_type: str | None, original_nummer: str | None) -> list[str]:
    """Pflicht-Systemnotizen (BT-22) zur Belegart, vor der Nutzernotiz.

    Eine Quelle fuer den Wortlaut: der Generator schreibt sie, und der
    Rueckimport (scripts/beleg_aus_xml_einspielen.py) erkennt und ueberspringt
    sie an genau diesem Wortlaut — keine zweite Liste.
    """
    art = belegart(invoice_type).intern
    if art == "self_billing":
        return ["Gutschrift"]
    if art == "self_billing_storno" and original_nummer:
        return [f"Stornierung der Gutschrift Nr. {original_nummer}"]
    return []


def _belegnotiz(wert: str | None) -> str | None:
    """Nicht-leerer Freitext fuer BT-22, sonst None (EN 16931 R74).

    Reiner Text vom Beleg: kein ReportLab-Markup (``description_markup``
    wandelt Zeilenumbrueche in ``<br/>`` um — das gehoert nicht in die CII).
    Escaping uebernimmt ``esc`` beim Schreiben. ``None`` und Leerraum fallen
    weg; ``or ""`` verhindert, dass ``None`` als Literal ``"None"`` landet.
    """
    text = (wert or "").strip()
    return text or None


def notes_xml(invoice: Invoice) -> str:
    # BT-22 ist beim Gutschriftverfahren Pflicht und darf nicht von frei
    # bearbeitbaren Nutzernotizen abhängen.
    # Reihenfolge: Systemnotizen, Kopftext, Fusstext, dann invoice.notes.
    # BT-21 (SubjectCode) entfaellt: UNTDID 4451 hat keinen klaren Code fuer
    # Beleg-Kopf- bzw. Fusstext (AAI/ACB waeren Rateerei).
    art = belegart(invoice.invoice_type).intern
    original_nummer = (
        invoice.original_invoice.invoice_number if art == "self_billing_storno" else None
    )
    notizen = list(systemnotizen(invoice.invoice_type, original_nummer))
    for wert in (
        getattr(invoice, "kopftext", None),
        getattr(invoice, "fusstext", None),
    ):
        text = _belegnotiz(wert)
        if text is not None:
            notizen.append(text)
    if invoice.notes:
        notizen.append(invoice.notes)
    return "".join(f"""
        <ram:IncludedNote>
            <ram:Content>{esc(notiz)}</ram:Content>
        </ram:IncludedNote>""" for notiz in notizen)


# P7: Zuordnung Rechnungstyp → ZUGFeRD/UN-CEFACT TypeCode: services/belegart.py
# (380=Rechnung, 381=Gutschrift/Storno, 384=Rechnungskorrektur,
# 386=Anzahlungsrechnung, 389=Gutschrift im Gutschriftverfahren).


def type_code(invoice: Invoice) -> str:
    """Gibt den ZUGFeRD TypeCode (BT-3) für invoice.invoice_type zurück.

    Fail-closed (#98 E10) über `belegart()`: ein unbekannter Typ wird NICHT
    still auf 380 gemappt — sonst trüge die XML einen falschen Dokumenttyp
    (z. B. ein vertippter Storno als Standardrechnung). None = kein Typ
    gesetzt = 380 (legitimer Default). Der Validator (INVOICE_TYPE_INVALID)
    blockt zusätzlich die Finalisierung.
    """
    return belegart(invoice.invoice_type).bt3


def exchanged_document_xml(invoice: Invoice, profile_id: str) -> str:
    """ExchangedDocumentContext und ExchangedDocument (inkl. Notizen)."""
    code = type_code(invoice)
    return f"""    <rsm:ExchangedDocumentContext>
        <ram:GuidelineSpecifiedDocumentContextParameter>
            <ram:ID>{profile_id}</ram:ID>
        </ram:GuidelineSpecifiedDocumentContextParameter>
    </rsm:ExchangedDocumentContext>

    <rsm:ExchangedDocument>
        <ram:ID>{esc(invoice.invoice_number)}</ram:ID>
        <ram:TypeCode>{code}</ram:TypeCode>
        <ram:IssueDateTime>
            <udt:DateTimeString format="102">{fmt_date(invoice.issue_date)}</udt:DateTimeString>
        </ram:IssueDateTime>{notes_xml(invoice)}
    </rsm:ExchangedDocument>"""
