# Mirko — System Design

Status: draft for implementation
Scope: 3GPP SA3 meeting contribution tracking (TDocs, working drafts, lineage, mail, agendas)
Target platform: Linux / NixOS, single user, local-first

---

## 1. Purpose and scope

Mirko tracks what happens to a set of 3GPP SA3 **TDocs** during a meeting week:

- which **working drafts** delegates are producing in `Inbox/Drafts/`,
- which **emails** announce or discuss them,
- how the **official agenda/allocation table** records their lineage and final state,
- which **final Inbox ZIP** exists,
- and what the user concluded, in notes and classifications.

It is a decision-support tool for one delegate watching a moving target, not a 3GPP
process re-implementation.

### 1.1 In scope

- One meeting per portable meeting folder.
- Manifest-diff polling over `lftp` against exactly one configured FTP endpoint.
- HTML ingestion of `AgendaWithTdocAllocation_*.htm` (authoritative state + lineage).
- Excel ingestion of the pre-meeting allocation table (prep data, provenance-aware).
- Filename heuristics for `Drafts/` (hints only, never authoritative).
- Mail ingestion from a local `mbox`, `.eml` file, or `EML` directory (no IMAP/POP client).
- Lineage graph + per-TDoc timeline, filters, detail view.
- User-managed node statuses and notes, manual lineage assertions, conflict repair.
- Whole-meeting Markdown export.
- Ephemeral-safe local cache, single-download policy, OS-default file opening.

### 1.2 Explicit non-goals (v1)

- No embedded LLM invocation. AI is a future external consumer (see §16).
- No multi-user/server mode, no cloud sync, no auth beyond loopback binding.
- No editing or re-uploading of documents back to FTP.
- No document-content parsing for `Release` / `WI Code` (see §7.3).
- No automatic cross-meeting analytics.
- No auto-failover between FTP endpoints (§10.2).
- No hard deletion of artifacts, assertions, or notes (§9.4).

---

## 2. Environment and stack

Observed environment: Python 3.14.7, Node 22.23.2, Nix 2.34.9, `sqlite3`, Firefox,
Chrome, LibreOffice. `lftp` is **not installed** and is an explicit runtime dependency.

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.14 + FastAPI + Uvicorn | Best parsing/mail/subprocess libraries; async subprocess keeps API responsive; auto OpenAPI is the future AI contract. |
| Frontend | React + TypeScript + Vite | Familiar, testable, LLM-maintainable; no graph library needed. |
| Graph | Hand-rolled SVG lane renderer | Git-log shape; ≤ tens of nodes; exact control; zero heavy deps. |
| Persistence | SQLite (WAL) | Portable single file, transactional, already available, ideal for app state. |
| Blob cache | Content-addressed files under the meeting folder | Dedup, renames, portability, auditability. |
| FTP | `lftp` invoked as a subprocess | Required by the network/proxy/WAP environment; works for FTP and HTTPS mirrors. |
| Mail | Local `mbox` / `.eml` file / `EML` directory via stdlib `mailbox` + `email` | Thunderbird or any client does fetching; removes IMAP/credential fragility. |
| Packaging | Nix flake + dev shell (Python, Node, lftp) | Reproducible NixOS setup; preflight blocks startup if `lftp` is missing. |

Process model: one FastAPI process, one serial background sync worker (thread or
asyncio task), one SQLite connection per request/task, WAL mode.

---

## 3. System context

```
              ┌──────────────────────────── Browser (React SPA) ───────────────────────────┐
              │  Rail: favourites   Center: lineage/filters   Right: detail/notes   │
              └───────────────────────────────────────▲──────────────────────────────────────┘
                                                      │ local JSON/SSE (127.0.0.1)
┌─────────────────────────────────────────────────────┴──────────────────────────────────────┐
│ FastAPI                                                                                     │
│  ├── API (read models, notes, assertions, conflicts, export, open-file)                     │
│  ├── Sync worker (serial):  FTP manifest diff → fetch → cache                                │
│  ├── Ingestors:             HTML agenda | Excel | filename hints | mail                      │
│  └── Projection builder:    artifacts + assertions → tdoc_current / edge_current            │
└───────────────┬─────────────────────────┬───────────────────────────┬───────────────────────┘
                │ lftp subprocess         │ filesystem watch/poll     │ open
        ┌───────▼────────┐        ┌───────▼─────────┐        ┌────────▼────────┐
        │ One FTP endpoint│        │ mbox / EML dir  │        │ xdg-open (no    │
        │ (local/remote/  │        │ (Thunderbird)   │        │ shell)          │
        │  public ftp)    │        └─────────────────┘        └─────────────────┘
        └─────────────────┘
                │
        ┌───────▼──────────────────────────────┐
        │ Meeting folder                        │
        │  meeting.json                         │
        │  mirko.sqlite                         │
        │  cache/blobs/<sha256>                 │
        │  cache/mirror/... (optional view)     │
        │  exports/                             │
        │  logs/                                │
        └───────────────────────────────────────┘
```

---

## 4. Meeting folder and `meeting.json`

One folder = one meeting = complete portable state. Moving the folder moves
everything; no absolute paths are stored.

```
<meeting-dir>/
  meeting.json
  mirko.sqlite
  mirko.sqlite-wal / -shm
  cache/
    blobs/<sha256>
    mirror/<source-relative-path>     # optional relative symlinks for external browsing
    index.json                        # human-readable path→blob snapshot
  exports/
  imports/                            # workbooks uploaded through the UI
  logs/
```

### 4.1 Config shape (illustrative)

