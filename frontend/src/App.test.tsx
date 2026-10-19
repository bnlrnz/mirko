import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  detail,
  discovery,
  lineage,
  meeting,
  sync,
  tdocs,
  timeline,
} from "./test/fixtures";

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch() {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/meeting") return json(meeting);
    if (url.startsWith("/api/lineage")) return json(lineage);
    if (url === "/api/discovery") return json(discovery);
    if (url === "/api/sync/status") return json(sync);
    if (url === "/api/sync") return json({ status: "ok" });
    if (url === "/api/tdocs?state=agreed") return json([tdocs[1]]);
    if (url === "/api/tdocs") return json(tdocs);
    if (url === "/api/tdocs/S3-264203") {
      return json({
        ...detail,
        tdoc_number: "S3-264203",
        title: "Revised CR",
        decision: "agreed",
        is_tracked: false,
      });
    }
    if (url === "/api/tdocs/S3-264203/timeline") return json(timeline);
    if (url === "/api/tdocs/S3-264202") return json(detail);
    if (url === "/api/tdocs/S3-264202/timeline") return json(timeline);
    return json({});
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("App", () => {
  beforeEach(() => {
    installFetch();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the three-pane shell and loads data", async () => {
    render(<App />);

    expect(await screen.findByText("SA3#130 Prague")).toBeInTheDocument();
    const rail = screen.getByLabelText("Tracked TDocs and filters");
    expect(within(rail).getByText("S3-264202")).toBeInTheDocument();
    expect(screen.getByLabelText("TDoc detail")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Lineage" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Timeline" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Discovery" })).toBeInTheDocument();
    expect(screen.getByText("ftp://10.10.10.10:21/ftp/SA/SA3")).toBeInTheDocument();
  });

  it("selects a TDoc and shows its detail and timeline", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.click(within(rail).getByText("S3-264203"));

    const panel = await screen.findByLabelText("Detail for S3-264203");
    expect(within(panel).getByText("Revised CR")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /Track/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    expect(
      (await screen.findAllByText("[SA3#130][S3-264202] CR on QUIC")).length,
    ).toBeGreaterThan(0);
  });

  it("applies state filters through the API", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.change(screen.getByLabelText("State filter"), {
      target: { value: "agreed" },
    });

    await waitFor(() => {
      expect(within(rail).queryByText("S3-264202")).not.toBeInTheDocument();
    });
    expect(within(rail).getByText("S3-264203")).toBeInTheDocument();
  });

  it("shows discovery items and syncs on demand", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /Discovery/ }));
    expect(await screen.findByText("S3-263700 → S3-264999")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync Now" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync Now" })).toBeEnabled();
    });
  });
});
