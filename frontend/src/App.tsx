import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import {
  CenterPane,
  lineageTabKey,
  type CenterTab,
} from "./components/CenterPane";
import { DetailPanel } from "./components/DetailPanel";
import { LeftRail } from "./components/LeftRail";
import { SettingsPanel } from "./components/SettingsPanel";
import { TopBar } from "./components/TopBar";
import {
  createLineageTab,
  lineageTabsFromConfig,
  lineageTabsToConfig,
  normalizeLineageLabel,
} from "./lineageTabs";
import type {
  Conflict,
  ConflictResolution,
  DraftDetail,
  Filters,
  Lineage,
  LineageTab,
  Meeting,
  NodeStatus,
  NotificationItem,
  Settings,
  SettingsUpdate,
  SyncStatus,
  TdocDetail,
  TdocSummary,
  TimelineEvent,
  UserAction,
} from "./types";

function sendSystemNotification(
  item: NotificationItem,
  onOpen: (tdoc: string) => void,
) {
  if (
    typeof window === "undefined" ||
    !("Notification" in window) ||
    window.Notification.permission !== "granted"
  ) {
    return;
  }
  const notification = new window.Notification(item.title, {
    body: item.detail ?? item.tdocs.join(", "),
    tag: `mirko-${item.ref}`,
  });
  notification.onclick = () => {
    window.focus();
    onOpen(item.tdocs[0] ?? "");
    notification.close();
  };
}

function currentNotificationPermission(): NotificationPermission | "unsupported" {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "unsupported";
  }
  return window.Notification.permission;
}

