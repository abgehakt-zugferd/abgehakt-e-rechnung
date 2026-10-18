"""
GoBD-DB-Trigger (Spec §3/§4): BEFORE DELETE/TRUNCATE werfen P0001 — feuern
rollen-unabhängig (auch Owner/Superuser), zweite Verteidigungslinie unter den
ORM-Guards (services/*_guard.py). Single Source of Truth für Migration UND die
create_all-Test-DB (conftest ruft install()).

Scope (Spec §4): nur die bedingungslos verbotenen, katastrophalen Operationen —
Hard-DELETE + TRUNCATE. Die UPDATE-Statusmaschine bleibt bewusst ORM-only.
"""
from sqlalchemy import text
from sqlalchemy.engine import Connection

# invoice_items: KEIN DELETE-Trigger (Draft-Positionen sind legitim löschbar) —
# nur TRUNCATE ist dort nie legitim.
# aufstellungen: wie invoices, nie löschbar. aufstellung_anlagen: Das DELETE-
# Verbot ist bewusst UNBEDINGT (auch im Entwurf): Der Platz jeder Anlage ist
# durch (aufstellung_id, quelle) fix, Korrektur ist ein UPDATE der Zeile
# (neue Datei, neuer Hash) — eine gelöschte Anlagenzeile wäre ein
# verschwundener Dateinachweis, und genau den prüft der GoBD-Export.
DELETE_TABLES = (
    "invoices", "customers", "aufstellungen", "aufstellung_anlagen",
)
TRUNCATE_TABLES = (
    "invoices", "invoice_items", "customers", "aufstellungen",
    "aufstellung_anlagen",
)

_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION gobd_forbid_delete() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION
    'GoBD: Hard-Delete auf Tabelle % ist verboten — Status setzen (cancelled/rejected) '
    'bzw. deleted_at (Soft-Delete), niemals loeschen.', TG_TABLE_NAME
    USING ERRCODE = 'raise_exception';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION gobd_forbid_truncate() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'GoBD: TRUNCATE auf Tabelle % ist verboten (Paragraf 14b UStG).', TG_TABLE_NAME
    USING ERRCODE = 'raise_exception';
END;
$$ LANGUAGE plpgsql;
"""


def _trigger_sql(tabelle: str, ereignis: str, funktion: str, je: str) -> str:
    """Ein Trigger — aber nur, wenn die Tabelle existiert.

    Warum die Existenzsicherung: INSTALL_SQL ist eine BEWEGLICHE Quelle
    (Single Source of Truth), und Migration 001 legt sie bei jedem Durchlauf
    der Kette in einer Datenbank aus, in der spaetere Tabellen (hier:
    aufstellungen, Migration 030) noch nicht existieren. Ohne die Pruefung
    waere jede historische Kette — upgrade bis 017, 028, head — kaputt,
    sobald diese Liste waechst. Die Migration, die eine Tabelle anlegt,
    ruft dieselbe Quelle erneut (030: op.execute(INSTALL_SQL)), deshalb
    existiert der Trigger am Ende der Kette trotzdem — und zwar aus DIESER
    Datei, nirgends sonst.
    """
    return (
        f"DO $$ BEGIN "
        f"IF to_regclass('{tabelle}') IS NOT NULL THEN "
        f"CREATE OR REPLACE TRIGGER gobd_no_{ereignis}_{tabelle} "
        f"BEFORE {ereignis.upper()} ON {tabelle} "
        f"FOR EACH {je} EXECUTE FUNCTION {funktion}(); "
        f"END IF; "
        f"END $$;"
    )


def _build_install_sql() -> str:
    parts = [_FUNCTIONS]
    for t in DELETE_TABLES:
        parts.append(_trigger_sql(t, "delete", "gobd_forbid_delete", "ROW"))
    for t in TRUNCATE_TABLES:
        parts.append(_trigger_sql(t, "truncate", "gobd_forbid_truncate", "STATEMENT"))
    return "\n".join(parts)


def _build_uninstall_sql() -> str:
    parts = []
    for t in DELETE_TABLES:
        parts.append(f"DROP TRIGGER IF EXISTS gobd_no_delete_{t} ON {t};")
    for t in TRUNCATE_TABLES:
        parts.append(f"DROP TRIGGER IF EXISTS gobd_no_truncate_{t} ON {t};")
    parts.append("DROP FUNCTION IF EXISTS gobd_forbid_delete();")
    parts.append("DROP FUNCTION IF EXISTS gobd_forbid_truncate();")
    return "\n".join(parts)


INSTALL_SQL = _build_install_sql()
UNINSTALL_SQL = _build_uninstall_sql()


def install(conn: Connection) -> None:
    """Trigger + Funktionen anlegen (idempotent, CREATE OR REPLACE)."""
    conn.execute(text(INSTALL_SQL))


def uninstall(conn: Connection) -> None:
    conn.execute(text(UNINSTALL_SQL))
