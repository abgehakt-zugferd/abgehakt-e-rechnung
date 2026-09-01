"""Fest verankerter Branding-Hinweis.

Der Footer ist NICHT abschaltbar: kein Enable-/Disable-Schalter, kein ENV-/
Settings-Hebel, kein {% if %}-Gate. Der Hinweis rendert immer. Einziger
Änderungspunkt ist diese Datei. Ihn zu entfernen ist eine Codeänderung und
verpflichtet bei Netzwerk-Betrieb laut AGPL §13 zur Offenlegung des geänderten
Quellcodes.
"""
from fastapi.templating import Jinja2Templates

from app.installation import is_testinstanz

PRODUCT_NAME = "Abgehakt"
SOURCE_URL = "https://github.com/abgehakt-zugferd/abgehakt-e-rechnung"


def register_branding_globals(templates: Jinja2Templates) -> None:
    """Macht die Branding-Konstanten als Jinja-Globals verfügbar.

    Jede Jinja2Templates-Instanz braucht das einzeln, weil jeder Router in
    diesem Projekt sein eigenes Jinja-Environment erzeugt (kein gemeinsamer
    Context-Processor vorhanden).
    """
    templates.env.globals["PRODUCT_NAME"] = PRODUCT_NAME
    templates.env.globals["SOURCE_URL"] = SOURCE_URL
    templates.env.globals["is_testinstanz"] = is_testinstanz
