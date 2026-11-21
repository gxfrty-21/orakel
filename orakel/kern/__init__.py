"""Handelskern des Orakels: Daten, Strategien, Backtest, Richter, Risiko, Paper.

Der Kern darf ausschliesslich Module aus diesem Paket und die gemeinsame Basis
``orakel.config`` importieren. Alles andere bleibt draussen, auch die
Zulieferung wie ``orakel.seed``, ``orakel.spider`` oder ``orakel.pipeline``;
die Grenze prüft ``import-linter`` in der CI (Vertrag in ``.importlinter``).
"""
