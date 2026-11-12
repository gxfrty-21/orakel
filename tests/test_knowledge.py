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

    assert graph["statistik"] == {
        "notizen": 4, "links": 2, "unaufgeloest": 1, "ohne_verknuepfung": 1,
    }
    assert ("20-Strategien/alpha.md", "70-Wissen/beta.md") in kanten
    assert ("60-Fehler/gamma.md", "unaufgeloest:fehlt") in kanten
    assert knoten["20-Strategien/alpha.md"]["tags"] == ["strategie"]
    assert "Beta" in knoten["20-Strategien/alpha.md"]["auszug"]
    assert knoten["unaufgeloest:fehlt"]["unaufgeloest"] is True


def test_vault_graph_ist_bei_leerem_vault_ehrlich(tmp_path):
    graph = Vault(tmp_path / "vault").graph()

    assert graph["knoten"] == []
    assert graph["kanten"] == []
    assert graph["statistik"]["notizen"] == 0
    assert "keine Markdown-Notizen" in graph["hinweis"]
