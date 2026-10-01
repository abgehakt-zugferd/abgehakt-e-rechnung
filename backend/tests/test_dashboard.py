"""
Dashboard-Aggregation (Audit-#8): main.dashboard zählt Rechnungen nach Status.
Bisher 0 Tests. Wir rufen die Route-Funktion direkt und prüfen den Template-Kontext
(robuster als HTML-Grep auf rohe Zahlen).
"""
import uuid
from datetime import date
from app.zeit import heute as kalender_heute
from decimal import Decimal

from starlette.requests import Request

import app.main as main
from app.models.customer import Customer
from app.models.invoice import Invoice


def _request() -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/dashboard", "raw_path": b"/dashboard",
        "headers": [], "query_string": b"", "scheme": "http",
        "server": ("test", 80), "client": ("test", 1234),
    })


def _inv(pg_session, status, gross, issue=None, net=None, tax=None, due=None,
         bezahlt_am=None):
    if issue is None:
        issue = kalender_heute()
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    if net is None:
        net = Decimal(gross) if gross else Decimal("0")
    if tax is None:
        tax = Decimal("0")
    if status == "paid" and bezahlt_am is None:
        bezahlt_am = issue
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=issue, due_date=due or issue, currency="EUR",
                  net_total=net, tax_total=tax,
                  gross_total=Decimal(gross), status=status,
                  bezahlt_am=bezahlt_am)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, status, gross, issue=None, net=None, tax=None, due=None,
                bezahlt_am=None):
    if issue is None:
        issue = kalender_heute()
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    if net is None:
        net = Decimal(gross) if gross else Decimal("0")
    if tax is None:
        tax = Decimal("0")
    inv = Invoice(invoice_number=f"GS-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=issue, due_date=due or issue, currency="EUR",
                  net_total=net, tax_total=tax,
                  gross_total=Decimal(gross), status=status,
                  invoice_type="credit_note", bezahlt_am=bezahlt_am)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_dashboard_zaehlt_status_korrekt(pg_session):
    heute = kalender_heute()
    for _ in range(2):
        _inv(pg_session, "draft", "0")
    for _ in range(3):
        _inv(pg_session, "issued", "100.00")
    # Netto != Brutto, sonst merkt kein Test den Wechsel auf netto.
    _inv(
        pg_session, "paid", "59.50",
        net=Decimal("50.00"), tax=Decimal("9.50"),
        bezahlt_am=heute,
    )
    _inv(pg_session, "cancelled", "0")

    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["total_invoices"] == 7
    assert ctx["open_invoices"] == 3      # nur 'issued'
    assert ctx["draft_count"] == 2
    # Umsatz: nur bezahlt, netto. Gestellte zaehlen nicht.
    assert Decimal(ctx["revenue_ytd"]) == Decimal("50.00")
    assert Decimal(ctx["paid_this_month"]) == Decimal("59.50")


def test_dashboard_bezahlt_diesen_monat_nutzt_zahlungsmonat(pg_session):
    """Juli-Rechnung, im laufenden Monat als bezahlt markiert, zaehlt jetzt."""
    heute = kalender_heute()
    inv = _inv(pg_session, "issued", "300.00", issue=date(2026, 7, 8))
    inv.status = "paid"
    inv.bezahlt_am = heute
    pg_session.commit()
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("300.00")


def test_dashboard_bezahlt_diesen_monat_ignoriert_vorherigen_monat(pg_session):
    heute = kalender_heute()
    if heute.month == 1:
        bezahlt = date(heute.year - 1, 12, 15)
    else:
        bezahlt = date(heute.year, heute.month - 1, 15)
    _inv(pg_session, "paid", "100.00", issue=date(2026, 7, 8), bezahlt_am=bezahlt)
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("0.00")


def test_dashboard_leer_ist_null(pg_session):
    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["total_invoices"] == 0
    assert ctx["open_invoices"] == 0
    assert ctx["draft_count"] == 0
    assert ctx["recent_invoices"] == []


def test_dashboard_per_http_route(client):
    """#42: die Route durchlaufen, nicht nur main.dashboard() direkt aufrufen."""
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "ÜBERSICHT" in r.text
    assert "RECHNUNGEN GESAMT" in r.text