```json
{
  "schema_version": 1,
  "meeting": {
    "id": "SA3#130",
    "title": "SA3#130 Prague",
    "timezone": "Europe/Prague",
    "days": ["2026-10-12", "2026-10-16"],
    "hours": { "start": "09:00", "end": "18:00" },
    "tdoc_series_prefix": "S3-26"
  },
  "source": {
    "kind": "local",
    "protocol": "ftp",
    "host": "10.10.10.10",
    "port": 21,
    "base_path": "/Meetings_3GPP_SYNC/SA3",
    "username": "anonymous",
    "password": null,
    "password_env": null,
    "tls": "none"
  },
  "mail": {
    "kind": "mbox",
    "path": "/home/ben/mail/sa3-130.mbox",
    "eml_dir": null
  },
  "paths": {
    "drafts": "Inbox/Drafts",
    "inbox": "Inbox",
    "agenda_glob": "AgendaWithTdocAllocation_*.htm",
    "excel": "S3-26_meeting_allocation.xlsx"
  },
  "poll": {
    "auto_sync": true,
    "meeting_interval_s": 45,
    "idle_interval_s": 600,
    "mail_interval_s": 120,
    "backoff_max_s": 900,
    "jitter": 0.2
  },
  "tracked_seed": ["S3-264481", "S3-264388"],
  "sync": { "lazy_drafts": true },
  "ui": {
    "default_mode": "auto",
    "bar_color": "#ffffff",
    "lineage_views": [
      {
        "id": "lineage-1",
        "label": "Agenda 5.3.1.3",
        "filters": {
          "agenda": "5.3.1.3",
          "type": "CR",
          "state": "agreed",
          "source": "Huawei",
          "tracked": false,
          "include_ephemeral": true,
          "hide_withdrawn": false,
          "hide_not_treated": false,
          "hide_unknown": false,
          "show_hidden": false
        }
      }
    ],
    "active_lineage_view": "lineage-1"
  }
}
```

Rules:

- **Exactly one** active `source` object. Switching endpoints is a deliberate edit
  (UI or file), never an automatic failover.
- Credentials: literal value or `password_env` indirection. File mode `0600`.
  Never logged, never exported, never sent to any AI hook. The settings API returns
  only `password_set`; it never reads a stored password back to the browser.
- `tracked_seed` is imported once into the DB; afterwards the tracked set is dynamic
  DB state, not config.
- `ui.lineage_views` is portable user workspace state: tab names and filters are
  written automatically, and `ui.active_lineage_view` restores the selected tab.
  These are optional, so older `meeting.json` files still load unchanged.
- `tdoc_series_prefix` expands short hints (`3846` → `S3-263846`) and is never guessed
  from filenames.
- The config is validated on startup against a JSON Schema; unknown keys warn.

Known endpoint presets (documentation only; still one active at a time):

| Kind | FTP URL | Auth | Notes |
|---|---|---|---|
| `local` | `ftp://10.10.10.10/` + `base_path` | anonymous | Default during meeting. Full view. |
| `remote` | short-lived e.g. `ftp://o2arena_prague.3gpp.org/` | meeting credentials via env | Lagging mirror; chosen manually. |
| `public` | `ftp://ftp.3gpp.org/Meetings_3GPP_SYNC/SA3/` | anonymous | Can see `Drafts/`; lags. |

`base_path` is relative to the FTP root, *not* to the HTTP browsing UI. The local
server also exposes an HTTP view at `http://10.10.10.10/ftp/`, and the public server
at an equivalent `https://ftp.3gpp.org/...` page, but the sync worker always talks
plain FTP and drops any `/ftp` URL segment, e.g. `ftp://10.10.10.10/` +
`/Meetings_3GPP_SYNC/SA3`.

---

## 5. Domain model

Terminology is defined in `GLOSSARY.md`. This section is the structural model.

### 5.1 Two levels

1. **Inter-TDoc (official) lineage** — nodes are **TDocs** (`S3-26XXXX`). Edges:
   - `revision_of` — one source, produced by a revision; the source is the baseline.
   - `merged_into` — one of several sources of a merge; the non-baseline sources.
   - `based_on` — weak/standalone `Replaces` relationship without a confirmed merge
     group, or an inferred LS-in → LS-out reply link (title match, unverified).
2. **Intra-TDoc events** — artifacts attached to one TDoc: initial submission,
   working drafts (`-rN`), emails, Inbox ZIP, meeting notes. Ephemeral but kept locally.
   The lineage renderer can show cached working drafts as dashed child nodes of
   their TDoc; this is visualization only, not a new TDoc identity.

A TDoc is the stable identity. A **working draft is not a new TDoc**; an official
revision **is** a new TDoc number.

### 5.2 State (Decision)

Canonical states observed in the real HTML (ingestor tolerates more):

`open, withdrawn, revised, merged, approved, agreed, endorsed, email approval,
postponed, noted, not pursued, replied to, not treated`

- `open` is the only transient state. Everything else is final for that TDoc;
  later progress appears as a *new* TDoc entry.
- `revised` = this TDoc was revised into a successor (expect `Replaced-by`).
- `merged` = this TDoc was a non-baseline source merged into a successor.
- `replied to` is used for LS in. `not treated` = not opened due to time.
- `approved` vs `agreed` is procedural per 3GPP (`CR` → agreed; `pCR`, `LS out`,
  living-document pCRs → approved). Mirko does not reinterpret it.
- Empty `Decision` on a TDoc row is projected as `open` with `state_source=inferred`.

`Wdrn` is **ignored**; it duplicates `Decision=withdrawn`.

### 5.3 Observed column semantics (HTML)

`Agenda | Topic | TDoc | Title | Source | Type | For | Avail | Treated | Decision | Wdrn | Replaced-by | Replaces`

- `Agenda` / `Topic` are grouped via `rowspan`; continuation rows are empty.
- `TDoc`, `Replaced-by`, `Replaces` contain exactly one TDoc token or are empty.
- `Treated` is not a clean boolean: 51 real rows look like
  `YesHuawei, ORANGE, CMCC didn't agree...`. Split the leading `Yes` from the
  remainder and store the remainder as a **meeting note**.
- `For`: `Approval | Agreement | Discussion | Endorsement | Decision | Information | - | empty`
  (case-insensitive; normalize `approval` → `Approval`).
- `Type`: `CR, pCR, draftCR, LS in, LS out, report, agenda, other, discussion,
  draft TS, draft TR, SID new, SID revised, WID new, WID revised`.
- `Replaces` = the document this row is based on (baseline). A source row that was
  itself a revision still carries its own `Replaces`.
- `Replaced-by` = the successor that replaced this row.

### 5.4 Lineage derivation (authoritative)

Do not derive merges from `Replaces` alone. Use the reverse index:

```
rows            = all HTML rows with a TDoc
sources_of[n]   = [r for r in rows if r.replaced_by == n]
baseline_of[n]  = n.replaces
for n, sources in sources_of:
    b = baseline_of[n] if baseline_of[n] in sources else
        the unique r in sources with decision == revised else
        the only source else UNRESOLVED
    for s in sources:
        edge s -> n : revision_of if s == b else merged_into
```

