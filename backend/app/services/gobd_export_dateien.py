"""Originaldateien des Z3-Exports, einschließlich fehlender Archivkopien."""


def rechnungsdateien(zf, invoices, storage_path, missing):
    for inv in invoices:
        if inv.pdf_filename:
            pdf_path = storage_path / "pdfs" / inv.pdf_filename
            if pdf_path.exists():
                zf.writestr(f"dokumente/{inv.pdf_filename}", pdf_path.read_bytes())
            else:
                missing.append(f"{inv.invoice_number}: PDF fehlt ({inv.pdf_filename})")
        # `discarded` (#145) ist ein verworfener ENTWURF und hat wie `draft` nie
        # ein PDF gehabt — das ist kein fehlender Beleg. Die Zeile bleibt trotzdem
        # im Export: sie ist das, was die Nummernlücke erklärt.
        elif inv.status not in ("draft", "discarded"):
            missing.append(f"{inv.invoice_number}: kein PDF hinterlegt")

        xml_name = f"{inv.invoice_number}.xml"
        xml_path = storage_path / "xml" / xml_name
        if xml_path.exists():
            zf.writestr(f"dokumente/{xml_name}", xml_path.read_bytes())
        elif inv.zugferd_xml:
            # DB ist Primärspeicher der XML (docs/ARCHITEKTUR.md) — Datei nur Zweitablage.
            zf.writestr(f"dokumente/{xml_name}", inv.zugferd_xml)
        elif inv.status not in ("draft", "discarded"):
            missing.append(f"{inv.invoice_number}: XML fehlt ({xml_name})")



def uebergabedateien(zf, uebergaben, storage_path, missing):
    # Angenommene Übergabebelege (§ 12) sind aufbewahrungspflichtige
    # Unterlagen wie Rechnungen; ohne sie hätte der Prüfer die 389/381-
    # Gutschrift ohne ihren Ursprungsbeleg. Eigenordner im ZIP, Inhalt
    # unverändert, Richtung und Hash bleiben im Namen erhalten.
    #
    # Nur die Kopien der gereichten Annahme-Zeilen (#160): Der Router wählt
    # sie nach dem Datum der ANNAHME aus — derselbe Zeitraum, nach dem
    # rechnungen.csv gefiltert wird. Eine Kopie ohne Zeile ist ein Beleg,
    # dessen Annahme nicht vollendet wurde (§ 11: gewirkt hat die Zeile),
    # und gehört nicht in den Datenträger des Prüfzeitraums.
    im_zeitraum = {zeile.beleg_sha256 for zeile in uebergaben}
    geschrieben: set[str] = set()
    uebergabe_wurzel = storage_path / "uebergaben"
    if uebergabe_wurzel.is_dir():
        for datei in sorted(uebergabe_wurzel.rglob("*.json")):
            if datei.stem in im_zeitraum:
                zf.writestr(
                    "uebergaben/" + datei.relative_to(uebergabe_wurzel).as_posix(),
                    datei.read_bytes(),
                )
                geschrieben.add(datei.stem)
    # Eine Annahme-Zeile verspricht ihre Kopie (§ 12: ohne eigene Kopie keine
    # Wirkung). Fehlt sie im Speicher, ist das eine Lücke im Bestand, die der
    # Prüfer aus fehlende_dateien.txt erfahren muss — still weglassen hieße,
    # die Aufbewahrung lückenlos zu schienen.
    for zeile in uebergaben:
        if zeile.beleg_sha256 not in geschrieben:
            missing.append(
                f"Annahme {zeile.beleg_id}: Aufbewahrungskopie fehlt "
                f"(uebergaben/…/{zeile.beleg_sha256}.json)"
            )