def test_dashboard_http_zeigt_kennzahlen(client, pg_session):
    _inv(pg_session, "issued", "100.00")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert ">1<" in r.text or "1</p>" in r.text
    assert "100" in r.text
    assert "SCHULDIGE UMSATZSTEUER" in r.text
    assert "GESCH. STEUERABGABEN" in r.text


def test_dashboard_steuer_kennzahlen_im_kontext(pg_session):
    from app.models.company import Company

    company = pg_session.get(Company, 1)
    company.kst_satz_percent = Decimal("15.00")
    company.soli_auf_kst_percent = Decimal("5.50")
    company.gewerbe_hebesatz = 400
    pg_session.commit()

    _inv(
        pg_session, "issued", "119.00",
        net=Decimal("100.00"), tax=Decimal("19.00"),
    )
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["vat_liability_ytd"]) == Decimal("19.00")
    assert Decimal(ctx["steuer_ruecklage_ytd"]) == Decimal("29.83")
    assert Decimal(ctx["estimated_tax_ytd"]) == Decimal("48.83")  # 19 + 29,825 % von 100


def test_dashboard_steuer_kennzahlen_nutzt_einstellungen(pg_session):
    from app.models.company import Company

    company = pg_session.get(Company, 1)
    company.kst_satz_percent = Decimal("15.00")
    company.soli_auf_kst_percent = Decimal("5.50")
    company.gewerbe_hebesatz = 490
    pg_session.commit()

    _inv(
        pg_session, "issued", "119.00",
        net=Decimal("100.00"), tax=Decimal("19.00"),
    )
    ctx = main.dashboard(_request(), pg_session).context
    # 19 + 100 * 0,32975 = 52,975
    assert Decimal(ctx["estimated_tax_ytd"]) == Decimal("51.98")


def test_dashboard_ytd_ignoriert_gutschriften(pg_session):
    """#5: Gutschriften duerfen den YTD-Umsatz nicht aufblaehen."""
    heute = kalender_heute()
    _inv(
        pg_session, "paid", "119.00",
        net=Decimal("100.00"), tax=Decimal("19.00"),
        bezahlt_am=heute,
    )
    # Bezahlt und mit Zahlungsdatum im Jahr: nur der Typfilter haelt sie heraus.
    _gutschrift(pg_session, "paid", "50.00", bezahlt_am=heute)
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("100.00")


def test_dashboard_offene_posten_ignorieren_gutschriften(pg_session):
    """#14: ausgestellte Gutschriften sind keine offenen Forderungen."""
    _inv(pg_session, "issued", "100.00")
    _gutschrift(pg_session, "issued", "50.00")
    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["open_invoices"] == 1


def test_dashboard_liefert_offenen_betrag_und_ueberfaellig(pg_session):
    heute = kalender_heute()
    _inv(pg_session, "issued", "100.00", due=heute.fromordinal(heute.toordinal() - 5))
    _inv(pg_session, "issued", "50.00", due=heute)
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["open_amount"]) == Decimal("150.00")
    assert ctx["ueberfaellig"].anzahl == 1
    assert Decimal(ctx["ueberfaellig"].betrag) == Decimal("100.00")
    assert ctx["ueberfaellig"].aeltester_tage == 5


def test_dashboard_vormonat_und_vorjahr_im_kontext(pg_session):
    from app.services.dashboard_kennzahlen import vorjahres_stichtag

    heute = kalender_heute()
    if heute.month == 1:
        vormonat_tag = date(heute.year - 1, 12, 15)
    else:
        vormonat_tag = date(heute.year, heute.month - 1, 15)
    # Bezahlt dieses Jahr (netto 200) und Vorjahr zum Stichtag (netto 80).
    _inv(
        pg_session, "paid", "238.00",
        net=Decimal("200.00"), tax=Decimal("38.00"),
        issue=heute, bezahlt_am=heute,
    )
    _inv(
        pg_session, "paid", "95.20",
        net=Decimal("80.00"), tax=Decimal("15.20"),
        issue=vorjahres_stichtag(heute),
        bezahlt_am=vorjahres_stichtag(heute),
    )
    _inv(pg_session, "paid", "30.00", issue=heute, bezahlt_am=heute)
    _inv(pg_session, "paid", "12.00", issue=heute, bezahlt_am=vormonat_tag)

    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_previous_month"]) == Decimal("12.00")
    assert Decimal(ctx["revenue_prev_ytd"]) == Decimal("80.00")
    # YTD netto: 200 + 30, dazu 12 nur, wenn der Vormonat im selben Jahr liegt.
    # Im Januar ist er Dezember des Vorjahres: 230 statt 242.
    # Vorjahr 80 → (242 - 80) / 80 * 100 = 202,5 bzw. (230 - 80) / 80 * 100 = 187,5
    if vormonat_tag.year == heute.year:
        assert ctx["revenue_yoy_pct"] == Decimal("202.5")
    else:
        assert ctx["revenue_yoy_pct"] == Decimal("187.5")
    assert ctx["vat_quarter_label"].startswith("Q")
    assert "nicht_versendet_anzahl" in ctx


