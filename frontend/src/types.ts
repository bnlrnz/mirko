export interface Meeting {
  schema_version: number;
  id: string;
  title: string;
  timezone: string;
  days: string[];
  hours: { start: string; end: string };
  tdoc_series_prefix: string;
  source_kind: string;
  endpoint: string;
}

export interface TdocSummary {
  tdoc_number: string;
  agenda_item: string | null;
  topic: string | null;
  title: string | null;
  source: string | null;
  type: string | null;
  for_action: string | null;
  release: string | null;
  wi_code: string | null;
  avail: boolean | null;
  treated: boolean | null;
  treated_note: string | null;
  decision: string | null;
  state_source: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  is_tracked: boolean;
  is_provisional: boolean;
  notes_count: number;
  artifact_count: number;
  mention_count: number;
  has_conflict: boolean;
}

export interface Artifact {
  id: number;
  kind: string;
  logical_path: string;
  filename: string | null;
  status: string;
  is_ephemeral: boolean;
  blob_hash: string | null;
  remote_size: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface Note {
  id: number;
  target_kind: string;
  target_ref: string;
  body: string;
  position_tag: "Support" | "Object" | "Clarify" | null;
  author: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface MailSummary {
  id: number;
  message_id: string;
  thread_id: number | null;
  subject: string | null;
  from_addr: string | null;
  to_addrs: string | null;
  cc_addrs: string | null;
  date_utc: string | null;
  agenda_item: string | null;
  meeting_id: string | null;
  ingested_at: string;
  inference: unknown;
}

export interface Assertion {
  id: number;
  subject_kind: string;
  subject_ref: string;
  predicate: string;
  object_kind: string | null;
  object_ref: string | null;
  value: string | null;
  source: string;
  source_ref: string | null;
  confidence: number;
  verified: boolean;
  active: boolean;
  muted: boolean;
  superseded_by: number | null;
  observed_at: string;
  detail: unknown;
}

export type ConflictResolution = "accept_html" | "keep_mine" | "repair";

export interface Conflict {
  id: number;
  predicate: string;
  subject_ref: string;
  status: string;
  resolution: string | null;
  created_at: string;
  resolved_at: string | null;
  assertions: Assertion[];
}

export interface TdocDetail extends TdocSummary {
  raw_meta: unknown;
  artifacts: Artifact[];
  notes: Note[];
  emails: MailSummary[];
  assertions: Assertion[];
}

export interface TimelineEvent {
  kind: string;
  occurred_at: string | null;
  title: string | null;
  detail: string | null;
  source: string | null;
  artifact_id: number | null;
  email_id: number | null;
  ephemeral: boolean;
  sequence: number;
}

export interface LineageNode {
  tdoc_number: string;
  title: string | null;
  decision: string | null;
  state_source: string | null;
  agenda_item: string | null;
  type: string | null;
  is_tracked: boolean;
  is_provisional: boolean;
  first_seen_at: string | null;
}

export interface LineageEdge {
  source: string;
  target: string;
  kind: "revision_of" | "merged_into" | "based_on" | string;
  confidence: number;
  verified: boolean;
  source_ref: string | null;
  active?: boolean;
  muted?: boolean;
}

export interface Lineage {
  nodes: LineageNode[];
  edges: LineageEdge[];
}

export interface DiscoveryItem {
  kind: string;
  ref: string;
  title: string;
  detail: string | null;
  tdocs: string[];
  agenda_item: string | null;
  confidence: number;
  created_at: string | null;
  action?: "track" | "promote" | null;
  assertion_id?: number | null;
}

export interface SyncStatus {
  endpoint: string;
  health: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_due_at: string | null;
  last_error: string | null;
  interval_s: number;
  stale: boolean;
  refresh: Record<string, string | null>;
  counts: Record<string, number>;
  server_time: string;
}

export interface Filters {
  agenda: string;
  type: string;
  state: string;
  source: string;
  tracked: boolean;
  includeEphemeral: boolean;
  search: string;
}
