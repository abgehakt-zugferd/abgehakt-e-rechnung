"""Tests für services/crypto.py – Fernet-Ver-/Entschlüsselung des SMTP-Passworts.

Regeln:
  - Round-Trip: decrypt(encrypt(x)) == x
  - Chiffrat != Klartext (nichts Lesbares in der DB)
  - Alt-Klartext (kein gültiges Token) wird von decrypt unverändert zurückgegeben (Übergang)
  - Leerwerte werden unverändert durchgereicht
"""
import pytest
from app.services import crypto

_KEY = "test-secret-key-mit-mindestens-32-zeichen!!"


def test_round_trip_with_explicit_key():
    token = crypto.encrypt("hunter2", key=_KEY)
    assert token != "hunter2"
    assert crypto.decrypt(token, key=_KEY) == "hunter2"


def test_decrypt_of_legacy_plaintext_returns_input():
    # Alt-Bestand: Wert ist noch Klartext, kein gültiges Fernet-Token
    assert crypto.decrypt("legacy-plaintext-pw", key=_KEY) == "legacy-plaintext-pw"


def test_empty_values_pass_through():
    assert crypto.encrypt("", key=_KEY) == ""
    assert crypto.decrypt("", key=_KEY) == ""


def test_missing_secret_key_raises_on_encrypt():
    with pytest.raises(RuntimeError):
        crypto.encrypt("x", key="")
