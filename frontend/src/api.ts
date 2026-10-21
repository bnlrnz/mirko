import type {
  Assertion,
  Conflict,
  ConflictResolution,
  DraftDetail,
  ExcelImportResult,
  FetchResult,
  Lineage,
  MailSummary,
  Meeting,
  NodeStatus,
  Note,
  NotificationItem,
  Settings,
  SettingsUpdate,
  SyncStatus,
  TdocDetail,
  TdocSummary,
  TimelineEvent,
  UserAction,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  meeting: () => request<Meeting>("/api/meeting"),
  tdocs: (params: Record<string, string | boolean | undefined> = {}) =>
    request<TdocSummary[]>(`/api/tdocs${query(params)}`),
  tdoc: (tdoc: string) =>
    request<TdocDetail>(`/api/tdocs/${encodeURIComponent(tdoc)}`),
  draft: (artifactId: number) =>
    request<DraftDetail>(`/api/drafts/${artifactId}`),
  timeline: (tdoc: string) =>
    request<TimelineEvent[]>(
      `/api/tdocs/${encodeURIComponent(tdoc)}/timeline`,
    ),
  lineage: (
    trackedOnly: boolean,
    includeInactive = false,
    includeDrafts = true,
  ) =>
    request<Lineage>(
      `/api/lineage${query({
        tracked: trackedOnly,
        include_inactive: includeInactive,
        include_drafts: includeDrafts,
      })}`,
    ),
  mail: (params: Record<string, string | number | undefined> = {}) =>
    request<MailSummary[]>(
      `/api/mail${query(params as Record<string, string | undefined>)}`,
    ),
  notifications: () => request<NotificationItem[]>("/api/notifications"),
  log: () => request<UserAction[]>("/api/log"),
  conflicts: () => request<Conflict[]>("/api/conflicts"),
  resolveConflict: (id: number, resolution: ConflictResolution, note?: string) =>
    request<Conflict>(`/api/conflicts/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution, note }),
    }),
  addAssertion: (body: {
    subject_ref: string;
    predicate: string;
    object_kind?: string | null;
    object_ref?: string | null;
    value?: string | null;
    confidence?: number;
    detail?: string | null;
  }) =>
    request<Assertion>("/api/assertions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateAssertion: (
    id: number,
    body: { active?: boolean; muted?: boolean },
  ) =>
    request<Assertion>(`/api/assertions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateNote: (id: number, body: { body?: string }) =>
    request<Note>(`/api/notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteNote: (id: number) =>
    fetch(`/api/notes/${id}`, { method: "DELETE" }).then((response) => {
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
    }),
  syncStatus: () => request<SyncStatus>("/api/sync/status"),
  sync: () => request<{ status: string; deferred?: number }>("/api/sync", {
    method: "POST",
  }),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: SettingsUpdate) =>
    request<Settings>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  uploadExcel: (file: File) =>
    request<ExcelImportResult>(
      `/api/import/excel${query({ filename: file.name, force: true })}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      },
    ),
  fetchTdoc: (tdoc: string, lineage = true) =>
    request<FetchResult>(
      `/api/tdocs/${encodeURIComponent(tdoc)}/fetch${query({ lineage })}`,
      { method: "POST" },
    ),
  track: (tdoc: string, tracked: boolean) =>
    request<{ tdoc_number: string; is_tracked: boolean }>(
      `/api/tdocs/${encodeURIComponent(tdoc)}/track`,
      { method: tracked ? "POST" : "DELETE" },
    ),
  addNote: (body: {
    target_kind: string;
    target_ref: string;
    body: string;
  }) =>
    request<unknown>("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  setStatus: (body: {
    target_kind: "tdoc" | "draft";
    target_ref: string;
    status: NodeStatus | null;
  }) =>
    request<{ target_kind: string; target_ref: string; status: NodeStatus | null }>(
      "/api/status",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  finalize: () =>
    request<{ status: string; export_path: string }>("/api/finalize", {
      method: "POST",
    }),
};
