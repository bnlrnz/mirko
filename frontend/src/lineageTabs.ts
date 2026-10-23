import type {
  Filters,
  LineageFiltersConfig,
  LineageTab,
  LineageViewConfig,
} from "./types";

export const EMPTY_FILTERS: Filters = {
  agenda: [],
  type: [],
  state: [],
  source: [],
  tracked: false,
  includeEphemeral: true,
  hideWithdrawn: false,
  hideNotTreated: false,
  hideUnknown: false,
  showHidden: false,
};

type FilterConfigValue = string | readonly string[] | null | undefined;

interface LineageFiltersInput {
  agenda?: FilterConfigValue;
  type?: FilterConfigValue;
  state?: FilterConfigValue;
  source?: FilterConfigValue;
  tracked?: boolean;
  include_ephemeral?: boolean;
  hide_withdrawn?: boolean;
  hide_not_treated?: boolean;
  hide_unknown?: boolean;
  show_hidden?: boolean;
}

const VIEW_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
export const MAX_LINEAGE_LABEL = 80;

export function normalizeLineageLabel(label: string): string {
  return label.trim().slice(0, MAX_LINEAGE_LABEL);
}

function configValues(value: FilterConfigValue): string[] {
  if (typeof value === "string") {
    return value ? [value] : [];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  const result: string[] = [];
  for (const item of value) {
    if (typeof item === "string" && item && !result.includes(item)) {
      result.push(item);
    }
  }
  return result;
}

export function filtersToConfig(filters: Filters): LineageFiltersConfig {
  return {
    agenda: [...filters.agenda],
    type: [...filters.type],
    state: [...filters.state],
    source: [...filters.source],
    tracked: filters.tracked,
    include_ephemeral: filters.includeEphemeral,
    hide_withdrawn: filters.hideWithdrawn,
    hide_not_treated: filters.hideNotTreated,
    hide_unknown: filters.hideUnknown,
    show_hidden: filters.showHidden,
  };
}

export function filtersFromConfig(
  config: LineageFiltersInput | null | undefined,
): Filters {
  const value = config ?? {};
  return {
    agenda: configValues(value.agenda),
    type: configValues(value.type),
    state: configValues(value.state),
    source: configValues(value.source),
    tracked: typeof value.tracked === "boolean" ? value.tracked : false,
    includeEphemeral:
      typeof value.include_ephemeral === "boolean"
        ? value.include_ephemeral
        : true,
    hideWithdrawn:
      typeof value.hide_withdrawn === "boolean"
        ? value.hide_withdrawn
        : false,
    hideNotTreated:
      typeof value.hide_not_treated === "boolean"
        ? value.hide_not_treated
        : false,
    hideUnknown:
      typeof value.hide_unknown === "boolean" ? value.hide_unknown : false,
    showHidden:
      typeof value.show_hidden === "boolean" ? value.show_hidden : false,
  };
}

export function lineageTabsToConfig(
  tabs: readonly LineageTab[],
): LineageViewConfig[] {
  return tabs.map((tab) => ({
    id: tab.id,
    label: tab.label,
    filters: filtersToConfig(tab.filters),
  }));
}

/**
 * Rebuild lineage tabs from meeting.json. Hand-edited or stale values fall
 * back to safe defaults instead of preventing the application from loading.
 */
export function lineageTabsFromConfig(
  views:
    | readonly {
        id?: unknown;
        label?: unknown;
        filters?: LineageFiltersInput | null;
      }[]
    | null
    | undefined,
): LineageTab[] {
  const tabs: LineageTab[] = [];
  for (const view of views ?? []) {
    const fallback = createLineageTab(tabs);
    const candidateId =
      typeof view.id === "string" ? view.id.trim() : "";
    const id =
      VIEW_ID_RE.test(candidateId) &&
      !tabs.some((tab) => tab.id === candidateId)
        ? candidateId
        : fallback.id;
    const label =
      typeof view.label === "string"
        ? normalizeLineageLabel(view.label)
        : "";
    tabs.push({
      id,
      label: label || fallback.label,
      filters: filtersFromConfig(view.filters),
    });
  }
  return tabs;
}

/**
 * Create a new lineage view. Every view owns a fresh filter object so changing
 * one tab never mutates another.
 */
export function createLineageTab(
  existing: readonly LineageTab[] = [],
): LineageTab {
  const ids = new Set(existing.map((tab) => tab.id));
  let number = 1;
  while (ids.has(`lineage-${number}`)) {
    number += 1;
  }

  const labels = new Set(existing.map((tab) => tab.label));
  let label = number === 1 ? "Lineage" : `Lineage ${number}`;
  let suffix = number;
  while (labels.has(label)) {
    suffix += 1;
    label = `Lineage ${suffix}`;
  }

  return {
    id: `lineage-${number}`,
    label,
    filters: {
      ...EMPTY_FILTERS,
      agenda: [],
      type: [],
      state: [],
      source: [],
    },
  };
}
