CREATE TABLE node_status (
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Support', 'Object', 'Clarify')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (target_kind, target_ref)
);

CREATE INDEX idx_node_status_target
    ON node_status(target_kind, target_ref);

INSERT INTO node_status(target_kind, target_ref, status, updated_at)
SELECT target_kind, target_ref, position_tag, updated_at
FROM (
    SELECT target_kind, target_ref, position_tag, updated_at,
           ROW_NUMBER() OVER (
               PARTITION BY target_kind, target_ref
               ORDER BY created_at DESC, id DESC
           ) AS rank
    FROM note
    WHERE position_tag IS NOT NULL
)
WHERE rank = 1;

ALTER TABLE note DROP COLUMN position_tag;
