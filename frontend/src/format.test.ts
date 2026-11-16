import { describe, expect, it } from "vitest";

import { formatDateTime, formatTime } from "./format";

describe("format", () => {
  it("formats clock times with a 24-hour cycle", () => {
    const afternoon = new Date(2026, 9, 16, 15, 5);

    expect(formatTime(afternoon.toISOString())).toBe("15:05:00");
    expect(formatDateTime(afternoon.toISOString())).toContain("15:05:00");
  });

  it("renders midnight as 00:00:00", () => {
    const midnight = new Date(2026, 9, 16, 0, 0);

    expect(formatTime(midnight.toISOString())).toBe("00:00:00");
  });

  it("returns the original value when it cannot be parsed", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
