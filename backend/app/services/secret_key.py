"""Selbstverwalteter SECRET_KEY als Datei im storage-Volume (#99 §5.4, L7).

Warum eine Datei und nicht die Datenbank: der Schlüssel verschlüsselt Secrets
*in* der Datenbank (z. B. das SMTP-Passwort). Läge er darin, schützte er sich
selbst nicht mehr — und ein DB-Dump gäbe Klartext und Schlüssel in einem Griff.

Warum überhaupt selbstverwaltet: die Pilotnutzerin hat kein Terminal. Ein Start,
der eine handgeschriebene `.env` mit `openssl rand -hex 32` verlangt, ist für sie
eine Sackgasse.

Bewusst KEIN Import von `app.config` — die Settings rufen hier hinein (Zyklus).
"""
import os
import secrets
from pathlib import Path

DATEINAME = "secret.key"
LAENGE_BYTES = 32  # → 64 Hex-Zeichen


def lade_oder_erzeuge(storage_path: Path) -> str:
    """Liest den Schlüssel aus `<storage>/secret.key`, oder erzeugt ihn einmalig.

    Fail-closed: eine vorhandene, aber leere/unbrauchbare Datei wird NICHT
    überschrieben. Sie stillschweigend durch einen frischen Schlüssel zu ersetzen
    würde jeden verschlüsselten Bestandswert unlesbar machen — und zwar unbemerkt,
    weil `crypto.decrypt` unentschlüsselbare Werte unverändert durchreicht.
    """
    pfad = Path(storage_path) / DATEINAME

    if pfad.exists():
        schluessel = pfad.read_text(encoding="ascii").strip()
        if not schluessel:
            raise RuntimeError(
                f"{DATEINAME} ist leer oder unlesbar. Die Datei NICHT löschen — mit ihr "
                "sind gespeicherte Zugangsdaten (z. B. das SMTP-Passwort) verschlüsselt. "
                "Aus einem Backup zurückspielen."
            )
        return schluessel

    schluessel = secrets.token_hex(LAENGE_BYTES)
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        # Erst die Rechte, dann der Inhalt: bei umgekehrter Reihenfolge stünde der
        # Schlüssel kurzzeitig world-readable auf der Platte.
        pfad.touch(mode=0o600)
        pfad.chmod(0o600)  # touch respektiert mode nicht, wenn die Datei schon existiert
        pfad.write_text(schluessel, encoding="ascii")
    except PermissionError as fehler:
        # Erster Start auf einem Linux-Server: das entpackte `storage/` gehört dem
        # Menschen, der entpackt hat; das Programm läuft als eigener Systembenutzer.
        # Ohne diesen Zweig bricht der Start mit einem PermissionError-Stapel ab,
        # aus dem niemand den Handgriff ableiten kann — und zwar vor dem ersten
        # Bildschirm. Die Kennungen kommen aus dem laufenden Prozess: feste Zahlen
        # in der Meldung würden mit dem Basis-Image driften.
        raise RuntimeError(
            f"Das Verzeichnis {pfad.parent} ist für das Programm nicht beschreibbar, "
            "deshalb kann der Schlüssel für gespeicherte Zugangsdaten nicht angelegt "
            "werden. Einmalig im Projektverzeichnis ausführen: "
            f"sudo chown -R {os.getuid()}:{os.getgid()} storage"
        ) from fehler
    return schluessel
