from __future__ import annotations

from orakel.nexus.sprache import erkenne


def test_deutsch_wird_an_stoppwoertern_erkannt():
    ergebnis = erkenne(
        "Die EZB lässt den Leitzins unverändert. Die Inflation ist nicht das einzige Thema.",
        "en",
    )
    assert ergebnis.code == "de"
    assert ergebnis.methode == "stoppwoerter"
    assert ergebnis.konfidenz >= 0.7


def test_englisch_wird_erkannt():
    ergebnis = erkenne(
        "The European Central Bank left the interest rate unchanged. "
        "Inflation is not the only issue.",
        "de",
    )
    assert ergebnis.code == "en"
    assert ergebnis.methode == "stoppwoerter"


def test_franzoesisch_wird_erkannt():
    ergebnis = erkenne(
        "La BCE a laissé le taux directeur inchangé. "
        "L'inflation n'est pas le seul sujet.",
        "en",
    )
    assert ergebnis.code == "fr"


def test_italienisch_wird_erkannt():
    ergebnis = erkenne(
        "La BCE ha lasciato il tasso invariato. L'inflazione non è l'unico tema.",
        "en",
    )
    assert ergebnis.code == "it"


def test_spanisch_wird_erkannt():
    ergebnis = erkenne(
        "El BCE dejó el tipo de interés sin cambios. "
        "La inflación no es el único tema.",
        "en",
    )
    assert ergebnis.code == "es"


def test_chinesisch_wird_an_zeichen_erkannt():
    ergebnis = erkenne("欧洲央行维持利率不变。通胀不是唯一的问题。", "en")
    assert ergebnis.code == "zh"
    assert ergebnis.methode == "zeichen"


def test_japanisch_wird_vor_cjk_erkannt():
    ergebnis = erkenne("欧州中央銀行は金利を据え置いた。インフレは唯一の問題ではない。", "en")
    assert ergebnis.code == "ja"
    assert ergebnis.methode == "zeichen"


def test_koreanisch_wird_erkannt():
    ergebnis = erkenne("유럽중앙은행은 금리를 동결했다. 인플레이션은 유일한 문제가 아니다.", "en")
    assert ergebnis.code == "ko"
    assert ergebnis.methode == "zeichen"


def test_kyrillisch_wird_erkannt():
    ergebnis = erkenne("Европейский центральный банк оставил ставку без изменений.", "en")
    assert ergebnis.code == "ru"
    assert ergebnis.methode == "zeichen"


def test_kurzer_titel_faellt_ehrlich_auf_die_quelle_zurueck():
    ergebnis = erkenne("EZB", "de")
    assert ergebnis.code == "de"
    assert ergebnis.methode == "quelle"
    assert ergebnis.konfidenz == 0.3


def test_ohne_text_und_ohne_quelle_ist_das_ergebnis_unbekannt():
    ergebnis = erkenne("", None)
    assert ergebnis.code == "und"
    assert ergebnis.methode == "unbekannt"
    assert ergebnis.konfidenz == 0.0
