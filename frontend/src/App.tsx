import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { CenterPane, type CenterTab } from "./components/CenterPane";
import { DetailPanel } from "./components/DetailPanel";
import { LeftRail } from "./components/LeftRail";
import { TopBar } from "./components/TopBar";
import type {
  Conflict,
  ConflictResolution,
  DiscoveryItem,
  Filters,
  Lineage,
  Meeting,
  SyncStatus,
  TdocDetail,
  TdocSummary,
  TimelineEvent,
} from "./types";

const EMPTY_FILTERS: Filters = {
  agenda: "",
  type: "",
  state: "",
  source: "",
  tracked: false,
  includeEphemeral: true,
  search: "",
};

export default function App() {
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [tdocs, setTdocs] = useState<TdocSummary[]>([]);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TdocDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [lineage, setLineage] = useState<Lineage>({ nodes: [], edges: [] });
  const [discovery, setDiscovery] = useState<DiscoveryItem[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [tab, setTab] = useState<CenterTab>("lineage");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exportPath, setExportPath] = useState<string | null>(null);

  const refreshStatic = useCallback(async () => {
    try {
      const [meetingData, lineageData, discoveryData, syncData, conflictData] =
        await Promise.all([
          api.meeting(),
          api.lineage(filters.tracked),
          api.discovery(),
          api.syncStatus(),
          api.conflicts(),
        ]);
      setMeeting(meetingData);
      setLineage(lineageData);
      setDiscovery(discoveryData);
      setSync(syncData);
      setConflicts(conflictData);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [filters.tracked]);

  const refreshTdocs = useCallback(async () => {
    try {
      const rows = await api.tdocs({
        agenda: filters.agenda || undefined,
        type: filters.type || undefined,
        state: filters.state || undefined,
        source: filters.source || undefined,
        tracked: filters.tracked ? true : undefined,
      });
      setTdocs(rows);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [filters.agenda, filters.source, filters.state, filters.tracked, filters.type]);

  useEffect(() => {
    void refreshStatic();
  }, [refreshStatic]);

  useEffect(() => {
    void refreshTdocs();
  }, [refreshTdocs]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      setTimeline([]);
      return;
    }
    let cancelled = false;
    Promise.all([api.tdoc(selected), api.timeline(selected)])
      .then(([detailData, events]) => {
        if (!cancelled) {
          setDetail(detailData);
          setTimeline(events);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const visibleTdocs = useMemo(() => {
    const needle = filters.search.trim().toLowerCase();
    if (!needle) {
      return tdocs;
    }
    return tdocs.filter((row) =>
      [row.tdoc_number, row.title, row.topic, row.agenda_item]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [filters.search, tdocs]);

  const onSync = useCallback(async () => {
    setBusy(true);
    try {
      await api.sync();
      await refreshStatic();
      await refreshTdocs();
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }, [refreshStatic, refreshTdocs]);

  const onExport = useCallback(() => {
    window.open("/api/export/markdown", "_blank", "noopener");
  }, []);

  const onFinalize = useCallback(async () => {
    setBusy(true);
    try {
      const result = await api.finalize();
      setExportPath(result.export_path);
      await refreshStatic();
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }, [refreshStatic]);

  const onTrack = useCallback(
    async (tdoc: string, tracked: boolean) => {
      try {
        await api.track(tdoc, tracked);
        await Promise.all([refreshTdocs(), refreshStatic()]);
        if (selected === tdoc) {
          setDetail(await api.tdoc(tdoc));
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshStatic, refreshTdocs, selected],
  );

  const onAddNote = useCallback(
    async (body: string, position: string) => {
      if (!selected) {
        return;
      }
      try {
        await api.addNote({
          target_kind: "tdoc",
          target_ref: selected,
          body,
          position_tag: position || null,
        });
        setDetail(await api.tdoc(selected));
        setTimeline(await api.timeline(selected));
        await refreshTdocs();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshTdocs, selected],
  );

  const refreshDetail = useCallback(async () => {
    if (!selected) {
      return;
    }
    const [detailData, events] = await Promise.all([
      api.tdoc(selected),
      api.timeline(selected),
    ]);
    setDetail(detailData);
    setTimeline(events);
  }, [selected]);

  const onDeleteNote = useCallback(
    async (noteId: number) => {
      try {
        await api.deleteNote(noteId);
        await Promise.all([refreshDetail(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshDetail, refreshTdocs],
  );

  const onAddAssertion = useCallback(
    async (subject: string, predicate: string, object: string) => {
      try {
        await api.addAssertion({
          subject_ref: subject,
          predicate,
          object_kind: "tdoc",
          object_ref: object,
        });
        await Promise.all([refreshDetail(), refreshStatic(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshDetail, refreshStatic, refreshTdocs],
  );

  const onResolveConflict = useCallback(
    async (id: number, resolution: ConflictResolution) => {
      try {
        await api.resolveConflict(id, resolution);
        await Promise.all([refreshStatic(), refreshDetail(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshDetail, refreshStatic, refreshTdocs],
  );

  const onPromote = useCallback(
    async (item: DiscoveryItem) => {
      try {
        if (item.action === "track" && item.tdocs[0]) {
          await api.track(item.tdocs[0], true);
        } else if (item.action === "promote" && item.assertion_id) {
          await api.updateAssertion(item.assertion_id, {
            active: true,
            muted: false,
          });
        }
        await Promise.all([refreshStatic(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshStatic, refreshTdocs],
  );

  const selectedConflicts = useMemo(
    () => conflicts.filter((item) => item.subject_ref === selected),
    [conflicts, selected],
  );

  return (
    <div className="app-shell">
      <TopBar
        meeting={meeting}
        filters={filters}
        sync={sync}
        busy={busy}
        exportPath={exportPath}
        onFilters={setFilters}
        onSync={onSync}
        onExport={onExport}
        onFinalize={onFinalize}
      />
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <main className="three-pane">
        <LeftRail
          tdocs={visibleTdocs}
          allTdocs={tdocs}
          filters={filters}
          selected={selected}
          onFilters={setFilters}
          onSelect={setSelected}
        />
        <CenterPane
          tab={tab}
          onTab={setTab}
          lineage={lineage}
          timeline={timeline}
          discovery={discovery}
          conflicts={conflicts}
          selected={selected}
          onSelect={setSelected}
          onResolve={onResolveConflict}
          onPromote={onPromote}
        />
        <DetailPanel
          detail={detail}
          includeEphemeral={filters.includeEphemeral}
          conflicts={selectedConflicts}
          onTrack={onTrack}
          onAddNote={onAddNote}
          onDeleteNote={onDeleteNote}
          onAddAssertion={onAddAssertion}
          onResolveConflict={onResolveConflict}
          onSelect={setSelected}
        />
      </main>
    </div>
  );
}
