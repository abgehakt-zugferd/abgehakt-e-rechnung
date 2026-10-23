"""Zahlungsvorgabe für Rechnungsaufträge, ohne erfundene Zahlungsfrist."""

from app.services.rechnung.fehler import RechnungFehler


def ist_rechnungsauftrag(invoice) -> bool:
    return bool(
        getattr(invoice, "auftragsschluessel", None)
        and getattr(invoice, "uebergabe_beleg_sha256", None)
        and getattr(invoice, "invoice_type", None) in (None, "standard")
    )


def hinweis_fehlt(invoice) -> bool:
    return (
        invoice.status == "draft" and ist_rechnungsauftrag(invoice)
        and not (invoice.payment_terms or "").strip()
    )


def fehlermeldung(invoice) -> str:
    return (
        "Zahlungshinweis fehlt. Bitte beim Kunden hinterlegen und mit "
        "„Kundenvorgabe übernehmen“ in den Entwurf kopieren: "
        f"/customers/{invoice.customer_id}/bearbeiten"
    )


def finalisierung_pruefen(invoice) -> None:
    if hinweis_fehlt(invoice):
        raise RechnungFehler(400, fehlermeldung(invoice))


def uebernehmen(invoice) -> None:
    # Nur die offene Lücke füllen: spätere Stammdatenänderungen dürfen einen
    # bereits geprüften Hinweis am Beleg nicht unbemerkt überschreiben.
    if not hinweis_fehlt(invoice):
        raise RechnungFehler(400, "Nur fehlende Zahlungshinweise aus Rechnungsaufträgen übernehmen.")
    hinweis = (invoice.customer.zahlungshinweis or "").strip() if invoice.customer else ""
    if not hinweis:
        raise RechnungFehler(400, fehlermeldung(invoice))
    invoice.payment_terms = hinweis


def ohne_ueberweisungsaufforderung(invoice) -> bool:
    """BT-20 ohne BT-9 beschreibt die Zahlung allein, auch im PDF-Fuß."""
    return invoice.due_date is None and bool((invoice.payment_terms or "").strip())
