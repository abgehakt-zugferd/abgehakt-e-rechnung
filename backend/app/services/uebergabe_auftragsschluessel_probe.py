"""Form und Bestand des Auftragsschluessels (§§ 8, 8a, 8b).

Eine Quelle fuer rechnungsauftrag, aufstellungsauftrag und je Gutschrift
des abrechnungsauftrags: Muster per ganz_passt, danach die Frage an die
Empfangslage, ob zum Schluessel bereits ein nicht storniertes Dokument
besteht. Ausgelagert aus uebergabe_befund, damit der Leser nicht waechst.
"""

from __future__ import annotations

from typing import Optional, Protocol

from app.services.uebergabe_form import AUFTRAGSSCHLUESSEL_FORM, ganz_passt


class _FeststellungFabrik(Protocol):
    def __call__(
        self, code: str, pfad: str, *, erwartet: Optional[str] = None,
        erhalten: Optional[str] = None,
    ):
        ...


class _LageMitDokument(Protocol):
    def dokument_zu_auftragsschluessel(self, schluessel: str) -> Optional[str]:
        ...


def feststellungen_zu_schluessel(
    schluessel,
    pfad: str,
    lage: _LageMitDokument,
    feststellung: _FeststellungFabrik,
) -> list:
    """Form zuerst; Bestand nur bei formgerechtem Schluessel."""
    funde: list = []
    if not ganz_passt(AUFTRAGSSCHLUESSEL_FORM, schluessel):
        funde.append(feststellung(
            "WERT_UNBRAUCHBAR", pfad,
            erwartet="1 bis 128 Zeichen aus a-z, 0-9, : und -",
            erhalten=str(schluessel),
        ))
        return funde
    schon = lage.dokument_zu_auftragsschluessel(schluessel)
    if schon is not None:
        funde.append(feststellung(
            "AUFTRAG_SCHON_GERECHNET", pfad,
            erhalten=schon,
        ))
    return funde


def feststellungen_nutzlast_schluessel(
    nutzlast: dict,
    lage: _LageMitDokument,
    feststellung: _FeststellungFabrik,
) -> list:
    """§§ 8a und 8b: ein Schluessel oben in der Nutzlast."""
    return feststellungen_zu_schluessel(
        nutzlast["auftragsschluessel"],
        "$.nutzlast.auftragsschluessel",
        lage,
        feststellung,
    )


def feststellungen_gutschrift_schluessel(
    nutzlast: dict,
    lage: _LageMitDokument,
    feststellung: _FeststellungFabrik,
) -> list:
    """§ 8 ab 1.8: je Gutschrift ein Schluessel; alle Funde, ganzer Auftrag."""
    funde: list = []
    for nummer, gutschrift in enumerate(nutzlast["gutschriften"]):
        funde += feststellungen_zu_schluessel(
            gutschrift["auftragsschluessel"],
            f"$.nutzlast.gutschriften[{nummer}].auftragsschluessel",
            lage,
            feststellung,
        )
    return funde
