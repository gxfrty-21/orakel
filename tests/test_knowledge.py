from __future__ import annotations

from orakel.knowledge import Vault


def test_vault_graph_liest_notizen_und_wikilinks(tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.notiz("strategien", "Alpha", "[[Beta|B]] und [[Beta]]", tags=["strategie"])
    vault.notiz("wissen", "Beta", "# Beta\nInhalt der Notiz", tags=["wissen"])
    vault.notiz("fehler", "Gamma", "[[Fehlt]]", tags=["fehler"])
    vault.notiz("wissen", "Delta", "# Delta\nOhne Link", tags=["wissen"])

    graph = vault.graph()
    knoten = {n["id"]: n for n in graph["knoten"]}
    kanten = {(k["von"], k["nach"]) for k in graph["kanten"]}

    # Der automatisch gepflegte Index liegt ebenfalls als Notiz im Vault.
    assert graph["statistik"] == {
        "notizen": 5, "links": 2, "unaufgeloest": 1, "ohne_verknuepfung": 2,
    }
    assert ("20-Strategien/alpha.md", "70-Wissen/beta.md") in kanten
    assert ("60-Fehler/gamma.md", "unaufgeloest:fehlt") in kanten
    assert knoten["20-Strategien/alpha.md"]["tags"] == ["strategie"]
    assert "Beta" in knoten["20-Strategien/alpha.md"]["auszug"]
    assert knoten["unaufgeloest:fehlt"]["unaufgeloest"] is True


def test_vault_index_aktualisiert_sich_nach_jeder_notiz(tmp_path):
    vault = Vault(tmp_path / "vault")

    vault.notiz("wissen", "Eins", "Inhalt")
    index = (vault.wurzel / "00-Index" / "index.md").read_text(encoding="utf-8")
    assert "| wissen | 1 |" in index

    vault.notiz("wissen", "Zwei", "Inhalt")
    vault.notiz("fehler", "Drei", "Inhalt")
    index = (vault.wurzel / "00-Index" / "index.md").read_text(encoding="utf-8")
    assert "| wissen | 2 |" in index
    assert "| fehler | 1 |" in index


def test_vault_graph_ist_bei_leerem_vault_ehrlich(tmp_path):
    graph = Vault(tmp_path / "vault").graph()

    assert graph["knoten"] == []
    assert graph["kanten"] == []
    assert graph["statistik"]["notizen"] == 0
    assert "keine Markdown-Notizen" in graph["hinweis"]
