import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TimelineView } from "./TimelineView";
import { timeline } from "../test/fixtures";

describe("TimelineView", () => {
  it("renders events in order and marks ephemeral ones", () => {
    const { container } = render(
      <TimelineView events={timeline} selected="S3-264202" />,
    );
    expect(screen.getByText("S3-264202 first seen")).toBeInTheDocument();
    expect(screen.getByText("draft S3-264202-r1.docx")).toBeInTheDocument();
    expect(screen.getByText("[SA3#130][S3-264202] CR on QUIC")).toBeInTheDocument();
    expect(container.querySelectorAll(".timeline-event")).toHaveLength(3);
    expect(container.querySelectorAll(".timeline-event.ephemeral")).toHaveLength(1);
  });

  it("prompts for a selection", () => {
    render(<TimelineView events={[]} selected={null} />);
    expect(screen.getByText("Select a TDoc")).toBeInTheDocument();
  });
});
