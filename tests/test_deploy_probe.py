"""Absichtlich roter Test — nur für den Gegentest des Deploy-Gates.

Wird im selben Vorgang per Revert wieder entfernt. Er soll zeigen, was ein
roter CI-Lauf auf ``main`` auslöst: die Tests scheitern, die Nachprüfung
startet nicht, und in Produktion ändert sich nichts.
"""


def test_absichtlich_rot():
    assert False, "Probe: absichtlich rot, damit die CI scheitert"
