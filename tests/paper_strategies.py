"""Gemeinsame Hypothesis-Strategien für Paper-/Broker-Tests."""

from __future__ import annotations

from hypothesis import strategies as st


class _FehltMarker:
    pass


FEHLT = _FehltMarker()
BROKER_WERTE = st.one_of(
    st.sampled_from(["csv", "CSV", "mock", "MOCK", "mt5", "unbekannt", ""]),
    st.none(), st.booleans(), st.integers(), st.text(), st.just(FEHLT),
)
FREIGABE_WERTE = st.one_of(
    st.booleans(), st.none(), st.integers(), st.floats(allow_nan=False),
    st.text(), st.just(FEHLT),
)


@st.composite
def paper_konfiguration(draw):
    """Erzeugt auch fehlende Abschnitte, Schlüssel und ungültige Werte."""
    if draw(st.booleans()):
        return None
    paper: dict[str, object] = {}
    if draw(st.booleans()):
        paper["broker"] = draw(BROKER_WERTE)
    if draw(st.booleans()):
        paper["order_freigabe"] = draw(FREIGABE_WERTE)
    return paper


def paper_erlaubt(paper: dict[str, object] | None) -> bool:
    if paper is None:
        return False
    broker = paper.get("broker", FEHLT)
    freigabe = paper.get("order_freigabe", FEHLT)
    return (
        isinstance(broker, str)
        and broker.strip().lower() in {"csv", "mock"}
        and freigabe is False
    )
