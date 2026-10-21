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

Python 3.14, FastAPI, SQLite. The server starts one background poller; the sync
worker runs serially: remote manifest diff → `lftp` fetch → blob cache →
Excel/HTML/filename/mail ingestion → assertions and conflicts. It polls immediately
on startup, then adapts between meeting and idle intervals with jitter and backoff.
The UI refreshes sync status every five seconds and reloads data after a new attempt. Working drafts are deferred by default: only filenames are listed until a
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
  mentions from mbox, a single `.eml` file, or `.eml` trees.
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

The **Settings** panel in the web UI can edit the FTP and mail sources, enable or
disable automatic FTP updates, set the meeting and idle update intervals, toggle
lazy draft fetching, choose the meeting-bar color, and upload the allocation
workbook for immediate (forced) parsing. Saves are written atomically to
`meeting.json` with mode `0600`; credentials are never returned by the API.

## Frontend

React + TypeScript + Vite. Three panes: a compact tracked-favourites rail, a
center view (Lineage, Timeline, Conflicts, Notifications, Log), and a detail panel
with metadata, artifacts, mail, notes, assertions, manual links, and conflict
actions. The rail lists only tracked TDocs, each with a star and an unread marker
for draft, file, merge, revision, link, or status updates; double-clicking a
favourite centers its lineage node. Tracking a TDoc expands to its connected
lineage component. The Notifications tab lists new files, decisions, and newly
connected nodes for that tracked set, with the document title beside each TDoc
link. Unread entries are lightly highlighted; hovering or clicking an entry marks
it seen and lowers the tab count without removing it. The Log tab shows persisted
tracking and note actions.

Filters (agenda, type, state, source, tracked only, **Include Drafts**, **Hide
withdrawn**, **Hide not treated**, **Hide unknown**, and **Show hidden**) live in
the Lineage toolbar. Unknown nodes are non-HTML nodes with no path to an HTML node.
Draft visibility only affects the graph, never the selected node's detail panel.
**Hide** / **Show** under **Visibility** in the detail panel suppresses or restores
a TDoc or draft in lineage without deleting it; **Show hidden** reveals explicitly
hidden nodes. The graph can show cached working drafts as child nodes and
infers LS-in → LS-out reply links from matching titles (unverified `based_on`
edges). TDoc and draft nodes share independent action and note features: a
`Support` / `Object` / `Clarify` action takes visual precedence, while notes alone
show a post-it badge and light yellow tint. Manual links are entered as a four-digit
suffix after the meeting prefix and use **revised to**. Merged nodes derive their
lane from the baseline/revised document rather than the first incoming list entry.
Clicking a draft opens a draft detail panel with its artifact metadata, action, and
notes. Each TDoc detail links its official ZIP at `Docs/<tdoc-nr>.zip`.
The Conflicts tab shows the competing lineage nodes side by side, with each
assertion's source and confidence; clicking a node opens it in the detail panel.
Newly arrived files glow in the lineage graph; **Enable alerts** requests browser
notification permission and raises a desktop notification for each new document.
Deferred artifacts show as `not fetched` with a fetch button and their FTP upload
timestamp; selecting a TDoc or tracking it triggers the download automatically.

```sh
cd frontend
npm install
npm test              # Vitest + Testing Library
npm run build         # tsc --noEmit && vite build
nix develop .. -c npm run e2e   # Playwright smoke (browser provided by the flake)
```

## API surface

Read: `/api/meeting`, `/api/health`, `/api/tdocs` (+ filters), `/api/tdocs/{tdoc}`,
`/api/drafts/{artifact_id}`, `/api/tdocs/{tdoc}/timeline`, `/api/lineage`,
`/api/mail`, `/api/discovery`, `/api/conflicts`, `/api/log`, `/api/sync/status`,
`/api/export/markdown`, `/api/events` (SSE).

Write: `POST /api/sync`, `POST /api/tdocs/{tdoc}/fetch`,
`POST|DELETE /api/tdocs/{tdoc}/track`, `POST /api/assertions`,
`PATCH /api/assertions/{id}`, `POST /api/conflicts/{id}/resolve`, `POST /api/notes`,
`PATCH|DELETE /api/notes/{id}`, `PUT /api/status`, `PUT /api/hidden`,
`GET|PUT /api/settings`, `POST /api/import/excel`, `POST /api/finalize`.

## Methodology

Ingestion is append-only. HTML never silently deletes user intent: disagreement opens
a conflict (`accept_html` / `keep_mine` / `repair`), and the losing branch is muted,
never deleted. Filename and email links are ghost hints until promoted. Exports are
deterministic for a given database state.