def test_dashboard_hinweisstreifen_fehlt_ohne_unversendete(pg_session, client):
    from datetime import datetime, timezone

    inv = _inv(pg_session, "issued", "100.00")
    inv.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    pg_session.commit()
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "ohne Versand" not in r.text


def _href_fuer_kpi(html: str, kpi: str) -> str:
    import re
    m = re.search(rf'data-kpi="{re.escape(kpi)}"\s+href="([^"]+)"', html)
    if not m:
        m = re.search(rf'href="([^"]+)"[^>]*\s+data-kpi="{re.escape(kpi)}"', html)
    assert m, f"kein Link mit data-kpi={kpi!r} im Dashboard-HTML"
    return m.group(1)


def _liste_gesamt(client, href: str) -> int:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(href).query)
    params = {k: v[0] for k, v in qs.items()}
    r = client.get("/invoices/", params=params)
    assert r.status_code == 200, href
    # Blaetterzeile: "N Rechnung" / "N Rechnungen"
    import re
    m = re.search(r"(\d+) Rechnung", r.text)
    assert m, f"keine Gesamtzahl in Liste fuer {href}"
    return int(m.group(1))


def test_dashboard_kachel_und_hinweis_links_stimmen_mit_liste(pg_session, client):
    """Befund 1+2: href aus dem HTML, nicht fest einkodiert; fehlende Filter machen rot.

    Daten: Gutschrift (art), versendet+unversendet (versand), ueberfaellig+heute (faellig),
    ungleiche Statuszaehlungen (Unterzeilen).
    """
    from datetime import datetime, timezone, timedelta

    heute = kalender_heute()
    for _ in range(2):
        _inv(pg_session, "draft", "0")
    # drei gestellte Standard: eine ueberfaellig unversendet, eine heute faellig unversendet,
    # eine versendet
    _inv(pg_session, "issued", "100.00", due=heute - timedelta(days=3))
    _inv(pg_session, "issued", "50.00", due=heute)
    versendet = _inv(pg_session, "issued", "70.00", due=heute)
    versendet.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for _ in range(4):
        _inv(pg_session, "paid", "10.00")
    for _ in range(5):
        _inv(pg_session, "cancelled", "0")
    _gutschrift(pg_session, "issued", "25.00")
    pg_session.commit()

    html = client.get("/dashboard").text
    assert "ohne Versand" in html
    ctx = main.dashboard(_request(), pg_session).context

    faelle = [
        ("offen", ctx["open_invoices"]),
        ("ueberfaellig", ctx["ueberfaellig"].anzahl),
        ("status-draft", ctx["belegzaehlung"].entwurf),
        ("status-issued", ctx["belegzaehlung"].gestellt),
        ("status-paid", ctx["belegzaehlung"].bezahlt),
        ("status-cancelled", ctx["belegzaehlung"].storniert),
        ("hinweis-versand", ctx["nicht_versendet_anzahl"]),
    ]
    abweichungen = []
    for kpi, erwartet in faelle:
        href = _href_fuer_kpi(html, kpi)
        gefunden = _liste_gesamt(client, href)
        if gefunden != erwartet:
            abweichungen.append(
                f"{kpi}: Kachel={erwartet}, Liste={gefunden}, href={href}"
            )
    assert not abweichungen, "Links und Liste weichen ab:\n" + "\n".join(abweichungen)


def test_dashboard_zeigt_entwuerfe_unterzeile(pg_session, client):
    _inv(pg_session, "draft", "0")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "/invoices?status=draft" in r.text
    assert "Entwurf" in r.text
