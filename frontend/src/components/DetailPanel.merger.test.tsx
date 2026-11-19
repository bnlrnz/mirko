import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { detail } from "../test/fixtures";
import type { MergeSource } from "../types";
import { DetailPanel } from "./DetailPanel";

function renderPanel(mergedFrom: MergeSource[]) {
  const onSelect = vi.fn();
  render(
    <DetailPanel
      detail={{ ...detail, merged_from: mergedFrom }}
      draft={null}
      endpoint={null}
      conflicts={[]}
      onTrack={vi.fn()}
      onAddNote={vi.fn()}
      onSetStatus={vi.fn()}
      onSetHidden={vi.fn()}
      onDeleteNote={vi.fn()}
      onAddAssertion={vi.fn()}
      onResolveConflict={vi.fn()}
      onSelect={onSelect}
      onFetch={vi.fn()}
      fetching={false}
      seriesPrefix="S3-26"
      highlightArtifactId={null}
      onClearArtifactHighlight={vi.fn()}
    />,
  );
  return onSelect;
}

describe("DetailPanel merge sources", () => {
  it("lists the nodes a merger was built from", () => {
    const onSelect = renderPanel([
      { tdoc_number: "S3-264202", title: "Original CR" },
      { tdoc_number: "S3-264205", title: null },
    ]);

    expect(
      screen.getByRole("heading", { name: "Merger of" }),
    ).toBeInTheDocument();
    const section = screen
      .getByRole("heading", { name: "Merger of" })
      .closest("section") as HTMLElement;
    expect(within(section).getByText("Original CR")).toBeInTheDocument();
    expect(within(section).getByText("S3-264205")).toBeInTheDocument();
    expect(within(section).getByText("—")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "S3-264202" }));
    expect(onSelect).toHaveBeenCalledWith("S3-264202");
    fireEvent.click(screen.getByRole("button", { name: "S3-264205" }));
    expect(onSelect).toHaveBeenCalledWith("S3-264205");
  });

  it("omits the section for nodes that are not mergers", () => {
    renderPanel([]);
    expect(
      screen.queryByRole("heading", { name: "Merger of" }),
    ).not.toBeInTheDocument();
  });
});
