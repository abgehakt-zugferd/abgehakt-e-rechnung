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
DELETE_TABLES = ("invoices", "customers")
TRUNCATE_TABLES = ("invoices", "invoice_items", "customers")

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


def _build_install_sql() -> str:
    parts = [_FUNCTIONS]
    for t in DELETE_TABLES:
        parts.append(
            f"CREATE OR REPLACE TRIGGER gobd_no_delete_{t} "
            f"BEFORE DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION gobd_forbid_delete();"
        )
    for t in TRUNCATE_TABLES:
        parts.append(
            f"CREATE OR REPLACE TRIGGER gobd_no_truncate_{t} "
            f"BEFORE TRUNCATE ON {t} FOR EACH STATEMENT EXECUTE FUNCTION gobd_forbid_truncate();"
        )
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
