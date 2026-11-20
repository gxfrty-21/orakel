-- Downgrade zu 0001_basis.sql.
-- ACHTUNG: loescht die Tabellen und ihre Daten dieser Migration.

DROP TABLE IF EXISTS intel_quellen;
DROP TABLE IF EXISTS intel_weiterleitungen;
DROP TABLE IF EXISTS intel_auftraege;
DROP TABLE IF EXISTS intel_inhalte;
DROP TABLE IF EXISTS nexus_forecast_results;
DROP TABLE IF EXISTS nexus_forecasts;
DROP TABLE IF EXISTS nexus_edges;
DROP TABLE IF EXISTS nexus_tasks;
DROP TABLE IF EXISTS nexus_missionen;
DROP TABLE IF EXISTS nexus_widersprueche;
DROP TABLE IF EXISTS nexus_claim_quellen;
DROP TABLE IF EXISTS nexus_claims;
DROP TABLE IF EXISTS nexus_quellen_reputation;
DROP TABLE IF EXISTS nexus_meldungen;
DROP TABLE IF EXISTS artikel;
DROP TABLE IF EXISTS betrieb_laeufe;
DROP TABLE IF EXISTS zustand;
DROP TABLE IF EXISTS auswahl;
DROP TABLE IF EXISTS agenten_laeufe;
DROP TABLE IF EXISTS konferenzen;
DROP TABLE IF EXISTS positionen;
DROP TABLE IF EXISTS konto;
DROP TABLE IF EXISTS ereignisse;
DROP TABLE IF EXISTS entscheide;
DROP TABLE IF EXISTS trades;
DROP TABLE IF EXISTS validierungen;
DROP TABLE IF EXISTS kerzen;
