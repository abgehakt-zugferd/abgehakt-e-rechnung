# Öffentliche Schlüssel der Übergabe-Absender

Hier legt der Betreiber die öffentlichen Schlüssel seiner Absender ab: je
Absender ein Unterordner, darin je Schlüssel eine `.pub`-Datei (PEM) und ein
Beiblatt `.json`. Der Ordner ist nicht in Git; der lokale Build nimmt ihn mit
ins Abbild. Private Schlüssel gehören niemals hierher.

Die Ketten-Testinstanz nutzt dafür `schluessel-integration/` (neben `backend/`),
nicht diesen Ordner. Den Feldbestand des Beiblatts beschreibt
`docs/INTEGRATION-TESTINSTANZ.md`.
