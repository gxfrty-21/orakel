from __future__ import annotations

from hypothesis import given, settings, strategies as st

from paper_strategies import paper_erlaubt, paper_konfiguration


@settings(max_examples=100, derandomize=True, deadline=None)
@given(werte=st.lists(paper_konfiguration(), min_size=25, max_size=25))
def test_paper_strategie_ist_bei_wiederholten_ziehungen_stabil(werte):
    """Die gemeinsame Strategie bleibt über viele Ziehungen gültig und deterministisch."""
    for paper in werte:
        if paper is not None:
            assert isinstance(paper, dict)
            assert set(paper) <= {"broker", "order_freigabe"}
            vorher = dict(paper)
        else:
            vorher = None

        ergebnis = paper_erlaubt(paper)
        assert isinstance(ergebnis, bool)
        assert paper_erlaubt(paper) is ergebnis
        assert paper == vorher
