import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopBar } from "./TopBar";
import { meeting } from "../test/fixtures";

function renderTopBar(barColor: string) {
  render(
    <TopBar
      meeting={{ ...meeting, bar_color: barColor }}
      sync={null}
      busy={false}
      exportPath={null}
      onSync={vi.fn()}
      onExport={vi.fn()}
      onFinalize={vi.fn()}
      onSettings={vi.fn()}
      notificationPermission="unsupported"
      onEnableNotifications={vi.fn()}
    />,
  );
  return screen.getByRole("banner");
}

describe("TopBar", () => {
  it("fades the meeting bar color to white from left to right", () => {
    const bar = renderTopBar("#2457c5");
    expect(bar.style.background).toBe(
      "linear-gradient(90deg, rgb(36, 87, 197) 0%, rgb(255, 255, 255) 100%)",
    );
  });

  it("leaves the bar unthemed when the color is invalid", () => {
    const bar = renderTopBar("not-a-color");
    expect(bar.style.background).toBe("");
  });
});
