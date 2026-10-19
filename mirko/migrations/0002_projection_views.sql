CREATE VIEW edge_current AS
SELECT
    id AS assertion_id,
    subject_ref AS source,
    object_ref AS target,
    predicate AS kind,
    source,
    source_ref,
    confidence,
    verified,
    observed_at,
    detail
FROM assertion
WHERE subject_kind = 'tdoc'
  AND object_kind = 'tdoc'
  AND predicate IN ('revision_of', 'merged_into', 'based_on')
  AND active = 1
  AND muted = 0;

CREATE VIEW tdoc_current AS
SELECT * FROM tdoc;
