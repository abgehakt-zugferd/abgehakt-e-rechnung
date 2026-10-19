from app.services.belegsprache.grundlagen import Belegsprache
from app.services.belegsprache.modell import Belegdarstellung
from app.services.belegsprache.texte_de import DARSTELLUNG_DE
from app.services.belegsprache.texte_en import DARSTELLUNG_EN

_DE = Belegdarstellung(**DARSTELLUNG_DE)
_EN = Belegdarstellung(**DARSTELLUNG_EN)

_DARSTELLUNGEN: dict[Belegsprache, Belegdarstellung] = {"de": _DE, "en": _EN}


def darstellung(sprache: Belegsprache) -> Belegdarstellung:
    """Liefert die unveraenderliche Darstellung zur Sprache (zustandslos)."""
    return _DARSTELLUNGEN[sprache]
