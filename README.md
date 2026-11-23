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
downloaded on demand. Agenda HTML and Inbox mail remain eager. Listings skip
per-file `MDTM` so large folders stay fast; tracked artifacts get an exact UTC
timestamp from one batched `MDTM` pass.

- `mirko/config.py`, `meeting_folder.py` — validated config and folder layout.
- `mirko/migrations/` — schema plus `edge_current` / `tdoc_current` views.
- `mirko/ingest/agenda_html.py`, `agenda_ingest.py` — agenda parsing, lineage/state
  assertions, conflict detection, projections.
- `mirko/ingest/excel_ingest.py` — pre-meeting allocation workbook (openpyxl) that
  seeds TDocs ahead of the HTML agenda; fills gaps only, never overwrites HTML.
- `mirko/ingest/filename.py`, `filename_ingest.py` — filename parser, ephemeral draft
  artifacts, provisional numbers and ghost hints.
- `mirko/ingest/mail_subject.py`, `mail_ingest.py` — RFC2047 subjects/threading and
  mentions from mbox files, recursive mbox directories (including Thunderbird
  `.sbd` subfolders), a single `.eml` file, or `.eml` trees. Only mail tagged for
  the configured meeting (such as `[SA3#131]`) is ingested; mail for other
  meetings or without a meeting tag is skipped and pruned.
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
lazy draft fetching, choose the meeting-bar color (fading right into white), and
upload the allocation workbook for immediate (forced) parsing. An mbox source may
be a single file or a directory; Thunderbird folder files also include their
sibling `.sbd` subfolders, and `.msf` indexes are skipped. Saves are written
atomically to
`meeting.json` with mode `0600`; credentials are never returned by the API.

## Frontend

React + TypeScript + Vite. Three panes: a compact tracked-favourites rail, a
center view (Lineage, Conflicts, Notifications, Log), and a detail panel
with metadata, artifacts, mail, notes, assertions, manual links, and conflict
actions. The rail lists only tracked TDocs, each with a star and an unread marker
for draft, file, merge, revision, link, or status updates; double-clicking a
favourite centers its lineage node. Tracking a TDoc expands to its connected
lineage component. The Notifications tab lists new files, decisions, and newly
connected nodes for that tracked set, with the document title beside each TDoc
link. Unread entries are lightly highlighted; hovering or clicking an entry marks
it seen and lowers the tab count without removing it. Seen state is stored in the
meeting database, so it survives reloads and restarts. The Log tab shows persisted
tracking and note actions.

Filters (agenda, type, state, source, tracked only, **Include Drafts**, **Hide
withdrawn**, **Hide not treated**, **Hide unknown**, and **Show hidden**) live in
the Lineage toolbar. Agenda, type, state, and source are checkbox lists: selecting
several values matches any of them, while selections in different lists are
combined. Agenda options follow the meeting's section numbering (`5.1.2` before
`5.1.10`) and show the agenda topic beside the number. The source list splits the
agenda's comma-separated source field into individual company names, so a TDoc
submitted by `Huawei, HiSilicon` matches both `Huawei` and `HiSilicon`. The **+**
control creates additional lineage tabs, each with its own independent filter set,
so different views (for example one
agenda item and one tracked-only view) can be kept side by side. Double-click a tab
label or use its pencil control to rename it; close extra tabs with the × control.
Tab names, filters, and the active lineage view are stored in `meeting.json` under
`ui.lineage_views` and `ui.active_lineage_view`, so reloading the page or moving the
meeting folder to another machine restores the same views.
Unknown nodes are non-HTML nodes with no path to an HTML node.
Draft visibility only affects the graph, never the selected node's detail panel.
**Hide** / **Show** under **Visibility** in the detail panel suppresses or restores
a TDoc or draft in lineage without deleting it; **Show hidden** reveals explicitly
hidden nodes. The graph can show cached working drafts as child nodes and
infers LS-in → LS-out reply links from matching titles (unverified `based_on`
edges). Emails linked to a TDoc on a visible edge appear as envelope markers in
timeline order; several mails on one edge collapse into a bulk envelope that
expands to individual messages. With drafts shown, mails are spread across the
draft segments that match their timestamps; hiding drafts collects them back
onto the TDoc edge. Hovering a marker previews the subject and sender, clicking a
message opens the same mail-body dialog used in the detail panel, and clicking
anywhere else collapses an expanded bundle. TDoc and draft nodes share
independent action and note features: a
`Support` / `Object` / `Clarify` action takes visual precedence, while notes alone
show a post-it badge and light yellow tint. Manual links are entered as a four-digit
suffix after the meeting prefix and use **revised to**. Merged nodes derive their
lane from the baseline/revised document rather than the first incoming list entry.
Their detail panel lists every contributing predecessor under **Merger of**, with
links to open each source TDoc.
Clicking a draft opens a draft detail panel with its artifact metadata, action, and
notes. Each TDoc detail links its official ZIP at `Docs/<tdoc-nr>.zip`.
The Conflicts tab shows the competing lineage nodes side by side, with each
assertion's source and confidence; clicking a node opens it in the detail panel.
Newly arrived files glow in the lineage graph; **Enable alerts** requests browser
notification permission and raises a desktop notification for each new document.
Deferred artifacts show as `not fetched` with a fetch button and their FTP upload
timestamp; selecting a TDoc or tracking it triggers the download automatically.
Tracking paints the new tracked flags immediately and downloads deferred files in
the background, so a slow FTP fetch never blocks the graph. While that happens the
lineage toolbar shows **Updating lineage…** and **Fetching files…**, and nodes or
edges changed by the update flash briefly so the new part of the graph is easy to
spot.

