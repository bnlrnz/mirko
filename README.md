# Mirko

Mirko is a local-first 3GPP SA3 contribution tracker. One folder holds one meeting
and is the complete portable state: configuration, SQLite database (append-only
observations plus derived projections), content-addressed blob cache, and Markdown
exports. Nothing is stored with absolute paths, so moving the folder moves everything.

The authoritative design is [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md); the glossary is in
[`GLOSSARY.md`](GLOSSARY.md).

## Layout

```
<meeting-dir>/
  meeting.json           # meeting + single source endpoint + mail + poll settings
  mirko.sqlite           # observations, assertions, notes, conflicts, projections
  cache/blobs/<sha256>   # authoritative artifact storage (single-download)
  cache/mirror/...       # optional relative symlink view for external browsing
  exports/               # whole-meeting Markdown exports
  imports/               # workbooks uploaded through the UI
  logs/
```

## Backend

Python 3.14, FastAPI, SQLite. The sync worker runs serially: remote manifest diff →
`lftp` fetch → blob cache → Excel/HTML/filename/mail ingestion → assertions and
conflicts. Working drafts are deferred by default: only filenames are listed until a
TDoc is opened or tracked, then its artifacts (and lineage neighbours on track) are
downloaded on demand. Agenda HTML and Inbox mail remain eager.

- `mirko/config.py`, `meeting_folder.py` — validated config and folder layout.
- `mirko/migrations/` — schema plus `edge_current` / `tdoc_current` views.
- `mirko/ingest/agenda_html.py`, `agenda_ingest.py` — agenda parsing, lineage/state
  assertions, conflict detection, projections.
- `mirko/ingest/excel_ingest.py` — pre-meeting allocation workbook (openpyxl) that
  seeds TDocs ahead of the HTML agenda; fills gaps only, never overwrites HTML.
- `mirko/ingest/filename.py`, `filename_ingest.py` — filename parser, ephemeral draft
  artifacts, provisional numbers and ghost hints.
- `mirko/ingest/mail_subject.py`, `mail_ingest.py` — RFC2047 subjects/threading and
  mentions from mbox or `.eml` trees.
- `mirko/worker.py` — one sync + ingestion cycle with sync-state health.
- `mirko/repository.py`, `api.py` — read models and typed JSON API under `/api`.
- `mirko/export.py` — deterministic Markdown export, finalize/archive, mirror.

### Development

```sh
nix develop                       # python 3.14, pytest, node 22, playwright browsers
nix develop -c pytest -q          # backend tests
nix develop -c python -m mirko <meeting-dir>   # serve API + built frontend
nix develop -c python -m mirko <meeting-dir> \
  --import-excel ~/Downloads/TDoc_List_Meeting_SA3#130.xlsx  # seed TDocs early
```

`run_server` requires `lftp` and serves `frontend/dist` when it exists.
`--import-excel` ingests the workbook, prints the row/edge counts, and exits;
refresh the UI afterwards. It is safe to run while the server is idle.

The **Settings** panel in the web UI can edit the FTP source, toggle lazy draft
fetching, and upload the allocation workbook for immediate (forced) parsing. Saves are
written atomically to `meeting.json` with mode `0600`; credentials are never returned
by the API.

## Frontend

React + TypeScript + Vite. Three panes: tracked TDocs/filters, a center view
(Lineage, Timeline, Conflicts, Notifications, Log), and a detail panel with
metadata, artifacts, mail, notes, assertions, manual links, and conflict actions.
Each left-rail TDoc has a tracking star; double-clicking a lineage node toggles
tracking too. Tracking a TDoc expands to its connected lineage component; the
Notifications tab lists new files, decisions, and newly connected nodes for that
tracked set. The Log tab shows persisted tracking and note actions. The Lineage
graph can show cached working drafts as child nodes via the **Include Drafts**
filter, renders a post-it badge for the latest note type, and infers LS-in → LS-out
reply links from matching titles (unverified `based_on` edges). Deferred artifacts
show as `not fetched` with a fetch button and their FTP upload timestamp; selecting a
TDoc or tracking it triggers the download automatically.

```sh
cd frontend
npm install
npm test              # Vitest + Testing Library
npm run build         # tsc --noEmit && vite build
nix develop .. -c npm run e2e   # Playwright smoke (browser provided by the flake)
```

## API surface

Read: `/api/meeting`, `/api/health`, `/api/tdocs` (+ filters), `/api/tdocs/{tdoc}`,
`/api/tdocs/{tdoc}/timeline`, `/api/lineage`, `/api/mail`, `/api/discovery`,
`/api/conflicts`, `/api/log`, `/api/sync/status`, `/api/export/markdown`,
`/api/events` (SSE).

Write: `POST /api/sync`, `POST /api/tdocs/{tdoc}/fetch`,
`POST|DELETE /api/tdocs/{tdoc}/track`, `POST /api/assertions`,
`PATCH /api/assertions/{id}`, `POST /api/conflicts/{id}/resolve`, `POST /api/notes`,
`PATCH|DELETE /api/notes/{id}`, `GET|PUT /api/settings`, `POST /api/import/excel`,
`POST /api/finalize`.

## Methodology

Ingestion is append-only. HTML never silently deletes user intent: disagreement opens
a conflict (`accept_html` / `keep_mine` / `repair`), and the losing branch is muted,
never deleted. Filename and email links are ghost hints until promoted. Exports are
deterministic for a given database state.
