# Local database and cache design

Status: accepted

## Context

Mirko must be portable: a meeting's state should survive backup and transfer by
copying one folder. It also must respect a single-download policy while remotes
rename and reshuffle files, and it must never lose artifacts or notes when the
agenda disagrees with the user.

## Decision

Store all dynamic state in one **SQLite** database in WAL mode inside the meeting
folder, and store file content in a **content-addressed blob cache**
(`cache/blobs/<sha256>`) in the same folder. Logical paths, observations, lineage
assertions, notes, and sync manifests live in SQLite; blobs are immutable and
deduplicated. Access SQLite through a thin repository with raw SQL and numbered
migrations, not an ORM. No absolute paths are persisted, so the whole folder is the
unit of backup and transfer.

## Considered options

- **DuckDB** — better for analytical scans, but this is transactional app state with
  small tables; SQLite is already available and simpler to embed.
- **Flat-file JSON/SQLite hybrid** — simpler at first, but conflict/branch resolution,
  append-only assertions, and manifest diffs need transactions and indexes.
- **Mirror the FTP tree as the cache** — natural to browse, but renames and duplicate
  content cause re-downloads and break the single-download policy; a materialized
  `cache/mirror/` view can be regenerated from blobs instead.
- **ORM (SQLAlchemy)** — adds indirection for a schema this small; explicit SQL keeps
  every query inspectable and agent-maintainable.

## Consequences

- Moving the meeting folder moves the entire state; no external services.
- Identical content (e.g. a renamed working draft) costs one blob, and renames are
  cheap observations.
- The DB can be rebuilt from blobs plus `cache/index.json` only on a best-effort
  basis; the DB remains the source of truth for lineage and notes.
- Schema changes require explicit migrations, which is deliberate and testable.