- If `sources_of[n]` is empty but `n.replaces` exists, emit a low-confidence
  `based_on` edge `n.replaces → n` and flag a data gap.
- If `decision == revised/merged` but no `Replaced-by` exists, flag a conflict.
- If the baseline cannot be determined, emit all candidate edges `verified=false`
  and open a conflict; never guess silently.
- Cross-agenda-item edges are valid.
- Exclude self-references and deduplicate.

---

## 6. Assertions, provenance, and conflict branches

All statements about lineage and state are stored as append-only **assertions**:

```
assertion(subject, predicate, object/value, source, confidence, verified,
          active, muted, superseded_by, observed_at, detail)
```

Sources and precedence:

| Source | Precedence | Active by default | Verified |
|---|---|---|---|
| `html` | authoritative | yes | yes |
| `excel` | prep | yes (fills gaps only) | no |
| `user` | provisional override | yes | no until HTML agrees |
| `filename` | speculative hint | no (ghost edge) | no |
| `email` | speculative hint | no (ghost edge) | no |

Rules:

- HTML **never silently deletes** user intent. A disagreement creates a **conflict**.
- Filename/email hints never auto-create official links; they render as dashed ghost
  edges and remain available through `/api/discovery`, promotable with one click.
- A manual assertion stays active and is re-flagged if later HTML still disagrees.
- Conflict resolution is **per predicate/subject**, not per node, and never deletes
  notes or artifacts.
- The obsolete branch is retained (`active=0`, `muted=1`) and rendered muted/dashed.
- The Conflicts pane presents the competing nodes side by side with their values,
  sources, source references, and confidence, and lets the user open either node.
- All artifacts/notes hang off TDocs/artifacts, not assertions, so resolution cannot
  orphan them.

---

## 7. Data ingestion

### 7.1 Polling and manifests

One serial sync worker. Never overlap `lftp` runs. Per source of truth, keep a
remote manifest keyed by `(endpoint_id, path, name)` with `size`, `mtime`, and the
last fetched blob hash.

For every cycle:

1. List `Drafts/`, `Inbox/`, and the meeting root (agenda files).
2. Diff against `remote_entry`.
3. Fetch new names and names whose `(size, mtime)` changed, except when
   `sync.lazy_drafts` is true: `Drafts/` entries are recorded in the manifest with
   `fetch_state=pending` and as `status=remote` artifacts, without downloading.
4. Record an `artifact_observation`; new content becomes a new blob (never overwrite
   an existing blob). This is the **single-download policy**: one fetch per remote
   identity, and no re-fetch while identity is unchanged. Deferred artifacts are
   fetched on demand (detail open, track, or lineage neighbour of a tracked TDoc)
   and then recorded with their blob hash; agenda HTML and Inbox stay eager.
5. Ingest agenda: choose the newest `AgendaWithTdocAllocation_*.htm` by filename
   timestamp; fetch only if content hash changed; parse; rebuild projections.
6. Ingest mail from the local mailbox incrementally (mtime/size + Message-ID).

There is no deletion propagation: files absent from a listing are marked
`missing_since` but retained, because `Drafts/` is append-only in practice and
because cached working drafts are valuable after the meeting.

### 7.2 `lftp` adapter

Interface:

```python
class FtpClient(Protocol):
    def list(self, path: str) -> list[RemoteEntry]: ...
    def fetch(self, path: str, dest: Path) -> None: ...
```

Implementations: `LftpFtpClient`, `FakeFtpClient` (tests). The worker depends only on
the protocol.

- FTP and HTTPS both go through `lftp` for environmental consistency.
- Commands are passed as an argument vector, never through a shell.
- Remote names are treated as untrusted: reject names containing newline, NUL, or
  control characters; quote/escape before embedding in an `lftp` command string;
  reject path traversal in cache paths.
- Listing parse supports Unix-style `ls -l` output; failures are logged with a raw
  sample but never abort the whole cycle.

### 7.3 HTML ingestion

Steps:

1. Parse with a tolerant HTML parser (reference implementation uses the stdlib
   `html.parser`; `lxml` remains an option). No script execution.
2. Resolve `Agenda`/`Topic` by forward-filling from the last populated section.
   The real file uses empty cells, not `rowspan`; `rowspan`/`colspan` are
   tolerated if a future meeting adds them.
3. Normalize cell text: NBSP → space, U+2011/U+2010/U+2013/U+2014 → `-`,
   collapse whitespace, preserve U+FFFD replacement characters as-is (do not guess).
4. Canonicalize TDoc tokens: after normalization, match `S3-?\d{6}`; also accept
   `S3_` and spacing variants and normalize to `S3-NNNNNN`.
5. Empty `TDoc` = agenda/section header row; update section context, emit no document.
6. Upsert the `tdoc` projection (HTML wins over Excel/non-empty fields).
7. Parse `Treated` into `(treated: bool|unknown, treated_note: str)`.
8. Derive lineage using §5.4.
9. Map `Decision`/`For`/`Type` through alias tables; unknown values are preserved
   verbatim and flagged.
10. Store an `ingest_run` with content hash, row count, and endpoint provenance.

Real-data quirks that the parser must tolerate (all observed):

- TDoc hyphen is **U+2011**, not ASCII `-`.
- 34 agenda-only rows have NBSP in `TDoc`; one final row has no TDoc cell.
- `Treated` notes are concatenated with no separator and may contain newlines.
- `Decision` contains `email approval`, `endorsed`, and `not treated`.
- `For` contains `Decision` and `Information`, plus a lowercase `approval`.
- Titles/notes contain U+FFFD (`didn�t`), en dashes, and embedded paragraphs.
- Many `Replaced-by` targets are shared by many sources (real merges; one target
  had 15 sources).

### 7.4 Excel ingestion

- Read with `openpyxl` (`read_only=True`, `data_only=True`); never execute macros.
- Detect the header row by matching the HTML column names; map via an alias table.
  The published `TDoc_List_Meeting_*.xlsx` uses `Agenda item`,
  `Agenda item description`, `TDoc Status`, `Is revision of` and `Revised to`
  for agenda, topic, decision, replaces and replaced-by respectively.
