-- Orakel Company-Schicht, Migration 1.
-- Additiv: bestehende Tabellen werden weder umbenannt noch gelöscht.
-- Ausgeführt von Facts.__init__ nach dem bestehenden SCHEMA_SQL.

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id TEXT PRIMARY KEY,
    rufname TEXT NOT NULL UNIQUE,
    dept TEXT NOT NULL,
    dept_name TEXT NOT NULL,
    role TEXT NOT NULL,
    rank TEXT NOT NULL DEFAULT 'mitglied',
    mission TEXT NOT NULL,
    station TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT 'analyst',
    autonomy INTEGER NOT NULL DEFAULT 1,
    reports_to TEXT NOT NULL DEFAULT '',
    backup TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    data_scope_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    memory_scope TEXT NOT NULL DEFAULT '',
    kpi TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_profiles_dept ON agent_profiles(dept, active);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES agent_tasks(id),
    created_by TEXT NOT NULL DEFAULT 'SYSTEM',
    assigned_to TEXT NOT NULL REFERENCES agent_profiles(agent_id),
    dept TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT 'daily_check',
    priority INTEGER NOT NULL DEFAULT 50,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (
        state IN ('proposed','queued','accepted','running','review','blocked',
                  'done','failed','dead_letter','cancelled')
    ),
    autonomy_level INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until TEXT,
    accepted_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    due_at TEXT,
    acceptance TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_tasks_queue
    ON agent_tasks(state, priority DESC, id);
CREATE INDEX IF NOT EXISTS ix_agent_tasks_agent
    ON agent_tasks(assigned_to, state);

CREATE TABLE IF NOT EXISTS agent_task_deps (
    task_id INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    depends_on INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'success' CHECK (kind IN ('success','any')),
    PRIMARY KEY (task_id, depends_on)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id INTEGER,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_agent_events_task ON agent_events(task_id, id);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    requires_ack INTEGER NOT NULL DEFAULT 0,
    ack_at TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_agent_messages_thread ON agent_messages(thread_id, id);
CREATE INDEX IF NOT EXISTS ix_agent_messages_to ON agent_messages(to_agent, ack_at);

CREATE TABLE IF NOT EXISTS agent_memories (
    agent_id TEXT NOT NULL REFERENCES agent_profiles(agent_id),
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, scope, key)
);

CREATE TABLE IF NOT EXISTS agent_scores (
    agent_id TEXT NOT NULL REFERENCES agent_profiles(agent_id),
    period TEXT NOT NULL,
    tasks_done INTEGER NOT NULL DEFAULT 0,
    evidence_coverage REAL NOT NULL DEFAULT 0,
    rework INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, period)
);

CREATE TABLE IF NOT EXISTS company_policies (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'weich',
    updated_by TEXT NOT NULL DEFAULT 'SYSTEM',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES conference_sessions(id),
    level INTEGER NOT NULL DEFAULT 1 CHECK (level IN (1,2,3)),
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    rationale TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    deadline TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_decisions_status ON company_decisions(status, deadline);

CREATE TABLE IF NOT EXISTS company_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER REFERENCES company_decisions(id),
    task_id INTEGER REFERENCES agent_tasks(id),
    owner TEXT NOT NULL,
    due TEXT,
    status TEXT NOT NULL DEFAULT 'offen',
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_actions_status ON company_actions(status, due);

CREATE TABLE IF NOT EXISTS conference_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_date TEXT NOT NULL UNIQUE,
    scheduled_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    phase TEXT NOT NULL DEFAULT 'vorbereitung',
    quorum INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'geplant',
    protocol_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_conference_sessions_status ON conference_sessions(status, scheduled_date);

CREATE TABLE IF NOT EXISTS conference_attendance (
    session_id INTEGER NOT NULL REFERENCES conference_sessions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    present INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'mitglied',
    PRIMARY KEY (session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS conference_statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES conference_sessions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conference_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES conference_sessions(id) ON DELETE CASCADE,
    decision_id INTEGER NOT NULL REFERENCES company_decisions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    vote TEXT NOT NULL CHECK (vote IN ('ja','nein','enthaltung')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (decision_id, agent_id)
);

CREATE TABLE IF NOT EXISTS room_state (
    room_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'offen',
    active_agents INTEGER NOT NULL DEFAULT 0,
    last_event TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
