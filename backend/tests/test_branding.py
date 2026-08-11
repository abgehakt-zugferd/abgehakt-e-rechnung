"""Tests für den Branding-Footer-Mechanismus (Spec 3.5.1): der Hinweis ist NICHT
abschaltbar — kein Enable-Flag, kein {% if %}-Gate. Das End-to-End-Rendering über
einen echten Router prüft test_export_router.py."""
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

import app.branding as branding
from app.branding import PRODUCT_NAME, SOURCE_URL, register_branding_globals

PARTIAL = "partials/_branding_footer.html"


def test_no_enable_flag_exists():
    """Spec 3.5.1: nicht abschaltbar — es darf keinen Enable-/Disable-Schalter
    (mehr) geben."""
    assert not hasattr(branding, "BRANDING_FOOTER_ENABLED")


def test_partial_has_no_conditional_gate():
    """Der Footer darf nicht hinter einem {% if %} liegen — sonst wäre er über
    einen (Context-)Wert ausblendbar."""
    src = Path("app/templates").joinpath(PARTIAL).read_text(encoding="utf-8")
    assert "{% if" not in src
    assert "BRANDING_FOOTER_ENABLED" not in src


def test_partial_always_renders_branding():
    env = Environment(loader=FileSystemLoader("app/templates"))
    html = env.get_template(PARTIAL).render(
        PRODUCT_NAME="Testprodukt",
        SOURCE_URL="https://example.test/repo",
    )
    assert "Powered by" in html
    assert "Testprodukt" in html
    assert 'href="https://example.test/repo"' in html
    assert 'rel="noopener"' in html


def test_register_branding_globals_sets_jinja_globals():
    templates = Jinja2Templates(directory="app/templates")
    register_branding_globals(templates)
    assert templates.env.globals["PRODUCT_NAME"] == PRODUCT_NAME
    assert templates.env.globals["SOURCE_URL"] == SOURCE_URL
    assert "BRANDING_FOOTER_ENABLED" not in templates.env.globals


def test_branding_globals_registered_on_every_router_templates_instance():
    """Jeder Router hat sein eigenes Jinja-Environment (Global Constraints) —
    ohne register_branding_globals in JEDEM würde der Footer auf einzelnen Seiten
    fehlen."""
    from app import main
    from app.routers import customers, export, invoices, settings as settings_router

    for module in (main, export, customers, invoices, settings_router):
        assert module.templates.env.globals["PRODUCT_NAME"] == branding.PRODUCT_NAME
        assert module.templates.env.globals["SOURCE_URL"] == branding.SOURCE_URL


def test_footer_renders_through_every_router_instance():
    """Beweist, dass JEDE Router-Template-Instanz den Footer tatsächlich ausgibt
    — nicht nur, dass die Globals gesetzt sind. Die Platzhalterwerte enthalten
    <> und werden unter der (autoescapenden) Jinja2Templates-Umgebung escaped,
    deshalb hier auf die zeichensicheren Textbausteine 'Powered by'/'Quellcode'
    prüfen statt auf PRODUCT_NAME/SOURCE_URL wörtlich."""
    from app import main
    from app.routers import customers, export, invoices, settings as settings_router

    for module in (main, export, customers, invoices, settings_router):
        html = module.templates.env.get_template(PARTIAL).render()
        assert "Powered by" in html, f"Footer fehlt in {module.__name__}"
        assert "Quellcode" in html, f"Quellcode-Link fehlt in {module.__name__}"