- If a root-level `.xlsx`/`.xls` does not match `paths.excel`, it is still
  classified as the allocation workbook (the published name varies by meeting).
- Same logical schema; `source=excel`, `verified=false`, lower precedence than HTML.
- Excel only fills gaps; it never overwrites a non-empty HTML value.
- Store the raw sheet as an artifact blob for audit.
- Stop reading after a long run of blank rows: the real workbooks report
  `max_row` near the Excel limit despite only ~900 rows of data.

### 7.5 Filename parsing (`Drafts/`, `Inbox/`)

A layered parser; every tier returns `(primary_tdoc, working_rev, source_hints,
document_version, confidence, raw)`.

**Tier 0 — normalization (not mutation):** Unicode dash → `-`, collapse runs of
spaces, case-fold only for matching; keep the raw filename forever.

**Tier 1 — primary TDoc:** first canonical `S3-?\d{6}` token, preferring one
immediately following a `draft`/`Draft`/`drafft` prefix. Accept `draft`, `Draft`,
`drafft`, `draft-`, `draft_`, `draft `, and bare `S3-...` names.

**Tier 2 — working revision:** the marker attached to the primary token, accepting
`-rN`, `_rN`, `rN` (no separator), `-vN` (document version, kept separately),
two-digit `rN`, and a trailing ` rN` in the freeform tail. If markers conflict
(e.g. `-r3-was-263713 ... r2.docx`), prefer the marker attached to the current
TDoc token, record the conflict as a hint, and never fail the parse.

**Tier 3 — source hints:** find the first hint phrase among
`was`, `was_`, `was-`, `_was_`, `-was-`, `revision of`, `merger of`, `merger_of`,
`merger-of`, `merger`, `merge of`, `merge_of`, `merge-of`, `merging`, `mergering`,
`merged`, then collect the run of TDoc tokens that follows. Connectors: comma,
`and`, underscore, plus, space, hyphen. Stop at a title-like token (`A#`, `KI#`,
`[`, a word, an agenda fragment). Remove the primary TDoc (self-references occur).
Expand bare 4-digit tokens (`3846`, `4272`, `4123`) using `tdoc_series_prefix`.

**Tier 4 — fallback:** no primary TDoc → keep the raw name as an artifact attached
to the agenda item if one can be inferred, otherwise to an `unfiled` bucket. Never
discard. Never create a TDoc from a malformed token such as `S3-26abcd`.

Observed corpus families the parser must handle (real filenames):

- Typos/prefixes: `drafft_S3-...`, `Draft_...`, `draft S3-...`, `draft-S3-...`, bare `S3-...`.
- Revision styles: `-r1`, `_r1`, `r1` appended, `-r16`, `-v5`, trailing ` r2`, `r3..docx`.
- Hints: `was`, `_was_`, `-was-`, `revision of`, `merger of`, `merger_of`, `merging`,
  `mergering`, `merge of`, `merge_of`, `merged`, `merger`.
- Multi-source separators: comma, `and`, `_`, `+`, space, hyphen chains
  (`4253-4276-4370-4356-4381`).
- Short sources: `3803`, `4313`, `4272`, `3799`, `3861`, `3846`, `4123`, `4167`, `4002`.
- Self-reference and duplicates: `merger_of_S3-264381_S3-264254` where the primary
  is itself a source; `S3-264163` repeated.
- Junk: `.lnk`, `.rtf`, `.zip`, `S3-2604090`, `S3-26abcd`, `S6- 263386`,
  `S3263763`, freeform meeting notes with no TDoc.
- Other groups' documents (`SP-...`) and non-contribution files.

All filename-derived links are **hints** (`source=filename`, inactive ghost edges).

### 7.6 Mail ingestion

- Source: one `mbox` file, one `.eml` file, or a directory of `.eml` files.
  Incremental via mtime/size and Message-ID dedup. No IMAP/POP.
- Parse headers with stdlib `email`; decode RFC 2047 subjects and bodies.
- Store the raw message blob (content-addressed) and extracted plain text for FTS5.
- Subject parse:

  1. Extract `[SA3#<n>]` when present.
  2. Examine all bracket groups: agenda item = one matching `\d+(\.\d+)*`;
     TDoc = one matching `S3-?\d+`; `KI#...` is not an agenda item.
  3. Extract TDoc tokens anywhere in the subject; a revision may be inside the
     bracket (`[S3-264549-r1]`) or immediately after it (`[S3-264463]-r1`).
  4. Parse source hints with the same Tier-3 parser.
  5. No TDoc token is normal (`[SA3#130][5.3.1.8.1] LS LS on ...`); attach to the
     agenda item only.

- Threading: `References`/`In-Reply-To` first; fallback normalized subject
  (strip `Re:`/`Fwd:`, collapse whitespace). Many 3GPP mails arrive as new
  top-level messages, so subject fallback matters.
- Scoping: ingest **all** mail, but surface/attach only:
  - TDoc matches in the subject (high confidence),
  - TDoc matches in the body (lower confidence, tagged `scope=body`),
  - agenda-item matches (Discovery view).
  Everything else stays searchable but unattached.
- One mail referencing multiple TDocs is attached to each lane (same Message-ID,
  multiple mentions). No "unfiled queue" of hundreds.

---

## 8. Persistence

SQLite, WAL, `foreign_keys=ON`, `synchronous=NORMAL`. Thin repository layer with
raw SQL and numbered SQL migrations; no ORM. `PRAGMA user_version` tracks schema.

### 8.1 Tables (logical)

