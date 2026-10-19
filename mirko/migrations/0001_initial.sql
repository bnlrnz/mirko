CREATE TABLE schema_migration (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE meeting_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE sync_state (
    source_kind TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    next_due_at TEXT,
    health TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (source_kind, endpoint_id)
);

CREATE TABLE remote_entry (
    endpoint_id TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER,
    mtime TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_blob_hash TEXT,
    missing_since TEXT,
    PRIMARY KEY (endpoint_id, path, name)
);

CREATE TABLE blob (
    hash TEXT PRIMARY KEY,
    size INTEGER NOT NULL CHECK (size >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE tdoc (
    tdoc_number TEXT PRIMARY KEY,
    agenda_item TEXT,
    topic TEXT,
    title TEXT,
    source TEXT,
    type TEXT,
    for_action TEXT,
    release TEXT,
    wi_code TEXT,
    avail INTEGER CHECK (avail IN (0, 1) OR avail IS NULL),
    treated INTEGER CHECK (treated IN (0, 1) OR treated IS NULL),
    treated_note TEXT,
    decision TEXT,
    state_source TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    is_tracked INTEGER NOT NULL DEFAULT 0 CHECK (is_tracked IN (0, 1)),
    is_provisional INTEGER NOT NULL DEFAULT 0 CHECK (is_provisional IN (0, 1)),
    raw_meta TEXT
);

CREATE TABLE artifact (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    logical_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    tdoc_number TEXT REFERENCES tdoc(tdoc_number),
    blob_hash TEXT REFERENCES blob(hash),
    remote_size INTEGER,
    remote_mtime TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source_kind TEXT NOT NULL,
    endpoint_id TEXT,
    is_ephemeral INTEGER NOT NULL DEFAULT 0 CHECK (is_ephemeral IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'present',
    raw_meta TEXT
);

CREATE TABLE artifact_observation (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifact(id),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    remote_size INTEGER,
    remote_mtime TEXT,
    blob_hash TEXT REFERENCES blob(hash),
    change_kind TEXT NOT NULL
);

CREATE TABLE ingest_run (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    endpoint_id TEXT,
    path TEXT,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    content_hash TEXT,
    row_count INTEGER,
    status TEXT NOT NULL
);

CREATE TABLE tracked_tdoc (
    tdoc_number TEXT PRIMARY KEY REFERENCES tdoc(tdoc_number),
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    added_by TEXT,
    origin TEXT
);

CREATE TABLE assertion (
    id INTEGER PRIMARY KEY,
    subject_kind TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_kind TEXT,
    object_ref TEXT,
    value TEXT,
    source TEXT NOT NULL,
    source_ref TEXT,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
    superseded_by INTEGER REFERENCES assertion(id),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    detail TEXT
);

CREATE TABLE conflict (
    id INTEGER PRIMARY KEY,
    predicate TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    assertion_ids TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    resolution TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT
);

CREATE TABLE note (
    id INTEGER PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    body TEXT NOT NULL,
    position_tag TEXT CHECK (position_tag IN ('Support', 'Object', 'Clarify') OR position_tag IS NULL),
    author TEXT,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE thread (
    id INTEGER PRIMARY KEY,
    root_message_id TEXT,
    normalized_subject TEXT NOT NULL
);

CREATE TABLE email (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    thread_id INTEGER REFERENCES thread(id),
    subject TEXT,
    from_addr TEXT,
    to_addrs TEXT,
    cc_addrs TEXT,
    date_utc TEXT,
    agenda_item TEXT,
    meeting_id TEXT,
    body_blob_hash TEXT REFERENCES blob(hash),
    raw_blob_hash TEXT REFERENCES blob(hash),
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    inference TEXT
);

CREATE TABLE email_mention (
    email_id INTEGER NOT NULL REFERENCES email(id),
    tdoc_number TEXT NOT NULL REFERENCES tdoc(tdoc_number),
    scope TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    PRIMARY KEY (email_id, tdoc_number, scope)
);

CREATE INDEX idx_tdoc_agenda_item ON tdoc(agenda_item);
CREATE INDEX idx_artifact_tdoc ON artifact(tdoc_number);
CREATE INDEX idx_artifact_ephemeral ON artifact(is_ephemeral);
CREATE INDEX idx_artifact_logical_path ON artifact(logical_path);
CREATE INDEX idx_artifact_observation_artifact ON artifact_observation(artifact_id, observed_at);
CREATE INDEX idx_assertion_subject ON assertion(subject_ref, predicate, active);
CREATE INDEX idx_assertion_object ON assertion(object_ref);
CREATE INDEX idx_conflict_subject ON conflict(subject_ref, predicate, status);
CREATE INDEX idx_note_target ON note(target_kind, target_ref);
CREATE INDEX idx_email_date ON email(date_utc);
CREATE INDEX idx_email_thread ON email(thread_id);
CREATE INDEX idx_email_mention_tdoc ON email_mention(tdoc_number);
CREATE INDEX idx_remote_entry_path ON remote_entry(endpoint_id, path);
CREATE INDEX idx_sync_state_due ON sync_state(next_due_at);

CREATE VIRTUAL TABLE email_fts USING fts5(
    message_id UNINDEXED,
    body,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE tdoc_fts USING fts5(
    tdoc_number UNINDEXED,
    title,
    tokenize = 'unicode61'
);
