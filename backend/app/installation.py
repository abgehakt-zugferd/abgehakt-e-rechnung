"""Installationstyp: Produktion vs. Ketten-Testinstanz.

Die Testinstanz zeigt im GUI „TESTINSTANZ" und leitet jeden SMTP-Versand
ausschließlich an TESTINSTANZ_MAIL_TO — nie an Kunden oder DATEV.
"""

from app.config import get_settings


def is_testinstanz() -> bool:
    return get_settings().installation_mode.strip().lower() == "testinstanz"


def testinstanz_mail_to() -> str:
    return get_settings().testinstanz_mail_to.strip()