```
schema_migration(version, applied_at)
meeting_meta(key, value)
sync_state(source_kind, endpoint_id, last_attempt_at, last_success_at,
           last_error, next_due_at, health)
remote_entry(endpoint_id, path, name, size, mtime, first_seen_at, last_seen_at,
             last_blob_hash, missing_since, PK(endpoint_id, path, name))
blob(hash PK, size, created_at)
artifact(id, kind, logical_path, filename, tdoc_number, blob_hash, remote_size,
         remote_mtime, first_seen_at, last_seen_at, source_kind, endpoint_id,
         is_ephemeral, status, raw_meta JSON)
artifact_observation(id, artifact_id, observed_at, remote_size, remote_mtime,
                     blob_hash, change_kind)
ingest_run(id, kind, endpoint_id, path, fetched_at, content_hash, row_count, status)
tdoc(tdoc_number PK, agenda_item, topic, title, source, type, for_action, release,
     wi_code, avail, treated, treated_note, decision, state_source,
     first_seen_at, last_seen_at, is_tracked, is_provisional, raw_meta JSON)
tracked_tdoc(tdoc_number PK, added_at, added_by, origin)
assertion(id, subject_kind, subject_ref, predicate, object_kind, object_ref, value,
          source, source_ref, confidence, verified, active, muted, superseded_by,
          observed_at, detail JSON)
conflict(id, predicate, subject_ref, assertion_ids JSON, status, resolution,
         created_at, resolved_at)
note(id, target_kind, target_ref, body, author, source,
     created_at, updated_at)
node_status(target_kind, target_ref, status, updated_at,
            PK(target_kind, target_ref))
hidden_node(target_kind, target_ref, hidden_at, PK(target_kind, target_ref))
user_action(id, action, target_kind, target_ref, detail, created_at)
email(id, message_id PK, thread_id, subject, from_addr, to_addrs, cc_addrs,
      date_utc, agenda_item, meeting_id, body_blob_hash, raw_blob_hash,
      ingested_at, inference JSON)
email_mention(email_id, tdoc_number, scope, confidence,
              PK(email_id, tdoc_number, scope))
thread(id, root_message_id, normalized_subject)
```

Derived views: `tdoc_current`, `edge_current` (active assertions for
`revision_of` / `merged_into` / `based_on`).

Indices: `tdoc(agenda_item)`, `artifact(tdoc_number)`, `artifact(is_ephemeral)`,
`assertion(subject_ref, predicate, active)`, `assertion(object_ref)`,
`email(date_utc)`, `email_mention(tdoc_number)`, FTS5 on email body and TDoc title.

### 8.2 Single-download invariants

- One blob per content hash.
- One remote identity (path+size+mtime) may be fetched once; a changed identity
  yields a new observation and, if content differs, a new blob.
- Re-running ingestion on identical content is idempotent.

### 8.3 Portability

- No absolute paths in the DB; everything resolves relative to the meeting folder.
- Blobs are content-addressed and immutable.
- `cache/index.json` can rebuild the logical view if the DB is lost (best effort).

---

## 9. Cache, file access, and lifecycle

### 9.1 Cache layout

`cache/blobs/<sha256>` is the only authoritative storage. `cache/mirror/` is an
optional, regenerable view with relative symlinks that mirrors source paths
(`Inbox/Drafts/...`, `Inbox/...`) for external browsing. It is never the source of
truth and is regenerated on sync/finalize.

### 9.2 Opening files

Clicking an artifact opens the cached blob with the OS default application:

- `subprocess.run([opener, materialized_path])`, never a shell.
- The blob is materialized under a temp/cache path with the original filename and
  extension (some office apps care), or symlinked where safe.
- Opener default `xdg-open`, configurable per meeting.
- Auto-open is restricted to document extensions (`.doc`, `.docx`, `.pdf`, `.rtf`,
  `.xls`, `.xlsx`, `.ppt`, `.pptx`, `.txt`, `.zip` view). Executable/shortcut types
  (`.lnk`, `.desktop`, `.exe`, `.sh`) require explicit confirmation and are never
  auto-run.

### 9.3 Ephemeral artifacts

Working drafts are flagged `ephemeral=1`. They remain cached after the meeting
(the only surviving copy), are included in the timeline and export, and can be
filtered out of "official only" views.

### 9.4 Finalize and archive

`Finalize`:

- recomputes final states from the last HTML,
- writes the whole-meeting Markdown export,
- sets `meeting_meta.finalized=1` (a flag, not a hard lock; annotation stays allowed),
- optionally materializes `cache/mirror/`.

Multi-meeting: open any meeting folder; no cross-meeting DB. A recent-folders list
stores paths only.

---

## 10. Sync engine

### 10.1 Scheduling

- One background worker starts with the server when `poll.auto_sync` is true and
  runs immediately; manual "Sync Now" serializes behind it through the same lock.
  Saving settings can start, stop, or reschedule the worker without a restart.
- Adaptive interval: `meeting_interval_s` inside configured meeting days/hours
  (timezone-aware), otherwise `idle_interval_s`.
- Jitter ±`jitter`; source failures back off exponentially up to `backoff_max_s`.
- Per-source health, last attempt, last success, next due.
- Mail poll independent (`mail_interval_s`), incremental.

### 10.2 One endpoint, no failover

Exactly one endpoint is active. If it fails:

- exponential backoff with jitter, capped at `backoff_max_s`,
- serve last-known data with an explicit stale badge,
- surface a prominent "source unreachable" state and a one-click **edit/switch
  endpoint** action (which writes a single new source object),
- never silently switch or mix manifests.

Provenance is recorded per artifact, so the UI can always say which endpoint a file
came from.

### 10.3 Failure classes

| Failure | Behavior |
|---|---|
| DNS/connect/timeout | backoff; stale badge; keep state |
| auth failure | stop retrying fast; surface credential error (redacted) |
| listing parse failure | keep previous manifest; log raw sample; retry |
| single file fetch failure | mark that artifact failed; continue cycle |
| HTML parse failure | keep previous projection; surface `agenda stale` |
| mail parse failure | skip message; log; continue |

### 10.4 Refresh visibility

A persistent sync chip shows: endpoint, current interval, last sync, next countdown,
health, and per-folder freshness (Drafts, Inbox, Agenda, Mail). This directly
satisfies the "make refresh speed visible" requirement.

---

## 11. API (local, loopback only)

Read:
- `GET /api/meeting`
- `GET /api/tdocs?agenda=&type=&release=&wi=&source=&state=&tracked=`
- `GET /api/tdocs/{tdoc}`
- `GET /api/drafts/{artifact_id}`
- `GET /api/tdocs/{tdoc}/timeline`
- `GET /api/lineage?tracked=true&include_drafts=true`
- `GET /api/lineage-views` (saved names, filters, active view)
- `GET /api/artifacts/{id}` (stream)
- `GET /api/mail?tdoc=&agenda=&q=`
- `GET /api/discovery`
- `GET /api/notifications?limit=100`
- `GET /api/log?limit=100`
- `GET /api/conflicts`
- `GET /api/sync/status`
- `GET /api/export/markdown?include_mail=false`
- `GET /api/events` (SSE; sync/graph/conflict events)

