"""`validation_results` braucht einen Index auf `invoice_id` (Leistungsprüfung 09.08.2026).

Die Rechnungs-Detailseite holt zu jeder Rechnung das jüngste Prüfergebnis:

    db.query(ValidationResult).filter(ValidationResult.invoice_id == …)
      .order_by(ValidationResult.validated_at.desc()).first()

Ohne Index ist das ein vollständiger Durchlauf der Tabelle, und diese Tabelle
wächst schneller als jede andere: sie bekommt bei **jedem** Klick auf „prüfen"
eine Zeile, nicht erst beim Finalisieren, und sie wird nie aufgeräumt. Bei einem
Betrieb, der acht Jahre aufbewahrt, sammeln sich dort leicht fünfstellig viele
Zeilen an, während die Detailseite immer nur eine davon braucht.

Der Index deckt beide Teile der Abfrage ab: `invoice_id` für die Auswahl,
`validated_at` absteigend für das „jüngste". Ein Index allein auf `invoice_id`
zwänge Postgres, die Treffer danach noch zu sortieren.
"""
from sqlalchemy import inspect

from app.models.invoice import ValidationResult

TABELLE = "validation_results"


def test_das_modell_kennt_den_index():
    """Die Modelldefinition ist die Quelle, aus der `alembic check` vergleicht.
    Stünde der Index nur in der Migration, meldete `check` dauerhaft Drift."""
    indizes = {i.name for i in ValidationResult.__table__.indexes}

    assert any("invoice" in name for name in indizes), (
        f"Kein Index auf invoice_id in {ValidationResult.__tablename__}: {indizes}"
    )


def test_der_index_umfasst_invoice_id_und_das_pruefdatum():
    spalten = [
        [s.name for s in i.columns]
        for i in ValidationResult.__table__.indexes
    ]

    assert any("invoice_id" in s and "validated_at" in s for s in spalten), (
        "Ein Index nur auf invoice_id lässt Postgres danach noch sortieren; "
        f"gefunden: {spalten}"
    )


def test_der_index_liegt_wirklich_in_der_datenbank(pg_engine):
    """Gegenprobe gegen das echte Schema. Ein Index, den nur das Modell kennt,
    beschleunigt nichts."""
    indizes = inspect(pg_engine).get_indexes(TABELLE)
    spalten = [i["column_names"] for i in indizes]

    assert any("invoice_id" in (s or []) for s in spalten), (
        f"In der Datenbank fehlt der Index: {indizes}"
    )
