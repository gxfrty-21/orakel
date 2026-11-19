"""Handelskern des Orakels: Daten, Strategien, Backtest, Richter, Risiko, Paper.

Der Kern darf ausschliesslich Module aus diesem Paket sowie die gemeinsame
Basis (``orakel.config``, ``orakel.seed``) importieren. Alles, was Web, Agenten,
Nexus oder Raumschiff betrifft, bleibt draussen; die Grenze prüft
``import-linter`` in der CI (Vertrag in ``.importlinter``).
"""