Write:
- `POST /api/tdocs/{tdoc}/track` / `DELETE`
- `POST /api/assertions` (manual link), `PATCH /api/assertions/{id}` (activate/mute)
- `POST /api/conflicts/{id}/resolve`
- `POST /api/notes`, `PATCH /api/notes/{id}`, `DELETE /api/notes/{id}`
- `PUT /api/status` (separate TDoc or draft node status; `null` clears)
- `PUT /api/hidden` (hide/show a TDoc or draft lineage node)
- `POST /api/artifacts/{id}/open`
- `POST /api/sync`
- `POST /api/tdocs/{tdoc}/fetch?lineage=true` (download deferred artifacts)
- `GET|PUT /api/settings` (source, mail source, lazy drafts, auto sync and poll
  intervals, UI bar color; password write-only)
- `PUT /api/lineage-views` (persist tab names, filters, and active view)
- `POST /api/import/excel?filename=...&force=true` (raw workbook body)
- `POST /api/finalize`

All responses are typed Pydantic models; OpenAPI is generated automatically (the
future AI contract).

---

## 12. UI / UX

Three-pane desktop layout, responsive enough for a narrow window.

- **Top bar:** meeting selector, Sync Now, sync chip (interval/last/next/health),
  Settings panel (FTP source, mail source, automatic updates and intervals,
  lazy drafts, meeting-bar color, workbook upload), and an **Enable alerts**
  control for browser notifications. The bar color defaults to `#ffffff` and fades
  from left to right into white.
- **Left rail:** compact tracked-favourites list only; a per-row tracking star and
  unread draft/file/merge/revision/link/status markers; double-click centers the
  node in Lineage.
- **Center:** lineage view (default during meeting) with inline filters (agenda,
  type, state, source, tracked only, **Include Drafts**, **Hide withdrawn**,
  **Hide not treated**, **Hide unknown**, **Show hidden**) or a sortable table
  (default for prep). Tabs:
  **Lineage**, **Timeline**, **Conflicts**, **Notifications**, **Log**. The **+**
  control creates additional, independent lineage tabs; each tab keeps its own
  filter selection, can be renamed through its pencil control or by double-clicking
  its label, and can be closed (except the last one). The source filter splits the
  comma-separated source field into individual companies, so a TDoc can be matched
  by any one of its contributing companies. Tab names, filters, and the active
  lineage view are persisted in `meeting.json` (`ui.lineage_views` and
  `ui.active_lineage_view`), so reloading the app or moving the meeting folder
  restores the same views. Draft
  visibility filters only the graph; the detail panel still shows all artifacts
  for the selected node.
- **Right panel:** detail — metadata, provenance, raw HTML row, artifacts, emails,
  separate node **Action** (`Support` / `Object` / `Clarify` / **No action**), node
  **Visibility** (**Hide** / **Show**), free-text notes, conflict actions. Actions
  and notes are available on TDoc and draft nodes.

### 12.1 Lineage renderer

Custom SVG lane renderer, not a graph library:

- lanes are lineage paths (git-log style); nodes are TDocs, with optional working
  drafts behind the **Include Drafts** filter, ordered by upload time and chained
  ahead of the TDoc's official revision; clicking a draft opens its own detail
  panel with artifact metadata, status, and draft-specific notes; artifacts discovered
  during the session highlight their draft node (or parent TDoc when no draft
  node exists) and can raise a browser desktop notification;
- every lineage tab renders from the same loaded graph but applies its own filter
  set independently, so switching tabs never changes another tab's view;
- `revision_of` = straight continuation; `merged_into` = curved convergence whose
  lane follows the baseline/revised predecessor rather than the first incoming
  list entry; `has_draft` = dotted child edge; `based_on` = dashed weak/inferred
  link;
- ghost hints = dotted/dashed, inactive; muted branch = greyed/dashed;
- **Hide unknown** omits non-HTML nodes with no edge path to an HTML-sourced node;
- explicitly hidden nodes are omitted unless **Show hidden** is checked, and then
  render with a subdued/manually-hidden style;
- state bubble colors: approved/agreed/replied-to green, merged/revised light
  green-grey, noted/postponed yellow, not treated/reserved grey,
  withdrawn/rejected red;
- tracked TDocs carry only a star, not an extra outline; a post-it badge shows the latest note type (plain
  note, red `×` Object, green `✓` Support, blue `?` Clarify); node backgrounds
  use matching very light tints; `Avail`, `Treated`, provisional/unconfirmed, and
  conflict badges remain separate;
- expand/collapse per tracked set; click-drag on the background pans in all
  directions with inertia (a click or mouse wheel stops the fling immediately);
  scrollbars keep their native behavior; nodes remain clickable;
  zoom controls; double-clicking a TDoc in the left list centers the graph on its
  node; double-clicking a lineage node toggles tracking; keyboard navigation;
- timeline pane synchronized by selection.

### 12.2 Timeline

Per TDoc, chronological events: initial artifact, working drafts (with revision),
emails, Inbox ZIP, state notes, user notes, state transitions. Ephemeral events are
visually distinct.

### 12.3 Interaction rules

- Adding a tracked TDoc is instant and local; tracking expands to every existing
  TDoc in the active lineage component, while untracking removes only the selected
  node. New files, decisions, and newly connected nodes surface in Notifications
  using the tracked timestamp; each TDoc link shows its document title (artifact
  filename for drafts). Unread entries are lightly highlighted; hovering or
  clicking one marks it seen and lowers the tab count while keeping the history
  visible, and opening a related TDoc or draft marks its entries seen. Tracking
  changes and note actions are recorded in `user_action` and shown in the Log tab.
- Each TDoc detail links its official ZIP using the fixed
  `Docs/<tdoc-nr>.zip` path; working draft details do not carry these links.
- Manual link creation: **revised to** / "merged into" / "merged from", using the
  fixed meeting prefix plus a four-digit suffix, with source badges and an explicit
  "unverified" state.
