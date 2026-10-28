import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace

from fastapi import HTTPException

from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.services import belegsperre, positionsangaben
from app.services.belegart import UnknownInvoiceTypeError, belegart
from app.services.belegsprache import UnknownDocumentLanguageError, dezimal_klartext, resolve_belegsprache
from app.services.einheiten import UnknownUnitError, unbekannte_bezeichnungen, resolve_einheit


def ungueltige_einheiten(items_json: str | None) -> tuple[str, ...]:
    """Einheiten der angezeigten Positionen, die der Katalog nicht kennt.

    Quelle ist dasselbe `items_json`, aus dem das Formular die Positionen liest. Damit
    gilt die Regel an jeder Stelle, die das Formular rendert, auch beim Vorbefuellen,
    wo `invoice` per Vertrag None ist (docs/specs/kopieren.md, Invariante 2).
    """
    if not items_json:
        return ()
    try:
        positionen = json.loads(items_json.replace("<\\/", "</"))
    except (ValueError, AttributeError):
        return ()
    return unbekannte_bezeichnungen(p.get("unit") for p in positionen if isinstance(p, dict))


def belegsprache_aus_form(form, *, fehlt: str = "de") -> str:
    """Formularwert → de|en.

    Fehlendes Feld: `fehlt` (Neuanlage: de zur Abwaertskompatibilitaet;
    Bearbeiten: bisherige Sprache der Rechnung). Jeder andere Wert ist HTTP 400
    vor Nummernvergabe. Der Resolver faellt nicht still auf Deutsch zurueck.
    """
    if "document_language" not in form:
        return fehlt
    roh = form.get("document_language")
    try:
        return resolve_belegsprache(roh if roh is not None else "")
    except UnknownDocumentLanguageError as fehler:
        raise HTTPException(400, str(fehler)) from fehler


def _firmen_vorgabe(company: Company, sprache: str) -> str:
    """Firmenvorgabe der gewaehlten Belegsprache; en ohne Vorgabe → 400."""
    if sprache == "en":
        vorgabe = (company.payment_terms_default_en or "").strip()
        if not vorgabe:
            raise HTTPException(
                400,
                "Englische Standard-Zahlungsbedingungen fehlen in den Einstellungen. "
                "Bitte zuerst unter Einstellungen hinterlegen.",
            )
        return vorgabe
    return (company.payment_terms_default or "").strip()


def zahlungsbedingungen(form, company: Company, sprache: str,
                        kunden_hinweis: str | None = None) -> str:
    """Leeres Feld → Zahlungshinweis des Kunden, sonst Vorgabe der gewaehlten
    Sprache. Steht genau die Vorgabe der anderen Sprache im Feld, wird sie
    durch die Vorgabe der gewaehlten Sprache ersetzt (#248). Freitext bleibt.
    Englisch ohne Vorgabe: 400.

    Der Kundenhinweis (Entscheidung 4) steht VOR der Sprachvorgabe der Firma:
    er gilt fuer DIESEN Kunden, die Firmavorgabe ist der Rueckfall fuer alle.
    Am Schreibpfad folgt danach zahlungstext_beim_speichern (#231): erst
    Sprach-Tausch, dann ggf. Gutschrift-Text auf der Firmenvorgabe.
    """
    eingabe = (form.get("payment_terms") or "").strip()
    andere = "de" if sprache == "en" else "en"
    andere_vorgabe = (
        (company.payment_terms_default or "").strip()
        if andere == "de"
        else (company.payment_terms_default_en or "").strip()
    )
    if eingabe and andere_vorgabe and eingabe == andere_vorgabe:
        return _firmen_vorgabe(company, sprache)
    if eingabe:
        return eingabe
    if kunden_hinweis:
        return kunden_hinweis
    return _firmen_vorgabe(company, sprache)


