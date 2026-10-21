import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LineageView, chainDrafts, layoutLineage } from "./LineageView";
import { lineage } from "../test/fixtures";
import type { Lineage } from "../types";

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

  it("does not render edges without both endpoint nodes", () => {
    const dangling = {
      ...lineage,
      edges: [
        ...lineage.edges,
        {
          source: "S3-264202",
          target: "S3-999999",
          kind: "revision_of",
          confidence: 1,
          verified: true,
          source_ref: "test",
        },
      ],
    };
    render(
      <LineageView lineage={dangling} selected={null} onSelect={vi.fn()} />,
    );
    expect(
      screen.queryByTestId("edge-S3-264202-S3-999999"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("1 edges")).toBeInTheDocument();
  });

  it("shows working drafts only when included", () => {
    const onSelect = vi.fn();
    const onSelectDraft = vi.fn();
    const withDraft: Lineage = {
      ...lineage,
      nodes: [
        ...lineage.nodes,
        {
          ...lineage.nodes[0],
          tdoc_number: "draft:1",
          title: "draft S3-264202-r1.docx",
          decision: "present",
          node_kind: "draft",
          attached_to: "S3-264202",
          artifact_id: 1,
          logical_path: "Inbox/Drafts/draft S3-264202-r1.docx",
          status: "present",
        },
      ],
      edges: [
        ...lineage.edges,
        {
          source: "S3-264202",
          target: "draft:1",
          kind: "has_draft",
          confidence: 1,
          verified: true,
          source_ref: null,
        },
      ],
    };
    const { rerender } = render(
      <LineageView
        lineage={withDraft}
        selected={null}
        includeDrafts
        onSelect={onSelect}
        onSelectDraft={onSelectDraft}
        newArtifactPaths={
          new Set(["Inbox/Drafts/draft S3-264202-r1.docx"])
        }
        newArtifactTdocs={new Set(["S3-264202"])}
      />,
    );
    expect(screen.getByText("3 nodes")).toBeInTheDocument();
    expect(
      screen.getByTestId("edge-S3-264202-draft:1"),
    ).toHaveClass("has_draft");
    const draft = screen.getByRole("button", {
      name: /draft draft S3-264202-r1.docx for S3-264202 present tracked/,
    });
    expect(draft).toHaveClass("new-file");
    expect(
      screen.getByRole("button", {
        name: /S3-264202 Original CR revised tracked/,
      }),
    ).toHaveClass("new-file");
    fireEvent.click(draft);
    expect(onSelectDraft).toHaveBeenCalledWith(1);
    expect(onSelect).not.toHaveBeenCalled();

    expect(
      screen.queryByRole("checkbox", { name: "Drafts" }),
    ).not.toBeInTheDocument();
    rerender(
      <LineageView
        lineage={withDraft}
        selected={null}
        includeDrafts={false}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText("2 nodes")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /draft S3-264202-r1.docx for/ }),
    ).not.toBeInTheDocument();
  });

  it("chains drafts in creation order before the revised TDoc", () => {
    const base = lineage.nodes[0];
    const revised = lineage.nodes[1];
    const chained = chainDrafts({
      nodes: [
        base,
        {
          ...base,
          tdoc_number: "draft:1",
          title: "draft S3-264202-r1.docx",
          node_kind: "draft",
          attached_to: "S3-264203",
          artifact_id: 1,
          remote_mtime: "2026-10-16T09:00:00",
        },
        {
          ...base,
          tdoc_number: "draft:2",
          title: "draft S3-264202-r2.docx",
          node_kind: "draft",
          attached_to: "S3-264203",
          artifact_id: 2,
          remote_mtime: "2026-10-16T10:00:00",
        },
        revised,
      ],
      edges: [
        ...lineage.edges,
        {
          source: "S3-264203",
          target: "draft:1",
          kind: "has_draft",
          confidence: 1,
          verified: true,
          source_ref: null,
        },
        {
          source: "S3-264203",
          target: "draft:2",
          kind: "has_draft",
          confidence: 1,
          verified: true,
          source_ref: null,
        },
      ],
    });
    expect(chained.edges).toContainEqual(
      expect.objectContaining({
        source: "S3-264202",
        target: "draft:1",
        kind: "revision_of",
      }),
    );
    expect(chained.edges).toContainEqual(
      expect.objectContaining({
        source: "draft:1",
        target: "draft:2",
        kind: "has_draft",
      }),
    );
    expect(chained.edges).toContainEqual(
      expect.objectContaining({
        source: "draft:2",
        target: "S3-264203",
        kind: "revision_of",
      }),
    );
    expect(chained.edges).not.toContainEqual(
      expect.objectContaining({
        source: "S3-264202",
        target: "S3-264203",
      }),
    );

    const layout = layoutLineage(chained);
    const depth = new Map(
      layout.nodes.map((node) => [node.tdoc_number, node.depth]),
    );
    expect(depth.get("draft:1")).toBeGreaterThan(depth.get("S3-264202") ?? 0);
    expect(depth.get("draft:2")).toBeGreaterThan(depth.get("draft:1") ?? 0);
    expect(depth.get("S3-264203")).toBeGreaterThan(depth.get("draft:2") ?? 0);
  });

  it("renders note badges for the latest note type", () => {
    const badges = ["Support", "Object", "Clarify", "note", null].map(
      (note_badge, index) => ({
        ...lineage.nodes[0],
        tdoc_number: `S3-26420${index + 2}`,
        note_badge,
      }),
    );
    render(
      <LineageView
        lineage={{ nodes: badges, edges: [] }}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("note-badge-S3-264202").querySelector("svg"),
    ).toHaveClass("note-badge-support");
    expect(
      screen.getByTestId("note-badge-S3-264203").querySelector("svg"),
    ).toHaveClass("note-badge-object");
    expect(
      screen.getByTestId("note-badge-S3-264204").querySelector("svg"),
    ).toHaveClass("note-badge-clarify");
    expect(
      screen.getByTestId("note-badge-S3-264205").querySelector("svg"),
    ).toHaveClass("note-badge-icon");
    expect(
      screen.queryByTestId("note-badge-S3-264206"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("note-badge-S3-264202").querySelector("rect"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("note-badge-S3-264202").querySelectorAll("path"),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: /S3-264202 Original CR/ }),
    ).toHaveClass("note-tint-support");
    expect(
      screen.getByRole("button", { name: /S3-264203 Original CR/ }),
    ).toHaveClass("note-tint-object");
    expect(
      screen.getByRole("button", { name: /S3-264204 Original CR/ }),
    ).toHaveClass("note-tint-clarify");
    expect(
      screen.getByRole("button", { name: /S3-264205 Original CR/ }),
    ).toHaveClass("note-tint-note");
    expect(
      screen.getByRole("button", { name: /S3-264206 Original CR/ }),
    ).not.toHaveClass("note-tint-note");
  });

  it("toggles tracking when a node is double-clicked", () => {
    const onTrack = vi.fn();
    render(
      <LineageView
        lineage={lineage}
        selected={null}
        onSelect={vi.fn()}
        onTrack={onTrack}
      />,
    );
    fireEvent.doubleClick(
      screen.getByRole("button", { name: /S3-264203 Revised CR agreed/ }),
    );
    expect(onTrack).toHaveBeenCalledWith("S3-264203", true);
  });

  it("colors replied-to TDocs like approved ones", () => {
    const replied: Lineage = {
      ...lineage,
      nodes: [
        {
          ...lineage.nodes[0],
          decision: "replied to",
        },
      ],
      edges: [],
    };
    render(
      <LineageView lineage={replied} selected={null} onSelect={vi.fn()} />,
    );
    expect(
      screen.getByRole("button", { name: /S3-264202 Original CR replied to/ }),
    ).toHaveClass("state-approved");
  });

  it("pans the canvas by click and drag", () => {
    render(<LineageView lineage={lineage} selected={null} onSelect={vi.fn()} />);
    const canvas = screen.getByTestId("lineage-scroll");
    canvas.scrollLeft = 100;
    canvas.scrollTop = 50;

    fireEvent.pointerDown(canvas, {
      button: 0,
      clientX: 200,
      clientY: 200,
      pointerId: 1,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 150,
      clientY: 160,
      pointerId: 1,
    });

    expect(canvas.scrollLeft).toBe(150);
    expect(canvas.scrollTop).toBe(90);
    expect(canvas).toHaveClass("panning");
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    expect(canvas).not.toHaveClass("panning");
  });

  it("does not pan or swallow clicks that start on a node", () => {
    const onSelect = vi.fn();
    render(<LineageView lineage={lineage} selected={null} onSelect={onSelect} />);
    const canvas = screen.getByTestId("lineage-scroll");
    const node = screen.getByRole("button", { name: /S3-264203/ });
    canvas.scrollLeft = 75;
    canvas.scrollTop = 40;

    fireEvent.pointerDown(node, {
      button: 0,
      clientX: 200,
      clientY: 200,
      pointerId: 1,
    });
    fireEvent.pointerMove(node, {
      clientX: 100,
      clientY: 100,
      pointerId: 1,
    });
    fireEvent.pointerUp(node, { pointerId: 1 });

    expect(canvas.scrollLeft).toBe(75);
    expect(canvas.scrollTop).toBe(40);
    expect(canvas).not.toHaveClass("panning");
    fireEvent.click(node);
    expect(onSelect).toHaveBeenCalledWith("S3-264203");
  });

  it("keeps momentum after a fling and stops it on click", () => {
    render(<LineageView lineage={lineage} selected={null} onSelect={vi.fn()} />);
    const canvas = screen.getByTestId("lineage-scroll");
    canvas.scrollLeft = 100;

    let clock = 0;
    const now = vi.spyOn(performance, "now").mockImplementation(() => clock);
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.push(callback);
      return frames.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});

    fireEvent.pointerDown(canvas, {
      button: 0,
      clientX: 400,
      clientY: 400,
      pointerId: 1,
    });
    clock = 100;
    fireEvent.pointerMove(canvas, {
      clientX: 200,
      clientY: 200,
      pointerId: 1,
    });
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    fireEvent.click(canvas);

    expect(frames).toHaveLength(1);
    frames[0](116);
    expect(canvas.scrollLeft).toBeGreaterThan(300);
    const flinging = canvas.scrollLeft;

    clock = 116;
    fireEvent.pointerDown(canvas, {
      button: 0,
      clientX: 300,
      clientY: 300,
      pointerId: 2,
    });
    fireEvent.pointerUp(canvas, { pointerId: 2 });
    fireEvent.click(canvas);
    expect(canvas.scrollLeft).toBe(flinging);

    now.mockRestore();
    vi.restoreAllMocks();
  });

  it("scrolls to the requested TDoc node", async () => {
    render(
      <LineageView
        lineage={lineage}
        selected={null}
        onSelect={vi.fn()}
        focusRequest={{ tdoc: "S3-264203", nonce: 1 }}
      />,
    );
    const canvas = screen.getByTestId("lineage-scroll");
    await waitFor(() => expect(canvas.scrollLeft).toBeGreaterThan(0));
    expect(canvas.scrollTop).toBeGreaterThan(0);
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