- Conflict resolution: accept HTML, keep mine, or repair; the losing branch is
  muted, never deleted.
- Everything is keyboard-reachable; no modal traps for routine work.

---

## 13. Markdown export

One file per export: `exports/mirko-<meeting>-<timestamp>.md`, covering the **whole
meeting** (not a JSON sidecar in v1).

Contents:

1. Header: meeting, generated-at, endpoint, freshness, counts.
2. Summary table: TDoc, agenda, type, state, source, notes count, tracked.
3. Per tracked TDoc: metadata, state, lineage (`revision_of` / `merged_into`),
   full event timeline, status, notes, optional mails.
4. A Mermaid `graph LR` lineage diagram.
5. Muted/inactive branches listed and marked; never omitted silently.
6. Ephemeral artifacts marked as such.

`include_mail` is a toggle. Export is deterministic for a given DB state (stable
ordering) so it can be snapshot-tested.

---

## 14. Performance and reliability targets

- Dataset scale: < 10k TDoc rows, < 1k artifacts, < 10k mails per meeting.
- UI interactions: < 100 ms for selection, filtering, pane switches; no full graph
  relayout on selection.
- Sync: incremental manifest diff; no full mirror; one fetch per changed remote
  identity.
- Startup: < 2 s with a warm cache; DB integrity check on open.
- Crash safety: WAL + transactional ingestion; partial cycles are resumable.
- Offline: all previously fetched data remains usable; stale badges everywhere.

---

## 15. Testing and verification

Test seams:

- `FtpClient` protocol with `LftpFtpClient` and `FakeFtpClient`.
- Pure parser functions with no I/O.
- Temp meeting folders for integration tests.
- `DocumentTextProvider` seam reserved for future AI (not implemented).

Test layers:

1. **Unit / golden:** normalization; TDoc canonicalization; filename parser tiers on
   the real 50-name corpus; subject parser on the provided examples; HTML parser on a
   saved raw `.htm` (rowspan, U+2011, NBSP, `Treated` notes, merge derivation);
   Excel parser.
2. **Property-based:** `hypothesis` fuzzing filenames/subjects for no-crash and
   idempotence.
3. **Integration:** fake FTP → sync → cache → projections; single-download invariants;
   conflict/branch resolution; idempotent re-ingestion.
4. **Migration:** apply all migrations to an empty DB and to a seeded prior version.
5. **API:** endpoint contracts and filter semantics.
6. **E2E:** Playwright smoke for three-pane navigation, selection sync, and conflict
   resolution.
7. **Export:** golden snapshot of the Markdown output.
8. **`lftp`:** gated integration test against a local test FTP server when `lftp` is
   present.

Fixtures to seed the repo with redacted real data:

- the 50-filename corpus extracted from the live `Drafts/` listing,
- the subject examples you provided,
- one saved raw `AgendaWithTdocAllocation_*.htm`,
- the pre-meeting Excel,
- a small `mbox` with representative messages.

Already implemented in this repo: the agenda HTML parser
(`mirko/ingest/agenda_html.py`), a hand-built excerpt fixture and a saved real
snapshot regression test (`tests/test_agenda_html.py`, `tests/fixtures/`). It
runs with the stdlib: `python -m unittest discover -s tests -v`.

---

## 16. Extensibility (AI and beyond)

AI is deferred, but the seams are kept:

- **Read contract:** OpenAPI endpoints already expose TDocs, artifacts, timeline,
  assertions, and notes.
- **Text seam:** a `DocumentTextProvider` interface can extract text from
  `.docx`/`.zip`/PDF for diffing later; not implemented in v1.
- **Annotation provenance:** `note.source` already allows `user | import | ai`;
  AI results will never overwrite user notes and will be visually distinct.
- **Export:** the Markdown export is the human/agent context packet; a JSON sidecar
  can be added later without schema change.
- No LLM endpoint, credentials, or network call is part of v1.

---

## 17. Security and privacy

- Server binds to `127.0.0.1` only; no remote access.
- FTP credentials in `meeting.json` (`0600`) or env indirection; redacted from logs,
  errors, exports, and the UI.
- Remote filenames are untrusted: no shell, strict argument passing, reject control
  characters and traversal.
- HTML parsed without script execution; Excel read without macros; ZIPs are not
  auto-extracted.
- Auto-open restricted to document types; shortcut/executable types require
  confirmation.
- No telemetry, no outbound calls other than the configured FTP endpoint.

---

## 18. Implementation milestones

| Milestone | Deliverable |
|---|---|
| M0 | Meeting folder, config validation, migrations, FastAPI skeleton, Nix flake/preflight |
| M1 | `FtpClient` + `LftpFtpClient`, manifest diff, blob cache, single-download invariants |
| M2 | HTML ingestion, state/type maps, merge derivation, projections |
| M3 | Filename parser + draft/Inbox artifacts + provisional/new-number discovery |
| M4 | Mail ingestion, subject parser, threading, mentions/discovery |
| M5 | React shell, three-pane layout, lineage renderer, timeline, filters |
| M6 | Notes/annotations, manual assertions, conflicts/branches, discovery UI |
| M7 | Markdown export, finalize/archive, E2E tests, docs |

---

## 19. Risks and open items

1. ~~Raw HTML not yet captured.~~ **Resolved.** A raw snapshot is parsed and
   regression-tested by `mirko/ingest/agenda_html.py` and
   `tests/test_agenda_html.py` (900 rows, 51 treated notes, 442 lineage edges,
   3 flagged data anomalies). The file uses empty continuation cells, not
   `rowspan`; TDoc hyphens arrive as `&#x2011;`, and `Treated` notes live in
   `span.tooltiptext`.
2. **`lftp` absent on this machine.** Add it to the Nix dev shell and block startup
   with a clear preflight message.
3. **HTTPS via `lftp`** may need certificate/SSL settings; test against the public
   sync endpoint.
4. **U+FFFD** in source is irreversible encoding loss; preserve, do not repair.
5. **Ambiguous merge baseline** (missing `Replaces`) becomes a conflict, never a guess.
6. **`Decision=open` is absent in the real file**; empty is mapped to `open` with
   `state_source=inferred`.
7. **Excel schema drifts between meetings**; the alias table is validated against
   `TDoc_List_Meeting_SA3#130.xlsx` and remains tolerant of new columns.
