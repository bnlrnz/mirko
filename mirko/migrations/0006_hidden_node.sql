CREATE TABLE hidden_node (
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    hidden_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (target_kind, target_ref)
);

CREATE INDEX idx_hidden_node_target
    ON hidden_node(target_kind, target_ref);
