import { describe, expect, it } from "vitest";

import { agendaFilterOptions } from "./agendaFilter";

describe("agenda filter options", () => {
  it("orders agenda numbers numerically instead of alphabetically", () => {
    const options = agendaFilterOptions([
      { agenda_item: "5.1.10", topic: "Tenth" },
      { agenda_item: "5.1.2", topic: "Second" },
      { agenda_item: "5.1.1", topic: "First" },
      { agenda_item: "5.1.20", topic: "Twentieth" },
      { agenda_item: "5.1.3", topic: "Third" },
    ]);

    expect(options.map((option) => option.value)).toEqual([
      "5.1.1",
      "5.1.2",
      "5.1.3",
      "5.1.10",
      "5.1.20",
    ]);
  });

  it("shows the agenda topic beside the number", () => {
    const options = agendaFilterOptions([
      { agenda_item: "5.1.2", topic: "  Security   and privacy  " },
      { agenda_item: "5.1.3", topic: "" },
    ]);

    expect(options).toEqual([
      { value: "5.1.2", label: "5.1.2 — Security and privacy" },
      { value: "5.1.3", label: "5.1.3" },
    ]);
  });

  it("deduplicates agenda numbers and ignores empty entries", () => {
    const options = agendaFilterOptions([
      { agenda_item: "5.1.2", topic: "" },
      { agenda_item: "5.1.2", topic: "Security" },
      { agenda_item: "   ", topic: "Ignored" },
      { agenda_item: null, topic: "Ignored" },
    ]);

    expect(options).toEqual([
      { value: "5.1.2", label: "5.1.2 — Security" },
    ]);
  });
});
