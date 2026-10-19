import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LineageView, layoutLineage } from "./LineageView";
import { lineage } from "../test/fixtures";

describe("LineageView", () => {
  it("lays out a revision chain on one lane", () => {
    const layout = layoutLineage(lineage);
    expect(layout.nodes).toHaveLength(2);
    const [first, second] = layout.nodes;
    expect(first.lane).toBe(second.lane);
    expect(second.depth).toBeGreaterThan(first.depth);
  });

  it("renders nodes, edges and selection", () => {
    const onSelect = vi.fn();
    render(
      <LineageView lineage={lineage} selected="S3-264202" onSelect={onSelect} />,
    );
    expect(screen.getByText("S3-264202")).toBeInTheDocument();
    expect(screen.getByText("S3-264203")).toBeInTheDocument();
    expect(
      screen.getByTestId("edge-S3-264202-S3-264203"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /S3-264203/ }));
    expect(onSelect).toHaveBeenCalledWith("S3-264203");
  });

  it("supports keyboard activation and zoom", () => {
    const onSelect = vi.fn();
    render(
      <LineageView lineage={lineage} selected={null} onSelect={onSelect} />,
    );
    const node = screen.getByRole("button", { name: /S3-264203/ });
    fireEvent.keyDown(node, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("S3-264203");
    fireEvent.click(screen.getByRole("button", { name: "+" }));
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });
});
