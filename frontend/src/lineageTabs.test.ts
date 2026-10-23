import { describe, expect, it } from "vitest";

import {
  createLineageTab,
  filtersFromConfig,
  lineageTabsFromConfig,
  lineageTabsToConfig,
} from "./lineageTabs";

describe("lineage tabs", () => {
  it("creates a default lineage view with empty filters", () => {
    const tab = createLineageTab();
    expect(tab.id).toBe("lineage-1");
    expect(tab.label).toBe("Lineage");
    expect(tab.filters.agenda).toEqual([]);
    expect(tab.filters.includeEphemeral).toBe(true);
  });

  it("gives every added view its own filter object", () => {
    const first = createLineageTab();
    const second = createLineageTab([first]);
    second.filters.agenda = ["5.3.1.3"];

    expect(second.id).toBe("lineage-2");
    expect(second.label).toBe("Lineage 2");
    expect(first.filters.agenda).toEqual([]);
  });

  it("does not share filter arrays between views", () => {
    const first = createLineageTab();
    const second = createLineageTab([first]);

    first.filters.agenda.push("5.3.1.3");
    first.filters.source.push("Huawei");

    expect(second.filters.agenda).toEqual([]);
    expect(second.filters.source).toEqual([]);
  });

  it("avoids duplicate labels after a view is renamed", () => {
    const first = { ...createLineageTab(), label: "Lineage 2" };
    const second = createLineageTab([first]);
    expect(second.label).toBe("Lineage 3");
    const third = createLineageTab([first, second]);
    expect(third.label).toBe("Lineage 4");
  });

  it("round-trips lineage views through the meeting config shape", () => {
    const tab = createLineageTab();
    tab.label = "Agenda 5.3.1.3";
    tab.filters.agenda = ["5.3.1.3", "5.3.1.4"];
    tab.filters.type = ["CR", "LS in"];
    tab.filters.state = ["agreed", "revised"];
    tab.filters.source = ["Huawei", "Nokia"];
    tab.filters.tracked = true;
    tab.filters.includeEphemeral = false;
    tab.filters.hideWithdrawn = true;

    const config = lineageTabsToConfig([tab]);
    expect(config).toEqual([
      {
        id: "lineage-1",
        label: "Agenda 5.3.1.3",
        filters: {
          agenda: ["5.3.1.3", "5.3.1.4"],
          type: ["CR", "LS in"],
          state: ["agreed", "revised"],
          source: ["Huawei", "Nokia"],
          tracked: true,
          include_ephemeral: false,
          hide_withdrawn: true,
          hide_not_treated: false,
          hide_unknown: false,
          show_hidden: false,
        },
      },
    ]);
    expect(lineageTabsFromConfig(config)).toEqual([tab]);
  });

  it("migrates legacy single-string filter values to lists", () => {
    const [tab] = lineageTabsFromConfig([
      {
        id: "lineage-1",
        label: "Legacy",
        filters: {
          agenda: "5.3.1.3",
          type: "CR",
          state: "agreed",
          source: "Huawei",
        },
      },
    ]);

    expect(tab.filters.agenda).toEqual(["5.3.1.3"]);
    expect(tab.filters.type).toEqual(["CR"]);
    expect(tab.filters.state).toEqual(["agreed"]);
    expect(tab.filters.source).toEqual(["Huawei"]);
  });

  it("falls back safely for stale or hand-edited view entries", () => {
    const restored = lineageTabsFromConfig([
      {
        id: "bad id",
        label: "   ",
        filters: { tracked: true, include_ephemeral: false },
      },
      {
        id: "view-2",
        label: "Tracked only",
        filters: { tracked: true },
      },
      { id: "view-2", label: "Duplicate id" },
    ]);

    expect(restored).toHaveLength(3);
    expect(restored[0].id).toBe("lineage-1");
    expect(restored[0].label).toBe("Lineage");
    expect(restored[0].filters.tracked).toBe(true);
    expect(restored[0].filters.includeEphemeral).toBe(false);
    expect(restored[1]).toMatchObject({
      id: "view-2",
      label: "Tracked only",
    });
    expect(restored[1].filters.tracked).toBe(true);
    expect(restored[2].id).toBe("lineage-2");
  });

  it("restores defaults for missing or invalid filter fields", () => {
    expect(filtersFromConfig(null)).toEqual(createLineageTab().filters);
    expect(
      filtersFromConfig({
        agenda: undefined,
        include_ephemeral: "yes" as unknown as boolean,
      }),
    ).toEqual(createLineageTab().filters);
  });
});
