from fastapi.templating import Jinja2Templates

from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter
from app.services.belegart import belegart, manuelle_belegarten
from app.services.einheiten import formular_bezeichnungen

templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)
templates.env.globals["formular_bezeichnungen"] = formular_bezeichnungen
templates.env.globals["manuelle_belegarten"] = manuelle_belegarten
templates.env.globals["belegart"] = belegart
