"""
Erzeugt ZUGFeRD 2.x CII-XML (Factur-X EN16931) aus Rechnungsdaten.
Seit 01.01.2025 hat der XML-Teil rechtlich Vorrang gegenüber dem PDF (§ 14 UStG n.F.).
Profile MINIMUM und BASIC-WL sind nicht rechtskonform – Standard: EN16931.
"""
# P7: Die Zuordnung Rechnungstyp → ZUGFeRD/UN-CEFACT TypeCode lebt in
# services/belegart.py als EINZIGE fachliche Quelle (mit PDF-Titel und
# manueller Waehlbarkeit). TYPE_CODE_MAP und UnknownInvoiceTypeError werden
# hier nur re-exportiert, damit Bestandsleser ihre Importstelle behalten —
# es gibt kein zweites Mapping.
from app.services.belegart import (  # noqa: F401
    TYPE_CODE_MAP,
    UnknownInvoiceTypeError,
)

from app.services.zugferd_xml.erzeugen import generate_xml
from app.services.zugferd_xml.kopf import systemnotizen
from app.services.zugferd_xml.steuerbefreiung import (
    COMPLIANT_PROFILES,
    EXEMPTION_REASONS,
    NonCompliantProfileError,
    PROFILE_IDS,
    exemption_reason,
)

__all__ = [
    "COMPLIANT_PROFILES",
    "EXEMPTION_REASONS",
    "NonCompliantProfileError",
    "PROFILE_IDS",
    "TYPE_CODE_MAP",
    "UnknownInvoiceTypeError",
    "exemption_reason",
    "generate_xml",
    "systemnotizen",
]
