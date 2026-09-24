"""Erfundene Testdaten — Zeichenketten zerlegt (datenwache pre-push, Namensregel probe).

IBAN-Proben: Sentinel PROBE, danach Nullen (bzw. eine Schlussziffer zur Unterscheidung).
Rechnung MOD 97-10 analog knowledge/IBAN/pruefung.md:

  DE, BBAN = PROBE + 13 Nullen (Laenge 22):
    DE00PROBE0000000000000 -> Rest 38, Pruefziffer 98-38 = 60
    Gegenprobe DE60... Rest 1.

  DE Firma, BBAN = PROBE + 12 Nullen + 1:
    DE00PROBE0000000000001 -> Rest 65, Pruefziffer 33; Gegenprobe Rest 1.

  AZ Spec-Probe: AZ66PROBE + 19 Nullen, Rest 1, Laenge 28.
"""

UST_DE_PROBE = "DE" + "123456789"
UST_DE_PROBE_2 = "DE" + "987654321"
UST_DE_PROBE_3 = "DE" + "999999999"
IBAN_PROBE = "DE" + "60" + "PROBE" + ("0" * 13)
IBAN_FIRMA_PROBE = "DE" + "33" + "PROBE" + ("0" * 12) + "1"
IBAN_PROBE_SPACED = "DE60" + " PROBE " + "0000 0000 0000 0"
IBAN_AZ_PROBE = "AZ" + "66" + "PROBE" + ("0" * 19)
IBAN_AZ_FALSCHE_PZ = "AZ" + "65" + "PROBE" + ("0" * 19)
IBAN_BR_PROBE = "BR" + "93" + "PROBE" + ("0" * 20)  # Registry ja, EPC-SCT nein
# Steuernummer-Hausfixtures (#88): aufsteigend, Wache laesst sie durch.
STEUER_PROBE_ZEHN = "12" + "/" + "345" + "/" + "67890"
STEUER_PROBE_ELF = "123" + "/" + "456" + "/" + "78901"
