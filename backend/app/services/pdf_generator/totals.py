"""Steuer- und Summenblock fuer das Rechnungs-PDF."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph, Table, TableStyle

from app.services.belegart import belegart
from app.services.belegsummen import belegsummen

from .blocks import Styles
from .layout import GOLD, GOLD_TINT
from .logic import pct, zeigt_steuer

SUMMEN_BREITE = 8 * cm


def append_steuer_und_summenblock(story, invoice, d, styles: Styles, body_font, bold_font):
    tax_groups = _tax_groups(invoice.items)
    summen = belegsummen(invoice.items, getattr(invoice, "abzug_betrag", None))
    rows, endbetrag = _totals_data(invoice, d, styles, tax_groups, summen)
    betrag_breite = _betrag_breite(invoice, summen, tax_groups, endbetrag, styles, d, body_font, bold_font)
    totals_table = Table(rows, colWidths=[SUMMEN_BREITE * 0.6, max(SUMMEN_BREITE * 0.4, betrag_breite)])
    totals_table.hAlign = "RIGHT"
    totals_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), body_font),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, GOLD),
        ("BACKGROUND", (0, -1), (-1, -1), GOLD_TINT),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(totals_table)


def _tax_groups(items):
    groups: dict[Decimal, dict] = defaultdict(lambda: {"basis": Decimal("0"), "tax": Decimal("0")})
    for item in items:
        groups[item.tax_rate]["basis"] += item.net_amount
        groups[item.tax_rate]["tax"] += item.tax_amount
    return groups


def _totals_data(invoice, d, styles, tax_groups, summen):
    money = lambda v: d.format_betrag(v, getattr(invoice, "currency", "EUR") or "EUR")
    mit_abzug = summen.abzug > 0
    rows = _rows_ohne_steuer(invoice, d, styles, summen, mit_abzug, money)
    if zeigt_steuer(invoice):
        rows.extend(_steuer_rows(invoice, d, styles, summen, mit_abzug, tax_groups, money))
    label = d.label_gutschriftbetrag if belegart(invoice.invoice_type).intern == "self_billing" else d.label_rechnungsbetrag
    endbetrag = money(summen.brutto) if mit_abzug else money(invoice.gross_total)
    rows.append([Paragraph(f"<b>{label}</b>", styles.small_bold), Paragraph(f"<b>{endbetrag}</b>", styles.right_bold)])
    return rows, endbetrag


def _rows_ohne_steuer(invoice, d, styles, summen, mit_abzug, money):
    if not mit_abzug:
        return [[Paragraph(d.label_netto, styles.small), Paragraph(money(invoice.net_total), styles.right)]]
    grund = getattr(invoice, "abzug_grund", None) or ""
    return [
        [Paragraph(d.label_positionssumme, styles.small), Paragraph(money(summen.positionen_netto), styles.right)],
        [Paragraph(d.abzugzeile(grund), styles.small), Paragraph("-" + money(summen.abzug), styles.right)],
        [Paragraph(d.label_netto, styles.small), Paragraph(money(summen.steuerbasis), styles.right)],
    ]


def _steuer_rows(invoice, d, styles, summen, mit_abzug, tax_groups, money):
    rows = []
    if mit_abzug:
        # belegsummen setzt fuer einen Abzug einen einheitlichen Steuersatz
        # voraus: genau eine Steuerzeile, auf der Basis nach Abzug wie im XML.
        satz = next(iter(tax_groups))
        label = d.steuerzeile(pct(satz), money(summen.steuerbasis))
        rows.append([Paragraph(label, styles.small), Paragraph(money(summen.steuer), styles.right)])
        return rows
    for rate in sorted(tax_groups.keys()):
        g = tax_groups[rate]
        label = d.steuerzeile(pct(rate), money(g["basis"]))
        rows.append([Paragraph(label, styles.small), Paragraph(money(g["tax"]), styles.right)])
    return rows


def _betrag_breite(invoice, summen, tax_groups, endbetrag, styles, d, body_font, bold_font):
    money = lambda v: d.format_betrag(v, getattr(invoice, "currency", "EUR") or "EUR")
    mit_abzug = summen.abzug > 0
    if mit_abzug:
        # Die Betragsspalte ist so breit wie ihr breitester Betrag: in festen
        # 3,2 cm brach „EUR 12,345.67“ im Endbetrag auf zwei Zeilen um.
        werte = [money(summen.positionen_netto), "-" + money(summen.abzug), money(summen.steuerbasis)]
        if zeigt_steuer(invoice):
            werte.append(money(summen.steuer))
    else:
        werte = [money(invoice.net_total)] + [money(g["tax"]) for g in tax_groups.values()]
    return max(
        [pdfmetrics.stringWidth(v, body_font, styles.right.fontSize) for v in werte]
        + [pdfmetrics.stringWidth(endbetrag, bold_font, styles.right_bold.fontSize)]
    ) + 12
