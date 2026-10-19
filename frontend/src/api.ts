import type {
  DiscoveryItem,
  Lineage,
  MailSummary,
  Meeting,
  SyncStatus,
  TdocDetail,
  TdocSummary,
  TimelineEvent,
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
  timeline: (tdoc: string) =>
    request<TimelineEvent[]>(
      `/api/tdocs/${encodeURIComponent(tdoc)}/timeline`,
    ),
  lineage: (trackedOnly: boolean) =>
    request<Lineage>(`/api/lineage${query({ tracked: trackedOnly })}`),
  mail: (params: Record<string, string | number | undefined> = {}) =>
    request<MailSummary[]>(
      `/api/mail${query(params as Record<string, string | undefined>)}`,
    ),
  discovery: () => request<DiscoveryItem[]>("/api/discovery"),
  syncStatus: () => request<SyncStatus>("/api/sync/status"),
  sync: () => request<{ status: string }>("/api/sync", { method: "POST" }),
  track: (tdoc: string, tracked: boolean) =>
    request<{ tdoc_number: string; is_tracked: boolean }>(
      `/api/tdocs/${encodeURIComponent(tdoc)}/track`,
      { method: tracked ? "POST" : "DELETE" },
    ),
  addNote: (body: {
    target_kind: string;
    target_ref: string;
    body: string;
    position_tag?: string | null;
  }) =>
    request<unknown>("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  finalize: () =>
    request<{ status: string; export_path: string }>("/api/finalize", {
      method: "POST",
    }),
};