export default function App() {
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [tdocs, setTdocs] = useState<TdocSummary[]>([]);
  const [lineageTabs, setLineageTabs] = useState<LineageTab[]>(() => [
    createLineageTab(),
  ]);
  const [lineageViewsLoaded, setLineageViewsLoaded] = useState(false);
  const [activeLineageTabId, setActiveLineageTabId] = useState("lineage-1");
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<number | null>(null);
  const [draft, setDraft] = useState<DraftDetail | null>(null);
  const [lineageFocus, setLineageFocus] = useState<{
    tdoc: string;
    nonce: number;
  } | null>(null);
  const [highlightArtifact, setHighlightArtifact] = useState<number | null>(
    null,
  );
  const [detail, setDetail] = useState<TdocDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [lineage, setLineage] = useState<Lineage>({ nodes: [], edges: [] });
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [seenNotifications, setSeenNotifications] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const [newArtifacts, setNewArtifacts] = useState<NotificationItem[]>([]);
  const [notificationPermission, setNotificationPermission] = useState<
    NotificationPermission | "unsupported"
  >(currentNotificationPermission);
  const [log, setLog] = useState<UserAction[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [tab, setTab] = useState<CenterTab>(lineageTabKey("lineage-1"));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exportPath, setExportPath] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const fetched = useRef(new Set<string>());
  const staticRequest = useRef(0);
  const lastSyncMarker = useRef<string | null>(null);
  const knownArtifacts = useRef<Set<string> | null>(null);
  const notificationsRef = useRef<NotificationItem[]>([]);
  const lineageSaveQueue = useRef<Promise<void>>(Promise.resolve());

  const clearArtifactHighlight = useCallback(() => {
    setHighlightArtifact(null);
  }, []);

  const markNotificationsSeen = useCallback((refs: Iterable<string>) => {
    setSeenNotifications((current) => {
      const next = new Set(current);
      let changed = false;
      for (const ref of refs) {
        if (!next.has(ref)) {
          next.add(ref);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, []);

  const onSelect = useCallback((tdoc: string, artifactId?: number) => {
    setSelected(tdoc);
    setSelectedDraft(null);
    setDraft(null);
    setHighlightArtifact(artifactId ?? null);
    setNewArtifacts((current) =>
      current.filter((item) => !item.tdocs.includes(tdoc)),
    );
    markNotificationsSeen(
      notificationsRef.current
        .filter((item) => item.tdocs.includes(tdoc))
        .map((item) => item.ref),
    );
  }, [markNotificationsSeen]);

  const onSelectDraft = useCallback(
    (artifactId: number) => {
      setSelected(null);
      setDraft(null);
      setSelectedDraft(artifactId);
      setHighlightArtifact(null);
      const path = lineage.nodes.find(
        (node) => node.artifact_id === artifactId,
      )?.logical_path;
      if (path) {
        setNewArtifacts((current) =>
          current.filter((item) => item.ref !== path),
        );
        markNotificationsSeen([path]);
      }
    },
    [lineage.nodes, markNotificationsSeen],
  );

  const announceArtifacts = useCallback(
    (items: NotificationItem[]) => {
      const artifacts = items.filter((item) => item.kind === "artifact");
      const known = knownArtifacts.current;
      if (known === null) {
        knownArtifacts.current = new Set(artifacts.map((item) => item.ref));
        return;
      }
      const fresh = artifacts.filter((item) => !known.has(item.ref));
      for (const item of artifacts) {
        known.add(item.ref);
      }
      if (fresh.length === 0) {
        return;
      }
      setNewArtifacts((current) => [
        ...fresh,
        ...current.filter(
          (item) => !fresh.some((next) => next.ref === item.ref),
        ),
      ].slice(0, 50));
      for (const item of fresh) {
        sendSystemNotification(item, onSelect);
      }
    },
    [onSelect],
  );

  const enableNotifications = useCallback(async () => {
    if (
      typeof window === "undefined" ||
      !("Notification" in window)
    ) {
      return;
    }
    setNotificationPermission(await window.Notification.requestPermission());
  }, []);

  const onFocusTdoc = useCallback(
    (tdoc: string) => {
      onSelect(tdoc);
      setTab(lineageTabKey(activeLineageTabId));
      setLineageFocus((current) => ({
        tdoc,
        nonce: (current?.nonce ?? 0) + 1,
      }));
    },
    [activeLineageTabId, onSelect],
  );

  const onAddLineageTab = useCallback(() => {
    const next = createLineageTab(lineageTabs);
    setLineageTabs((current) => [...current, next]);
    setActiveLineageTabId(next.id);
    setTab(lineageTabKey(next.id));
  }, [lineageTabs]);

  const onCenterTab = useCallback((next: CenterTab) => {
    setTab(next);
    if (next.startsWith("lineage:")) {
      setActiveLineageTabId(next.slice("lineage:".length));
    }
  }, []);

  const onCloseLineageTab = useCallback(
    (id: string) => {
      if (lineageTabs.length <= 1) {
        return;
      }
      const index = lineageTabs.findIndex((item) => item.id === id);
      if (index < 0) {
        return;
      }
      const remaining = lineageTabs.filter((item) => item.id !== id);
      setLineageTabs(remaining);
      if (activeLineageTabId === id) {
        const fallback = remaining[Math.min(index, remaining.length - 1)];
        setActiveLineageTabId(fallback.id);
        setTab((current) =>
          current === lineageTabKey(id)
            ? lineageTabKey(fallback.id)
            : current,
        );
      }
    },
    [activeLineageTabId, lineageTabs],
  );

  const onRenameLineageTab = useCallback((id: string, label: string) => {
    const trimmed = normalizeLineageLabel(label);
    if (!trimmed) {
      return;
    }
    setLineageTabs((current) =>
      current.map((item) =>
        item.id === id ? { ...item, label: trimmed } : item,
      ),
    );
  }, []);

  const onLineageFilters = useCallback((id: string, filters: Filters) => {
    setLineageTabs((current) =>
      current.map((item) =>
        item.id === id ? { ...item, filters } : item,
      ),
    );
  }, []);

  const refreshStatic = useCallback(async () => {
    const request = ++staticRequest.current;
    try {
      const [
        meetingData,
        lineageData,
        notificationData,
        logData,
        syncData,
        conflictData,
      ] = await Promise.all([
        api.meeting(),
        api.lineage(false, false, true),
        api.notifications(),
        api.log(),
        api.syncStatus(),
        api.conflicts(),
      ]);
      if (request !== staticRequest.current) {
        return;
      }
      setMeeting(meetingData);
      setLineage(lineageData);
      notificationsRef.current = notificationData;
      setNotifications(notificationData);
      announceArtifacts(notificationData);
      setLog(logData);
      setSync(syncData);
      setConflicts(conflictData);
      setError(null);
    } catch (caught) {
      if (request === staticRequest.current) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    }
  }, [announceArtifacts]);

  const refreshTdocs = useCallback(async () => {
    try {
      setTdocs(await api.tdocs({ tracked: true }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void refreshStatic();
  }, [refreshStatic]);

  useEffect(() => {
    void refreshTdocs();
  }, [refreshTdocs]);

  useEffect(() => {
    let cancelled = false;
    api
      .lineageViews()
      .then((data) => {
        if (cancelled) {
          return;
        }
        const views = Array.isArray(data?.views) ? data.views : [];
        const restored = lineageTabsFromConfig(views);
        if (restored.length > 0) {
          const activeId =
            typeof data.active_id === "string" &&
            restored.some((tab) => tab.id === data.active_id)
              ? data.active_id
              : restored[0].id;
          setLineageTabs(restored);
          setActiveLineageTabId(activeId);
          setTab(lineageTabKey(activeId));
        }
        setLineageViewsLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          setLineageViewsLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!lineageViewsLoaded) {
      return;
    }
    const timer = window.setTimeout(() => {
      const body = {
        views: lineageTabsToConfig(lineageTabs),
        active_id: activeLineageTabId,
      };
      lineageSaveQueue.current = lineageSaveQueue.current.then(async () => {
        try {
          await api.saveLineageViews(body);
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeLineageTabId, lineageTabs, lineageViewsLoaded]);

  useEffect(() => {
    lastSyncMarker.current =
      sync?.last_attempt_at ?? sync?.last_success_at ?? null;
  }, [sync]);

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

  useEffect(() => {
    if (selectedDraft === null) {
      setDraft(null);
      return;
    }
    let cancelled = false;
    api
      .draft(selectedDraft)
      .then((data) => {
        if (!cancelled) {
          setDraft(data);
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
  }, [selectedDraft]);

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

  const refreshDraft = useCallback(async () => {
    if (selectedDraft === null) {
      return;
    }
    setDraft(await api.draft(selectedDraft));
  }, [selectedDraft]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void api
        .syncStatus()
        .then(async (status) => {
          const marker =
            status.last_attempt_at ?? status.last_success_at ?? null;
          const changed =
            marker !== null && marker !== lastSyncMarker.current;
          setSync(status);
          if (changed) {
            lastSyncMarker.current = marker;
            await Promise.all([refreshStatic(), refreshTdocs()]);
            if (selected) {
              await refreshDetail();
            } else if (selectedDraft !== null) {
              await refreshDraft();
            }
          }
        })
        .catch(() => {
          // Keep the last known status while the backend is unavailable.
        });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [
    refreshDetail,
    refreshDraft,
    refreshStatic,
    refreshTdocs,
    selected,
    selectedDraft,
  ]);


  const onSync = useCallback(async () => {
    setBusy(true);
    try {
      await api.sync();
      fetched.current.clear();
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
        if (tracked) {
          fetched.current.delete(tdoc);
          const result = await api.fetchTdoc(tdoc, true);
          if (result.failures.length > 0) {
            setError(result.failures.join("; "));
          }
        }
        await Promise.all([refreshTdocs(), refreshStatic()]);
        if (selected === tdoc) {
          await refreshDetail();
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshDetail, refreshStatic, refreshTdocs, selected],
  );

  const onAddNote = useCallback(
    async (
      body: string,
      target: { kind: "tdoc" | "draft"; ref: string },
    ) => {
      try {
        await api.addNote({
          target_kind: target.kind,
          target_ref: target.ref,
          body,
        });
        if (target.kind === "tdoc") {
          setDetail(await api.tdoc(target.ref));
          setTimeline(await api.timeline(target.ref));
        } else {
          setDraft(await api.draft(Number(target.ref)));
        }
        await Promise.all([refreshStatic(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshStatic, refreshTdocs],
  );

  const onSetStatus = useCallback(
    async (
      status: NodeStatus | null,
      target: { kind: "tdoc" | "draft"; ref: string },
    ) => {
      try {
        await api.setStatus({
          target_kind: target.kind,
          target_ref: target.ref,
          status,
        });
        if (target.kind === "tdoc") {
          setDetail(await api.tdoc(target.ref));
        } else {
          setDraft(await api.draft(Number(target.ref)));
        }
        await Promise.all([refreshStatic(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshStatic, refreshTdocs],
  );

  const onSetHidden = useCallback(
    async (
      hidden: boolean,
      target: { kind: "tdoc" | "draft"; ref: string },
    ) => {
      try {
        await api.setHidden({
          target_kind: target.kind,
          target_ref: target.ref,
          hidden,
        });
        if (target.kind === "tdoc") {
          setDetail(await api.tdoc(target.ref));
        } else {
          setDraft(await api.draft(Number(target.ref)));
        }
        await Promise.all([refreshStatic(), refreshTdocs()]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshStatic, refreshTdocs],
  );

  const onDeleteNote = useCallback(
    async (noteId: number) => {
      try {
        await api.deleteNote(noteId);
        await Promise.all([
          refreshDetail(),
          refreshDraft(),
          refreshStatic(),
          refreshTdocs(),
        ]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [refreshDetail, refreshDraft, refreshStatic, refreshTdocs],
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

  const onFetch = useCallback(async () => {
    if (!selected) {
      return;
    }
    setFetching(true);
    try {
      const result = await api.fetchTdoc(selected, false);
      if (result.failures.length > 0) {
        setError(result.failures.join("; "));
      }
      await refreshDetail();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setFetching(false);
    }
  }, [refreshDetail, selected]);

  useEffect(() => {
    if (!selected || !detail || detail.tdoc_number !== selected) {
      return;
    }
    const missing = detail.artifacts.some(
      (artifact) =>
        artifact.blob_hash === null &&
        (artifact.status === "remote" || artifact.status === "failed"),
    );
    if (!missing || fetched.current.has(selected)) {
      return;
    }
    fetched.current.add(selected);
    setFetching(true);
    api
      .fetchTdoc(selected, false)
      .then(async (result) => {
        if (result.failures.length > 0) {
          setError(result.failures.join("; "));
        }
        if (result.fetched > 0) {
          await refreshDetail();
        }
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => setFetching(false));
  }, [detail, refreshDetail, selected]);

  const onSettings = useCallback(async () => {
    try {
      setSettings(await api.settings());
      setSettingsOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  const onSaveSettings = useCallback(
    async (update: SettingsUpdate) => {
      setSettingsBusy(true);
      try {
        const saved = await api.saveSettings(update);
        setSettings(saved);
        setMeeting(await api.meeting());
        setSettingsOpen(false);
        await Promise.all([refreshStatic(), refreshTdocs()]);
        setError(null);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setSettingsBusy(false);
      }
    },
    [refreshStatic, refreshTdocs],
  );

  const onUploadExcel = useCallback(
    async (file: File) => {
      const result = await api.uploadExcel(file);
      setSettings(await api.settings());
      await Promise.all([refreshStatic(), refreshTdocs()]);
      if (selected) {
        await refreshDetail();
      }
      return `${result.status}: ${result.row_count} rows, ${result.edge_count} edges, ${result.issue_count} issues`;
    },
    [refreshDetail, refreshStatic, refreshTdocs, selected],
  );

  const selectedConflicts = useMemo(
    () => conflicts.filter((item) => item.subject_ref === selected),
    [conflicts, selected],
  );

  const unreadNotificationCount = useMemo(
    () =>
      notifications.reduce(
        (count, item) => count + (seenNotifications.has(item.ref) ? 0 : 1),
        0,
      ),
    [notifications, seenNotifications],
  );
  const newArtifactPaths = useMemo(
    () => new Set(newArtifacts.map((item) => item.ref)),
    [newArtifacts],
  );
  const newArtifactTdocs = useMemo(
    () => new Set(newArtifacts.flatMap((item) => item.tdocs)),
    [newArtifacts],
  );

  return (
    <div className="app-shell">
      <TopBar
        meeting={meeting}
        sync={sync}
        busy={busy}
        exportPath={exportPath}
        onSync={onSync}
        onExport={onExport}
        onFinalize={onFinalize}
        onSettings={onSettings}
        notificationPermission={notificationPermission}
        onEnableNotifications={() => void enableNotifications()}
      />
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <main className="three-pane">
        <LeftRail
          tdocs={tdocs}
          selected={selected}
          notifications={notifications}
          seenNotifications={seenNotifications}
          onSelect={onSelect}
          onFocusTdoc={onFocusTdoc}
          onTrack={onTrack}
        />
        <CenterPane
          tab={tab}
          onTab={onCenterTab}
          lineageTabs={lineageTabs}
          onAddLineageTab={onAddLineageTab}
          onCloseLineageTab={onCloseLineageTab}
          onRenameLineageTab={onRenameLineageTab}
          onLineageFilters={onLineageFilters}
          lineage={lineage}
          timeline={timeline}
          notifications={notifications}
          unreadNotificationCount={unreadNotificationCount}
          seenNotifications={seenNotifications}
          onNotificationSeen={markNotificationsSeen}
          log={log}
          conflicts={conflicts}
          selected={selected}
          selectedDraft={selectedDraft}
          favoriteOrder={tdocs.map((row) => row.tdoc_number)}
          onSelect={onSelect}
          onSelectDraft={onSelectDraft}
          focusRequest={lineageFocus}
          newArtifactPaths={newArtifactPaths}
          newArtifactTdocs={newArtifactTdocs}
          onResolve={onResolveConflict}
          onTrack={onTrack}
        />
        <DetailPanel
          detail={detail}
          draft={draft}
          endpoint={meeting?.endpoint ?? null}
          conflicts={selectedConflicts}
          onTrack={onTrack}
          onAddNote={onAddNote}
          onSetStatus={onSetStatus}
          onSetHidden={onSetHidden}
          onDeleteNote={onDeleteNote}
          onAddAssertion={onAddAssertion}
          onResolveConflict={onResolveConflict}
          onSelect={onSelect}
          onFetch={onFetch}
          fetching={fetching}
          seriesPrefix={meeting?.tdoc_series_prefix ?? ""}
          highlightArtifactId={highlightArtifact}
          onClearArtifactHighlight={clearArtifactHighlight}
        />
      </main>
      {settingsOpen && settings ? (
        <SettingsPanel
          settings={settings}
          busy={settingsBusy}
          onClose={() => setSettingsOpen(false)}
          onSave={(update) => void onSaveSettings(update)}
          onUpload={onUploadExcel}
        />
      ) : null}
    </div>
  );
}
