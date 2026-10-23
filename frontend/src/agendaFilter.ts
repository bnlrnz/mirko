import type { LineageNode } from "./types";

const AGENDA_ORDER = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export interface AgendaFilterOption {
  value: string;
  label: string;
}

/**
 * Build agenda filter entries from lineage nodes. Agenda numbers are ordered
 * numerically (5.1.2 before 5.1.10), and the agenda topic is shown beside
 * each number when one is available.
 */
export function agendaFilterOptions(
  nodes: readonly Pick<LineageNode, "agenda_item" | "topic">[],
): AgendaFilterOption[] {
  const topics = new Map<string, string>();
  for (const node of nodes) {
    const agenda = node.agenda_item;
    if (!agenda || !agenda.trim()) {
      continue;
    }
    if (!topics.has(agenda)) {
      topics.set(agenda, "");
    }
    const topic = node.topic?.replace(/\s+/g, " ").trim();
    if (topic && !topics.get(agenda)) {
      topics.set(agenda, topic);
    }
  }

  return [...topics.entries()]
    .sort(([left], [right]) => AGENDA_ORDER.compare(left, right))
    .map(([agenda, topic]) => ({
      value: agenda,
      label: topic ? `${agenda} — ${topic}` : agenda,
    }));
}
