"""Orakel Trading-Engine.

Grundsätze (unveränderlich, siehe config.toml und Meister-Prompt):
- Ausschliesslich Paper-Trading. Es gibt keinen Pfad zu echten Orders.
- Fakten-Datenbank (SQLite) ist die einzige Wahrheit. Das Dashboard ist ein Spiegel.
- Der Richter entscheidet über Strategien, nicht die KI.
"""

__version__ = "0.1.0"
SCHEMA = 2
