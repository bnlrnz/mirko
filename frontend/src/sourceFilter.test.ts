import { describe, expect, it } from "vitest";

import {
  sourceMatches,
  splitSourceCompanies,
  uniqueSourceCompanies,
} from "./sourceFilter";

describe("source filter", () => {
  it("splits comma-separated source lists into single companies", () => {
    expect(splitSourceCompanies("Huawei, HiSilicon")).toEqual([
      "Huawei",
      "HiSilicon",
    ]);
    expect(splitSourceCompanies("vivo,Nokia")).toEqual(["vivo", "Nokia"]);
    expect(splitSourceCompanies("  Ericsson ,  BSI (DE) ")).toEqual([
      "Ericsson",
      "BSI (DE)",
    ]);
  });

  it("creates a sorted set without case-only duplicates", () => {
    expect(
      uniqueSourceCompanies([
        "Huawei, HiSilicon",
        "Ericsson",
        "HUAWEI",
        null,
        "Nokia, Ericsson",
      ]),
    ).toEqual(["Ericsson", "HiSilicon", "Huawei", "Nokia"]);
  });

  it("matches any single company in a combined source field", () => {
    expect(sourceMatches("HiSilicon", "Huawei, HiSilicon")).toBe(true);
    expect(sourceMatches("huawei", "Huawei, HiSilicon")).toBe(true);
    expect(sourceMatches("Nokia", "Huawei, HiSilicon")).toBe(false);
    expect(sourceMatches("Huawei", null)).toBe(false);
  });
});
