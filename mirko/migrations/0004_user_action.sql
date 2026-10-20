CREATE TABLE user_action (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    target_kind TEXT,
    target_ref TEXT,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_user_action_created
    ON user_action(created_at DESC, id DESC);

CREATE INDEX idx_user_action_target
    ON user_action(target_kind, target_ref);
