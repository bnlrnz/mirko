import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  conflicts,
  detail,
  lineage,
  meeting,
  notifications,
  settings,
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
  const mock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/meeting") return json(meeting);
      if (url === "/api/settings" && method === "GET") return json(settings);
      if (url === "/api/settings" && method === "PUT") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return json({
          ...settings,
          source: { ...settings.source, host: body.host },
          lazy_drafts: body.lazy_drafts,
        });
      }
      if (url.startsWith("/api/import/excel")) {
        return json({
          status: "ingested",
          path: "new.xlsx",
          row_count: 3,
          edge_count: 1,
          issue_count: 0,
        });
      }
      if (url.includes("/fetch")) {
        return json({
          tdoc_number: "S3-264202",
          fetched: 0,
          artifacts: [],
          failures: [],
        });
      }
      if (url.startsWith("/api/lineage")) return json(lineage);
      if (url === "/api/notifications") return json(notifications);
      if (url === "/api/conflicts") return json(conflicts);
      if (url.endsWith("/resolve")) {
        return json({ ...conflicts[0], status: "resolved" });
      }
      if (url === "/api/assertions") {
        return json({
          ...conflicts[0].assertions[0],
          id: 4,
          predicate: "revision_of",
          object_ref: "S3-264999",
        });
      }
      if (url === "/api/notes/1" && method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      if (url === "/api/tdocs/S3-264202/track") {
        return json({ tdoc_number: "S3-264202", is_tracked: true });
      }
      if (url === "/api/assertions/7") {
        return json({ ...conflicts[0].assertions[0], id: 7, active: true });
      }
      if (url === "/api/sync/status") return json(sync);
      if (url === "/api/sync") return json({ status: "ok" });
      if (url === "/api/finalize") {
        return json({
          status: "finalized",
          export_path: "exports/mirko-SA3-130-20261016T150000Z.md",
          mirror_links: 1,
          finalized_at: "2026-10-16T15:00:00Z",
        });
      }
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
    },
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

let fetchMock: ReturnType<typeof installFetch>;

describe("App", () => {
  beforeEach(() => {
    fetchMock = installFetch();
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
    expect(screen.getByRole("tab", { name: /Notifications/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Discovery" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "New numbers" })).not.toBeInTheDocument();
    expect(screen.getByText("ftp://10.10.10.10:21/Meetings_3GPP_SYNC/SA3")).toBeInTheDocument();
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

  it("shows notifications and syncs on demand", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /Notifications/ }));
    const list = await screen.findByLabelText("Tracked TDoc updates");
    expect(within(list).getByText("New link to S3-264999")).toBeInTheDocument();
    expect(within(list).getByText("New file for S3-264202")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Track S3-264999" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync Now" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync Now" })).toBeEnabled();
    });
  });

  it("finalizes and links the latest export", async () => {
    render(<App />);
    const button = await screen.findByRole("button", { name: "Finalize" });
    fireEvent.click(button);
    expect(await screen.findByText("latest export")).toBeInTheDocument();
  });

  it("lists conflicts and resolves them", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /Conflicts/ }));
    const list = await screen.findByLabelText("Open conflicts");
    expect(within(list).getByText("decision")).toBeInTheDocument();

    fireEvent.click(within(list).getByRole("button", { name: "Keep mine" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Keep mine" }),
      ).toBeInTheDocument(),
    );
  });

  it("adds a manual lineage link from the detail panel", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");

    fireEvent.change(within(panel).getByLabelText("Link target"), {
      target: { value: "S3-264999" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Add link" }));
    await waitFor(() =>
      expect(within(panel).getByLabelText("Link target")).toHaveValue(""),
    );
  });

  it("deletes a note from the detail panel", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    fireEvent.click(within(panel).getByRole("button", { name: "delete" }));
    await waitFor(() =>
      expect(within(panel).getByRole("button", { name: "delete" })).toBeInTheDocument(),
    );
  });

  it("colors lineage nodes by state and marks tracked nodes with a star", async () => {
    render(<App />);
    const original = await screen.findByRole("button", {
      name: /S3-264202 Original CR revised tracked/,
    });
    expect(original).toHaveClass("state-merged", "tracked");
    expect(within(original).getByText("★")).toBeInTheDocument();
    const revised = screen.getByRole("button", {
      name: /S3-264203 Revised CR agreed/,
    });
    expect(revised).toHaveClass("state-approved");
    expect(revised).not.toHaveClass("tracked");
  });

  it("shows the FTP upload timestamp for artifacts", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    expect(
      within(panel).getByText(/FTP uploaded 2026-10-16T09:55:00/),
    ).toBeInTheDocument();
  });

  it("fetches deferred artifacts when a TDoc is opened", async () => {
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/tdocs/S3-264202") {
        return json({
          ...detail,
          artifacts: detail.artifacts.map((artifact) => ({
            ...artifact,
            blob_hash: null,
            status: "remote",
          })),
        });
      }
      return original ? original(input, init) : json({});
    });

    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDocs and filters");
    fireEvent.click(within(rail).getByText("S3-264202"));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.map((call) => String(call[0])),
      ).toContain("/api/tdocs/S3-264202/fetch?lineage=false"),
    );
  });

  it("edits settings and uploads an allocation workbook", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Meeting settings" });

    fireEvent.change(within(dialog).getByLabelText("Source host"), {
      target: { value: "10.10.10.12" },
    });
    fireEvent.click(
      within(dialog).getByLabelText(/Fetch working drafts only/),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Meeting settings" }),
      ).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const reopened = await screen.findByRole("dialog", {
      name: "Meeting settings",
    });
    const file = new File(["workbook"], "new.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    fireEvent.change(within(reopened).getByLabelText("Excel workbook"), {
      target: { files: [file] },
    });
    expect(await within(reopened).findByText(/ingested: 3 rows/)).toBeInTheDocument();
  });
});