def _calc_item(quantity: Decimal, unit_price: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    net = (quantity * unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax = (net * tax_rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    gross = net + tax
    return net, tax, gross


def kunde_id(form) -> uuid.UUID | None:
    """Kunde aus dem Formular, oder None.

    Steht im Auswahlfeld noch „– Kunde wählen –", schickt der Browser einen LEEREN
    String mit, nicht gar nichts. `uuid.UUID("")` wirft dafür `ValueError` und damit
    einen 500er, wo eigentlich ein erlaubter Zustand vorliegt: ein Entwurf ohne
    Empfänger. Pflicht wird der Kunde erst beim Finalisieren (`BUYER_MISSING`).
    """
    roh = (form.get("customer_id") or "").strip()
    return uuid.UUID(roh) if roh else None


def faelligkeit_aus_form(form) -> date | None:
    """Leeres Feld heisst None, kein date.fromisoformat auf "": ein Kunde, der
    nach eigenem Takt zahlt (z. B. eine Plattform nach ihrem Bericht), bekommt
    keinen Termin, sondern den Zahlungshinweis in den Zahlungsbedingungen
    (BR-CO-25, Bauschritt 2b)."""
    roh = (form.get("due_date") or "").strip()
    return date.fromisoformat(roh) if roh else None


def _normalize_description(raw) -> str:
    """Zeilenenden vereinheitlichen, Rand-Whitespace weg. Der Rest bleibt wörtlich
    stehen — was der Nutzer tippt, geht so in `ram:Name` (BT-153) der CII-XML."""
    return str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def pruefe_einheiten(raw_items) -> None:
    """Serverseitig vor Nummernvergabe bzw. vor Speichern: unbekannte Einheit → 400.

    Trim aussen, danach exakter Katalogvergleich. Kein Default fuer leer/unbekannt.
    """
    for i, raw in enumerate(raw_items, 1):
        roh = raw.get("unit")
        if roh is None:
            roh = ""
        wert = str(roh).strip()
        try:
            resolve_einheit(wert)
        except UnknownUnitError:
            raise HTTPException(400, f"Position {i}: unbekannte Einheit {wert!r}.") from None


def pruefe_positionsangaben(raw_items) -> None:
    """Wie `pruefe_einheiten`: vor Nummernvergabe bzw. Speichern, sonst 400."""
    for i, raw in enumerate(raw_items, 1):
        try:
            positionsangaben.aus_formular(raw, i)
        except positionsangaben.PositionsangabeUngueltig as fehler:
            raise HTTPException(400, str(fehler)) from None


def abzug_aus_form(form) -> tuple[Decimal | None, str | None]:
    """Abzugspaar aus dem Formular; beide leer heisst kein Abzug (None, None).

    Nur eines der Felder gesetzt ist eine unvollständige Eingabe, ein nicht
    parsebarer Betrag ebenfalls. Beides wird HIER gemeldet und nicht erst von
    belegsummen, damit /neu vor der Nummernvergabe ablehnen kann. Der Grund
    wird nicht ersetzt oder erfindbar gemacht: fehlt er, wird abgelehnt.
    """
    roh_betrag = (form.get("abzug_betrag") or "").strip()
    roh_grund = (form.get("abzug_grund") or "").strip()
    if not roh_betrag and not roh_grund:
        return None, None
    if not roh_betrag or not roh_grund:
        raise HTTPException(
            400,
            "Abzug unvollständig: Betrag und Grund müssen zusammen gesetzt "
            "oder beide leer sein.",
        )
    try:
        # Komma und Punkt als Dezimaltrenner; hier centgenau runden wie belegsummen.
        betrag = Decimal(roh_betrag.replace(",", ".")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, OverflowError):
        raise HTTPException(400, f"Abzugsbetrag {roh_betrag!r} ist keine Zahl.") from None
    return betrag, roh_grund


def _herleitung_aus_formular(raw, netto):
    from app.services.uebergabe_befund import herleitungsbetrag

    werte = [str(raw.get(feld) or "").strip() for feld in ("basis_netto", "satz")]
    if not any(werte):
        return {"basis_netto": None, "satz": None}
    try:
        basis, satz = map(Decimal, werte)
        # Der Beteiligungssatz trägt beliebig viele Nachkommastellen (wie das
        # Übergabeformat, "33.333333"): Der importierte Entwurf bindet ihn aus
        # dem Bestand (belegsperre), und eine Zwei-Nachkommastellen-Probe hier
        # ließe sich nicht mehr speichern. Die Bemessungsgrundlage bleibt Geld
        # mit genau zwei Stellen, und die Nachgerechnung gilt für beide.
        if (not basis.is_finite() or not satz.is_finite()
                or basis != basis.quantize(Decimal("0.01"))
                or abs(basis) >= Decimal("10000000000") or abs(satz) >= 1000):
            raise ValueError
        if herleitungsbetrag(basis, satz) != netto:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail=
            "Herleitung: Bemessungsgrundlage mit höchstens zwei Nachkommastellen, "
            "Beteiligungssatz beliebig genau eingeben; der Betrag muss "
            "Bemessungsgrundlage × Beteiligungssatz / 100 entsprechen.")
    return {"basis_netto": basis, "satz": satz}


def positionen_aus_formular(raw_items) -> list[InvoiceItem]:
    """Positionen aus dem Formular bauen (Position 1..n, lückenlos), ohne DB.

    Die Betragsrechnung liegt bei `_calc_item`; dies ist die einzige Stelle, die
    Formularpositionen in InvoiceItem überführt. Ohne DB, weil /neu die Summen
    vor der Nummernvergabe prüfen muss.
    """
    positionen = []
    for i, raw in enumerate(raw_items, 1):
        qty = Decimal(str(raw["quantity"]))
        price = Decimal(str(raw["unit_price"]))
        tax_rate = Decimal(str(raw["tax_rate"]))
        net, tax, gross = _calc_item(qty, price, tax_rate)
        herleitung = _herleitung_aus_formular(raw, net)
        # Nach pruefe_einheiten: getrimmter Katalogwert, kein Default auf Stück.
        unit = str(raw.get("unit") or "").strip()
        positionen.append(InvoiceItem(
            position=i,
            description=_normalize_description(raw["description"]),
            **positionsangaben.aus_formular(raw, i),
            **herleitung,
            unit=unit,
            quantity=qty,
            unit_price=price,
            tax_rate=tax_rate,
            net_amount=net,
            tax_amount=tax,
            gross_amount=gross,
        ))
    return positionen


def belegart_waehlbar(invoice: Invoice | None) -> bool:
    """Ob das Formular ein Belegart-Feld anbietet (Spec vorabrechnung.md, Option B).

    Nur fuer manuell waehlbare Arten ohne gebundene Herkunft. Systembelege
    (381/384 und 389-Storno) oder importierte 389 bekommen kein editierbares
    Typfeld; ein unbekannter
    gespeicherter Typ wird fail-closed wie ein Systembeleg behandelt.
    Die Sperre steht serverseitig in den POST-Handlern — das fehlende Feld
    im HTML ist nur die ehrliche Anzeige davon, keine Sperre.
    """
    if invoice is None:
        return True
    if belegsperre.gilt(invoice):
        return False
    try:
        return belegart(invoice.invoice_type).manuell_waehlbar
    except UnknownInvoiceTypeError:
        return False


def items_as_json(invoice: Invoice, *, vorlage: bool = False) -> str:
    """Positionen für das Alpine-Formular. Menge und Steuersatz ohne Nullen am Ende,
    damit `19.00` als `19` zur Auswahlliste passt, aber nie als `6E+1`."""
    # `</` maskieren: die Liste steht im Template in einem <script>-Block, und eine
    # Beschreibung mit "</script>" würde ihn sonst vorzeitig schließen. `<\/` ist
    # gültiges JSON und dekodiert zum selben Zeichen.
    return json.dumps([
        {
            "description": item.description or "",
            "unit": item.unit,
            "quantity": dezimal_klartext(item.quantity),
            "unit_price": str(item.unit_price),
            # Die Herleitung gehoert zum alten Betrag: Bei vorlage=True faellt
            # sie weg (wie der Leistungszeitraum), sonst liesse sich der neue
            # Betrag mit der alten Basis nicht mehr speichern.
            "basis_netto": "" if vorlage or item.basis_netto is None else str(item.basis_netto),
            "satz": "" if vorlage or item.satz is None else str(item.satz),
            "tax_rate": dezimal_klartext(item.tax_rate),
            "net_amount": float(item.net_amount),
            "tax_amount": float(item.tax_amount),
            "gross_amount": float(item.gross_amount),
            **positionsangaben.fuer_formular(item, vorlage=vorlage),
        }
        for item in sorted(invoice.items, key=lambda i: i.position)
    ]).replace("</", "<\\/")


def vorbelegung_aus(quelle: Invoice, customers, mit_abzug: bool = False) -> tuple[SimpleNamespace, str, str | None]:
    """Formularwerte aus einer bestehenden Rechnung (docs/specs/kopieren.md, Feldvertrag).

    Kein invoice_type, kein original_invoice_id, kein ersetzt_invoice_id, keine
    uebergabe_beleg_*: die gehoeren nicht in die Vorbelegung. document_language
    wird vererbt (docs/specs/belegsprache.md). Die Ersatzrechnung setzt die
    Belegart danach ausdruecklich selbst. Der Abzug wird nur mit mit_abzug=True
    uebernommen: eine Kopie wuerde die einmalige Anrechnung still verdoppeln,
    die Ersatzrechnung ersetzt dagegen dieselbe Leistung.
    """
    kunde_hinweis = None
    waehlbare_ids = {c.id for c in customers}
    kunde_id = quelle.customer_id if quelle.customer_id in waehlbare_ids else None
    if quelle.customer_id is not None and kunde_id is None:
        kunde_hinweis = "Vorlagenkunde nicht waehlbar"
    vorbelegung = SimpleNamespace(
        customer_id=kunde_id,
        tax_category=quelle.tax_category,
        buyer_reference=quelle.buyer_reference,
        buyer_order_reference=quelle.buyer_order_reference,
        abzug_betrag=quelle.abzug_betrag if mit_abzug else None,
        abzug_grund=quelle.abzug_grund if mit_abzug else None,
        service_period_start=quelle.service_period_start,
        service_period_end=quelle.service_period_end,
        delivery_date=quelle.delivery_date,
        payment_terms=quelle.payment_terms,
        notes=quelle.notes,
        # Kopf-/Fusstext werden wie die Bemerkung vererbt: sie sind bereits
        # Rechnungsinhalt der Vorlage (Platzhalter war schon ersetzt).
        kopftext=getattr(quelle, "kopftext", None),
        fusstext=getattr(quelle, "fusstext", None),
        document_language=getattr(quelle, "document_language", None) or "de",
        invoice_type=None,
    )
    return vorbelegung, items_as_json(quelle, vorlage=True), kunde_hinweis