8. **Filename false positives** are inevitable; hints are ghost edges and always
   user-confirmable.
9. **`.lnk` / `.zip` in `Drafts/`** need explicit non-auto-open handling.
10. **Long-running discussions** (15+ drafts) are still tiny for the UI; no
    virtualization needed, but keep rendering O(n).

---

## Appendix A — Real filename corpus (fixtures)

```
drafft_S3-264314-r1.docx
Draft LS reply on resolving ENs in TS 23.280 (S3-264202 S6- 263386).docx
draft S3-263908-r1.docx
draft S3-263909_r1.docx
draft S3-264313-r2_New_NTN_Security_SID.docx
draft S3-264313r1-New_NTN_Security_SID.docx
draft S3-264405 was S3-263711 Reply LS on 6G user plane security r2.docx
draft S3-264454-r1 merger of S3-263847.docx
draft S3-264458 was 4313-New_NTN_Security_SID.docx
draft S3-264489_r1_was S3-263739.docx
draft S3-264558-r2_merge of  S3-264138 and S3-263951.docx
draft S3-264576_r3 was 3803_A#8 - KI#8.2 - update KI on UE AI agent authorization.docx
draft S3-264587-r1_was_S3-263953 A#4 – KI#4.2-solution#4.2.1-Addresing EN for solution#4.2.1.docx
draft-S3-260522_was_S3-264080-r1_PCR_33.801-01_AnnexD_Broadcast_Message_Catalogue.docx
draft-S3-263561-was-263713 A#4-KI#4.8-Update KI on user plane security.docx
draft-S3-263768r1.docx
draft-S3-263846-r1-merger of S3-264123, S3-264167_A#6-KI#6.4-Sol#NEW- Authorization of API invoker for intent based exposure.docx
draft-S3-264163-r1-merger_of_S3-263756_S3-263845_S3-264163.docx
draft-S3-264279_CR-TS33117_ICMPv6_threat-refs_abbreviations-r1.docx
draft-S3-264428_r1 was 4272_update key hierarchy and Kaiotf derivation.docx
draft-S3-264471-r1_revision of S3-263849.docx
draft-S3-264497_r1 was 3853_A#3 - KI#3.1 - Sol#3.1.1 - Update Solution for Option2 Dual NAS Security Terminations.docx
draft-S3-264531-r6-merger_of_S3-264381_S3-264254_S3-264359.docx
draft-S3-264549-r1_revision of 3846_merger of 4123, 4167_A#6-KI#6.4-Sol#NEW- Authorization of API invoker for intent based exposure.docx
draft-S3-264561-was-263713 A#4-KI#4.8-Update KI on user plane security r3..docx
draft_S3-263502-r1 - A#2-MAC-CE Security assumptions.docx
draft_S3-263703-v5-DetailedAgenda.docx
draft_S3-263738-r1_A7 – KINEW – Key Issue on security relevant data on access to subscriber data_merged.docx
draft_S3-263832-r3 .docx
Draft_S3-263861r1 A#3 - KI#3.1– Sol 6.3.1.docx
draft_S3-263942-r1 - merged Solution #3.3.2.doc
draft_S3-263952-r1_merger of S3-263952 and S3-264066 A#4 – KI#4.1-solution#4.1.1- Addresing EN for solution#4.1.1.docx
draft_S3-264002r2 merger of 4002 4181 and 3776.docx
draft_S3-264089-r1 merging S3-2604090 Sol #New-Authorization for UE producer and UE consumer in Data Framework.docx
draft_S3-264234_r1_A#7 – KI#NEW_security monitoring .docx
draft_S3-264253-r1-merger of 4253-4276-4370-4356-4381-Standalone PQC scheme for SUCI calculation.docx
draft_S3-264303-merger of S3-264303, 4315 and 4390-r1.docx
draft_S3-264408-r1-merger of S3-263836_S3-263837_S3-263860_S3-263980_S3-264158_S3-264225.docx
draft_S3-264413_was_264243_merge_of_264019_264317_CR_33502_Criticality.docx
draft_S3-264414r1 was merger of S3-264020 and S3-264242.docx
draft_S3-264452-r4 was 3799 - A#9 - KI#9.1 - Sol#NEW - Unified Data Level Authorization for Data Framework.docx.lnk
draft_S3-264467r1_33704-050rm.docx
draft_S3-264490-r1_was__S3-264399-Comments to S3-263739.docx
draft_S3-264507-r16 A#10 - KI#NEW - Security aspects for sensing service operation.docx
draft_S3-264509_r1 was_S3-264091-mergering S3-264188, S3-263892.docx
draft_S3-264519-r1_merger_of_S3-263764_S3263763_S3263932_S3264129.docx
draft_S3-264528-r1_merger of 4133+3725 - A#3 - KI#3.4 - Sol#3.4.2 - Add a new Variant.docx
draft_S3-264547-r1_ LS on Do-A capable AIoT Device Context Invalidity.docx
draft_S3-264550 -r1 TR 33801-01-060-Edit corrections.docx
draft_S3-264580_r2_ KI#9.2 Interim agreement of Authentication (mergingS3-264084, S3-263794).docx
draft_S3-26abcd-r3 was S3-263733_A#8 - KI#8.1 - Sol#New - Use of AKMA for UE AI applications agents.docx
Draft_MeetingReport-day1.rtf
Meeting notes for Monday lunch session (5.1.10).docx
Moderator 5.3.1.3.1 Area#3 Solutions Status_v1.docx
S3-263915.zip
S3-263987-r1.docx
S3-264418-r3 was S3-264244 [33.180] Recording and Logging reference points.docx
SP-260918_2026-09-07_5G-ACIA-LS_2026-002.docx
```

## Appendix B — Real HTML column values

`Decision`: `merged, revised, noted, approved, not treated, withdrawn, agreed, not pursued, email approval, replied to, postponed, endorsed` (+ empty/agenda rows)

`For`: `Approval, Agreement, Discussion, Endorsement, Decision, Information, -, approval`

`Type`: `pCR, other, CR, discussion, LS out, draftCR, LS in, SID new, draft TR, report, WID new, draft TS, agenda, SID revised`

`Treated` note example:
`YesHuawei, ORANGE, CMCC didn't agree with this LS.`
