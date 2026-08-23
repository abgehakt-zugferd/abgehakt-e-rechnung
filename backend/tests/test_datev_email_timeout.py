"""#9: SMTP ohne timeout blockiert den Worker unbegrenzt."""
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import datev_email


def _smtp_cfg():
    return SimpleNamespace(
        smtp_host="smtp.example.de",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_user="u",
        smtp_password="p",
        smtp_from="re@example.de",
        datev_bcc_email=None,
    )


def _pdf(tmp_path):
    p = tmp_path / "rechnung.pdf"
    p.write_bytes(b"%PDF-1.4 test")
    return p


def test_send_invoice_uebergibt_smtp_timeout(tmp_path):
    """Verbindungsaufbau muss begrenzt sein, nicht der globale Socket-Default None."""
    pdf = _pdf(tmp_path)
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_smtp_cfg()), \
         patch("smtplib.SMTP") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp.return_value)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        datev_email.send_invoice(
            to_email="kunde@example.com",
            invoice_number="RE-2026-001",
            customer_name="Test",
            pdf_path=pdf,
            bcc_datev=False,
            db=None,
        )
    _, kwargs = mock_smtp.call_args
    assert kwargs.get("timeout") == datev_email.SMTP_TIMEOUT


def test_send_test_email_uebergibt_smtp_timeout():
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_smtp_cfg()), \
         patch("smtplib.SMTP") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_smtp.return_value)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        datev_email.send_test_email("test@example.com", db=None)
    _, kwargs = mock_smtp.call_args
    assert kwargs.get("timeout") == datev_email.SMTP_TIMEOUT


def test_send_invoice_bricht_bei_stiller_verbindung_ab(tmp_path):
    """Server nimmt TCP an, antwortet nicht: mit timeout wird abgebrochen, nicht ewig gewartet."""
    pdf = _pdf(tmp_path)

    def silent_smtp(host, port, timeout=None):
        if timeout is None:
            raise RuntimeError("SMTP ohne timeout wuerde hier unbegrenzt blockieren")
        raise socket.timeout("Verbindung zum SMTP-Server hat das Zeitlimit ueberschritten")

    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_smtp_cfg()), \
         patch("smtplib.SMTP", side_effect=silent_smtp):
        with pytest.raises(datev_email.EmailError, match="Zeitlimit|timeout|SMTP"):
            datev_email.send_invoice(
                to_email="kunde@example.com",
                invoice_number="RE-2026-001",
                customer_name="Test",
                pdf_path=pdf,
                bcc_datev=False,
                db=None,
            )