```sh
cd frontend
npm install
npm test              # Vitest + Testing Library
npm run build         # tsc --noEmit && vite build
nix develop .. -c npm run e2e   # Playwright smoke (browser provided by the flake)
```

## Export

**Export** (`GET /api/export/markdown`) is a read-only snapshot of the current
database state as Markdown, streamed as a download. It writes nothing and can be
repeated at any time. The **Export** button in the top bar opens an options menu:

- **Scope** — tracked TDocs only (default) or all TDocs.
- **Agenda item** — restrict the export to one agenda section.
- **Include** — lineage graph, timeline, artifacts, notes, meeting notes, and
  state are on by default; mail is off by default.

The same settings are available as query parameters: `tracked_only`,
`agenda_item`, `include_lineage`, `include_timeline`, `include_artifacts`,
`include_notes`, `include_meeting_notes`, `include_state`, and `include_mail`.
The summary table always covers every TDoc in scope; detailed sections are only
emitted for TDocs that have notes, a meeting note, or linked mail when mail is
included.

**Finalize** (`POST /api/finalize`) is the end-of-meeting workflow and has no UI
button: it re-ingests the latest agenda, writes a whole-meeting timestamped file
under `exports/`, materializes `cache/mirror/`, and records `finalized`,
`finalized_at`, and `export_path` in `meeting_meta`. It is a flag, not a lock:
syncing, annotation, and re-finalizing remain allowed.

## API surface

Read: `/api/meeting`, `/api/health`, `/api/tdocs` (+ filters), `/api/tdocs/{tdoc}`,
`/api/drafts/{artifact_id}`, `/api/tdocs/{tdoc}/timeline`, `/api/lineage`,
`/api/lineage-views`, `/api/mail`, `/api/mail/{email_id}`, `/api/discovery`,
`/api/conflicts`, `/api/log`,
`/api/sync/status`, `/api/export/markdown`, `/api/events` (SSE).

Write: `POST /api/sync`, `POST /api/tdocs/{tdoc}/fetch`,
`POST|DELETE /api/tdocs/{tdoc}/track`, `POST /api/assertions`,
`PATCH /api/assertions/{id}`, `POST /api/conflicts/{id}/resolve`, `POST /api/notes`,
`PATCH|DELETE /api/notes/{id}`, `PUT /api/status`, `PUT /api/hidden`,
`GET|PUT /api/settings`, `GET|PUT /api/lineage-views`, `POST /api/import/excel`,
`POST /api/finalize`.

## Methodology

Ingestion is append-only. HTML never silently deletes user intent: disagreement opens
a conflict (`accept_html` / `keep_mine` / `repair`), and the losing branch is muted,
never deleted. Filename and email links are ghost hints until promoted. Exports are
deterministic for a given database state.
