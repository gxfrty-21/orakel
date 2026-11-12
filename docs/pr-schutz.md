# Schutz von `main`

Seit dem 12. November 2026 gilt das Repository-Ruleset
`main: PR und gruene CI`:

- Änderungen erreichen `main` nur über einen Pull Request.
- Pflicht-Checks: `pytest` und `docker`; der Branch muss aktuell sein.
- Keine Force-Pushes, kein Löschen des Branches.
- Kein Bypass, auch nicht für Administratoren.

Dieser Test-PR verifiziert den Ablauf: Vor den grünen Checks ist der Merge
blockiert, danach erlaubt. Railway baut `main` nach dem Merge automatisch.
