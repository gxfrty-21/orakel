-- Downgrade zu 0002_company.sql.
-- ACHTUNG: loescht die Tabellen und ihre Daten dieser Migration.

DROP TABLE IF EXISTS room_state;
DROP TABLE IF EXISTS conference_votes;
DROP TABLE IF EXISTS conference_statements;
DROP TABLE IF EXISTS conference_attendance;
DROP TABLE IF EXISTS conference_sessions;
DROP TABLE IF EXISTS company_actions;
DROP TABLE IF EXISTS company_decisions;
DROP TABLE IF EXISTS company_policies;
DROP TABLE IF EXISTS agent_scores;
DROP TABLE IF EXISTS agent_memories;
DROP TABLE IF EXISTS agent_messages;
DROP TABLE IF EXISTS agent_events;
DROP TABLE IF EXISTS agent_task_deps;
DROP TABLE IF EXISTS agent_tasks;
DROP TABLE IF EXISTS agent_profiles;
