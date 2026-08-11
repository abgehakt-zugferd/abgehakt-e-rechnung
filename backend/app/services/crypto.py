"""Ver-/Entschlüsselung von Secrets at rest (aktuell: SMTP-Passwort in AppConfig).

Der Fernet-Schlüssel wird deterministisch aus SECRET_KEY abgeleitet, damit dieselbe
Konfiguration ohne zusätzliches Key-Management ver- und entschlüsseln kann.
decrypt() reicht unentschlüsselbare Alt-Werte (Klartext) unverändert durch, damit der
Übergang ohne Datenverlust gelingt.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _derive_key(secret_key: str) -> bytes:
    if not secret_key:
        raise RuntimeError("SECRET_KEY nicht gesetzt – Verschlüsselung nicht möglich.")
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()  # 32 Byte
    return base64.urlsafe_b64encode(digest)


def _fernet(key: str | None) -> Fernet:
    secret = key if key is not None else get_settings().secret_key
    return Fernet(_derive_key(secret))


def encrypt(plaintext: str, *, key: str | None = None) -> str:
    if not plaintext:
        return plaintext
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str, *, key: str | None = None) -> str:
    if not token:
        return token
    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Übergang: Alt-Bestand im Klartext ist kein gültiges Token → unverändert zurück
        return token
