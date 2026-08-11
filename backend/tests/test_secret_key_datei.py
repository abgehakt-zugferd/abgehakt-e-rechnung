"""Der SECRET_KEY verwaltet sich selbst (#99 §5.4, Leitplanke L7).

Die Pilotnutzerin hat kein Terminal. Ein Start, der „SECRET_KEY muss in der
.env-Datei gesetzt sein" verlangt, ist für sie eine Sackgasse — sie müsste eine
Datei anlegen, die es noch nicht gibt, mit einem Wert, den sie nicht erzeugen kann.

Der Schlüssel liegt deshalb als Datei im storage-Volume, NICHT in der Datenbank:
er verschlüsselt das SMTP-Passwort *in* dieser Datenbank. Läge er darin, schützte
er sich selbst nicht mehr. Und er muss über Neustarts **stabil** bleiben — ein neu
gewürfelter Schlüssel macht das gespeicherte SMTP-Passwort unlesbar.
"""
import os
import stat

import pytest

from app.config import Settings
from app.services import crypto
from app.services.secret_key import DATEINAME, lade_oder_erzeuge


def test_erzeugt_schluessel_wenn_keiner_da(tmp_path):
    """Frische Installation: es gibt keine Schlüsseldatei — das ist der Normalfall,
    kein Fehler."""
    schluessel = lade_oder_erzeuge(tmp_path)

    assert schluessel
    assert (tmp_path / DATEINAME).exists()


def test_erzeugter_schluessel_ist_lang_genug(tmp_path):
    """< 32 Zeichen löst beim Start eine Warnung aus — den selbst erzeugten
    Schlüssel darf das nie treffen."""
    assert len(lade_oder_erzeuge(tmp_path)) >= 32


def test_datei_ist_nur_fuer_den_eigentuemer_lesbar(tmp_path):
    lade_oder_erzeuge(tmp_path)

    modus = stat.S_IMODE((tmp_path / DATEINAME).stat().st_mode)

    assert modus == 0o600, f"Schlüsseldatei ist zu offen: {oct(modus)}"


def test_zweiter_start_liest_denselben_schluessel(tmp_path):
    erster = lade_oder_erzeuge(tmp_path)
    zweiter = lade_oder_erzeuge(tmp_path)

    assert zweiter == erster


def test_smtp_passwort_bleibt_ueber_neustart_entschluesselbar(tmp_path):
    """Der eigentliche Punkt der Stabilität: würfelte der Start einen neuen
    Schlüssel, wäre das gespeicherte SMTP-Passwort nach dem Neustart Datenmüll."""
    vor_neustart = lade_oder_erzeuge(tmp_path)
    token = crypto.encrypt("geheimes-app-passwort", key=vor_neustart)

    nach_neustart = lade_oder_erzeuge(tmp_path)

    assert crypto.decrypt(token, key=nach_neustart) == "geheimes-app-passwort"


def test_zwei_installationen_bekommen_verschiedene_schluessel(tmp_path):
    """Kein eingebrannter Default: das Auslieferungs-Image trägt keinen Schlüssel,
    sonst hätte jede Installation denselben."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    assert lade_oder_erzeuge(a) != lade_oder_erzeuge(b)


def test_unlesbare_datei_bricht_klar_ab(tmp_path):
    """Fail-closed: eine leere/kaputte Schlüsseldatei darf NICHT stillschweigend
    durch einen frischen Schlüssel ersetzt werden — das machte jedes verschlüsselte
    Passwort unlesbar, ohne dass jemand es merkt."""
    (tmp_path / DATEINAME).write_text("")

    with pytest.raises(RuntimeError, match=DATEINAME):
        lade_oder_erzeuge(tmp_path)


# ── Verdrahtung in die Settings ──────────────────────────────────────────────

def test_settings_ohne_env_holen_den_schluessel_aus_der_datei(tmp_path, monkeypatch):
    """Ohne .env und ohne Umgebungsvariable startet die App trotzdem (L7)."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = Settings(secret_key="", storage_path=tmp_path, _env_file=None)

    assert settings.secret_key == (tmp_path / DATEINAME).read_text().strip()


def test_gesetzter_secret_key_hat_vorrang_und_legt_keine_datei_an(tmp_path):
    """Bestandsinstallationen mit .env behalten ihren Schlüssel — sonst wären
    dort alle verschlüsselten Werte auf einen Schlag unlesbar."""
    settings = Settings(secret_key="x" * 40, storage_path=tmp_path, _env_file=None)

    assert settings.secret_key == "x" * 40
    assert not (tmp_path / DATEINAME).exists()


def test_nicht_beschreibbares_storage_nennt_den_ausweg(tmp_path):
    """Erster Start auf einem Linux-Server: `storage/` gehört dem Menschen, der
    entpackt hat, das Programm läuft als eigener Systembenutzer. Ohne diesen Zweig
    endet der Start in einem PermissionError-Stapel, aus dem niemand ableiten kann,
    was zu tun ist — und das ausgerechnet vor dem ersten Bildschirm."""
    verzeichnis = tmp_path / "storage"
    verzeichnis.mkdir()
    verzeichnis.chmod(0o500)          # lesen und betreten, nicht schreiben
    try:
        with pytest.raises(RuntimeError) as fehler:
            lade_oder_erzeuge(verzeichnis)
    finally:
        verzeichnis.chmod(0o700)      # sonst scheitert das Aufräumen von tmp_path

    text = str(fehler.value)
    assert "chown" in text, "Die Meldung muss den Ausweg nennen, nicht nur das Problem"
    assert str(os.getuid()) in text and str(os.getgid()) in text, \
        "Feste Zahlen driften mit dem Basis-Image — die laufende Kennung ist die Wahrheit"
    assert str(verzeichnis) in text


def test_die_kennung_des_programmbenutzers_bleibt_100_101():
    """Das README nennt für Linux-Server `sudo chown -R 100:101 storage`. Diese Zahl
    stammt aus `adduser --system` im Dockerfile und ist die einzige Stelle in der
    Anleitung, die aus dem Bau kommt statt aus dem Text. Ändert das Basis-Image die
    Vergabe, ist der dokumentierte Handgriff falsch — und zwar unbemerkt, weil er
    ausgeführt wird, bevor jemand das Programm zum ersten Mal sieht."""
    assert (os.getuid(), os.getgid()) == (100, 101), \
        "Kennung geändert — die chown-Zeile im README (Abschnitt Installation) mitziehen"
