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
  bar_color: string;
}

export interface SettingsSource {
  kind: string;
  protocol: string;
  host: string;
  port: number | null;
  base_path: string;
  username: string | null;
  password_set: boolean;
  password_env: string | null;
  tls: string;
}

export interface SettingsMail {
  kind: "mbox" | "eml";
  path: string | null;
  eml_dir: string | null;
}

export interface Settings {
  source: SettingsSource;
  mail: SettingsMail | null;
  lazy_drafts: boolean;
  excel: string;
  auto_sync: boolean;
  meeting_interval_s: number;
  idle_interval_s: number;
  bar_color: string;
}

export interface SettingsUpdate {
  kind: string;
  protocol: string;
  host: string;
  port: number | null;
  base_path: string;
  username: string | null;
  password?: string | null;
  clear_password?: boolean;
  tls: string;
  mail: SettingsMail | null;
  lazy_drafts: boolean;
  auto_sync: boolean;
  meeting_interval_s: number;
  idle_interval_s: number;
  bar_color: string;
}

export interface FetchResult {
  tdoc_number: string;
  fetched: number;
  artifacts: string[];
  failures: string[];
}

export interface ExcelImportResult {
  status: string;
  path: string;
  row_count: number;
  edge_count: number;
  issue_count: number;
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
  remote_mtime: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export type NodeStatus = "Support" | "Object" | "Clarify";

export interface Note {
  id: number;
  target_kind: string;
  target_ref: string;
  body: string;
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

export interface MailDetail extends MailSummary {
  body: string;
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

export interface UserAction {
  id: number;
  action: string;
  target_kind: string | null;
  target_ref: string | null;
  detail: string | null;
  created_at: string | null;
}

export interface NotificationItem {
  kind: string;
  ref: string;
  title: string;
  detail: string | null;
  tdocs: string[];
  tdoc_titles?: Record<string, string>;
  agenda_item: string | null;
  created_at: string | null;
  action: "track" | null;
  action_ref: string | null;
  seen?: boolean;
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
  node_status: NodeStatus | null;
  is_hidden: boolean;
  artifacts: Artifact[];
  notes: Note[];
  emails: MailSummary[];
  assertions: Assertion[];
}

export interface DraftDetail extends Artifact {
  tdoc_number: string;
  title: string;
  parent_title: string | null;
  agenda_item: string | null;
  node_status: NodeStatus | null;
  is_hidden: boolean;
  notes: Note[];
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
  topic?: string | null;
  type: string | null;
  source?: string | null;
  is_tracked: boolean;
  is_provisional: boolean;
  first_seen_at: string | null;
  notes_count?: number;
  node_status?: NodeStatus | null;
  is_hidden?: boolean;
  node_kind?: "tdoc" | "draft";
  attached_to?: string | null;
  artifact_id?: number | null;
  logical_path?: string | null;
  status?: string | null;
  remote_mtime?: string | null;
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
  emails?: MailSummary[];
}

export interface Lineage {
  nodes: LineageNode[];
  edges: LineageEdge[];
}


export interface SyncStatus {
  endpoint: string;
  health: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_due_at: string | null;
  last_error: string | null;
  interval_s: number;
  mode?: "meeting" | "idle";
  stale: boolean;
  refresh: Record<string, string | null>;
  counts: Record<string, number>;
  server_time: string;
}

export interface Filters {
  agenda: string[];
  type: string[];
  state: string[];
  source: string[];
  tracked: boolean;
  includeEphemeral: boolean;
  hideWithdrawn: boolean;
  hideNotTreated: boolean;
  hideUnknown: boolean;
  showHidden: boolean;
}

export interface LineageTab {
  id: string;
  label: string;
  filters: Filters;
}

export interface LineageFiltersConfig {
  agenda: string[];
  type: string[];
  state: string[];
  source: string[];
  tracked: boolean;
  include_ephemeral: boolean;
  hide_withdrawn: boolean;
  hide_not_treated: boolean;
  hide_unknown: boolean;
  show_hidden: boolean;
}

export interface LineageViewConfig {
  id: string;
  label: string;
  filters: LineageFiltersConfig;
}

export interface LineageViews {
  views: LineageViewConfig[];
  active_id: string | null;
}
