import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { LineageNode } from "./types";
import {
  conflicts,
  detail,
  draft,
  lineage,
  meeting,
  notifications,
  settings,
  sync,
  tdocs,
  timeline,
  userActions,
} from "./test/fixtures";

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const seenNotificationRefs = new Set<string>();

function installFetch() {
  let nodeHidden = false;
  const mock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/meeting") return json(meeting);
      if (url === "/api/settings" && method === "GET") return json(settings);
      if (url === "/api/lineage-views" && method === "GET") {
        return json({ views: [], active_id: null });
      }
      if (url === "/api/lineage-views" && method === "PUT") {
        return json(JSON.parse(String(init?.body ?? "{}")));
      }
      if (url === "/api/status" && method === "PUT") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return json(body);
      }
      if (url === "/api/hidden" && method === "PUT") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        nodeHidden = Boolean(body.hidden);
        return json({
          target_kind: body.target_kind,
          target_ref: body.target_ref,
          hidden: nodeHidden,
        });
      }
      if (url === "/api/settings" && method === "PUT") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return json({
          ...settings,
          source: { ...settings.source, host: body.host },
          mail: body.mail,
          lazy_drafts: body.lazy_drafts,
          auto_sync: body.auto_sync,
          meeting_interval_s: body.meeting_interval_s,
          idle_interval_s: body.idle_interval_s,
          bar_color: body.bar_color,
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
      if (url === "/api/notifications") {
        return json(
          notifications.map((item) => ({
            ...item,
            seen: seenNotificationRefs.has(item.ref),
          })),
        );
      }
      if (url === "/api/notifications/seen" && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        const refs = Array.isArray(body.refs) ? body.refs : [];
        for (const ref of refs) {
          if (typeof ref === "string") {
            seenNotificationRefs.add(ref);
          }
        }
        return json({ marked: refs.length });
      }
      if (url === "/api/log") return json(userActions);
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
      if (url.endsWith("/track")) {
        return json({
          tdoc_number: "S3-264202",
          is_tracked: method === "POST",
        });
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
      if (url === "/api/tdocs?tracked=true") {
        return json(tdocs.filter((item) => item.is_tracked));
      }
      if (url === "/api/tdocs") return json(tdocs);
      if (url === "/api/drafts/1") return json(draft);
      if (url === "/api/tdocs/S3-264203") {
        return json({
          ...detail,
          is_hidden: nodeHidden,
          tdoc_number: "S3-264203",
          title: "Revised CR",
          decision: "agreed",
          is_tracked: false,
        });
      }
      if (url === "/api/tdocs/S3-264203/timeline") return json(timeline);
      if (url === "/api/tdocs/S3-264202") {
        return json({ ...detail, is_hidden: nodeHidden });
      }
      if (url === "/api/tdocs/S3-264202/timeline") return json(timeline);
      if (url === "/api/mail/1") {
        return json({ ...detail.emails[0], body: "Please review." });
      }
      return json({});
    },
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

let fetchMock: ReturnType<typeof installFetch>;

describe("App", () => {
  beforeEach(() => {
    seenNotificationRefs.clear();
    fetchMock = installFetch();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the three-pane shell and loads data", async () => {
    render(<App />);

    expect(await screen.findByText("SA3#130 Prague")).toBeInTheDocument();
    const rail = screen.getByLabelText("Tracked TDoc favourites");
    expect(within(rail).getByText("S3-264202")).toBeInTheDocument();
    expect(within(rail).queryByText("S3-264203")).not.toBeInTheDocument();
    expect(
      within(rail).getByTitle(/New file for S3-264202/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Include Drafts")).toBeChecked();
    expect(screen.getByLabelText("TDoc detail")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Lineage" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Timeline" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Notifications/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Log/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Discovery" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "New numbers" })).not.toBeInTheDocument();
    expect(screen.getByText("ftp://10.10.10.10:21/Meetings_3GPP_SYNC/SA3")).toBeInTheDocument();
  });

  it("selects a TDoc and shows its detail and timeline", async () => {
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /S3-264203 Revised CR agreed/ }),
    );

    const panel = await screen.findByLabelText("Detail for S3-264203");
    expect(within(panel).getByText("Revised CR")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /Track/ })).toBeInTheDocument();
    expect(
      within(panel).getByRole("link", { name: "S3-264203.zip" }),
    ).toHaveAttribute(
      "href",
      "https://10.10.10.10/ftp/Meetings_3GPP_SYNC/SA3/Docs/S3-264203.zip",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    expect(
      (await screen.findAllByText("[SA3#130][S3-264202] CR on QUIC")).length,
    ).toBeGreaterThan(0);
  });

  it("opens the full body of a linked mail", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    fireEvent.click(
      within(panel).getByRole("button", {
        name: /Open mail: .* CR on QUIC/,
      }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: /Mail: .* CR on QUIC/,
    });
    expect(await within(dialog).findByText("Please review.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("focuses the lineage when a favourite is double-clicked", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.doubleClick(within(rail).getByText("S3-264202"));

    const canvas = screen.getByTestId("lineage-scroll");
    await waitFor(() => expect(canvas.scrollLeft).toBeGreaterThan(0));
  });

  it("filters lineage nodes by category without changing favourites", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    const state = screen.getByRole("group", { name: "State filter" });
    fireEvent.click(
      within(state).getByRole("checkbox", { name: "agreed" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("button", {
          name: /S3-264202 Original CR revised/,
        }),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /S3-264203 Revised CR agreed/ }),
    ).toBeInTheDocument();
    expect(within(rail).getByText("S3-264202")).toBeInTheDocument();
    expect(within(rail).queryByText("S3-264203")).not.toBeInTheDocument();
  });

  it("shows the user action log", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /Log/ }));
    const list = await screen.findByLabelText("User action log");
    expect(within(list).getByText("note created")).toBeInTheDocument();
    expect(within(list).getByText("Support this CR.")).toBeInTheDocument();
    fireEvent.click(
      within(list).getAllByRole("button", { name: "S3-264202" })[0],
    );
    expect(
      await screen.findByLabelText("Detail for S3-264202"),
    ).toBeInTheDocument();
  });

  it("hides drafts in the lineage without hiding them from details", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    expect(
      within(panel).getByRole("link", { name: "draft S3-264202-r1.docx" }),
    ).toBeInTheDocument();

    expect(
      fetchMock.mock.calls.map((call) => String(call[0])),
    ).toContain(
      "/api/lineage?tracked=false&include_inactive=false&include_drafts=true",
    );
    fireEvent.click(screen.getByLabelText("Include Drafts"));
    expect(screen.getByLabelText("Include Drafts")).not.toBeChecked();
    expect(
      within(panel).getByRole("link", { name: "draft S3-264202-r1.docx" }),
    ).toBeInTheDocument();
  });

  it("keeps separate filters for each lineage tab", async () => {
    render(<App />);
    await screen.findByRole("tab", { name: "Lineage" });
    const state = () =>
      within(screen.getByRole("group", { name: "State filter" }));
    fireEvent.click(state().getByRole("checkbox", { name: "agreed" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", {
          name: /S3-264202 Original CR revised/,
        }),
      ).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "New lineage tab" }));
    const second = await screen.findByRole("tab", { name: "Lineage 2" });
    expect(second).toHaveAttribute("aria-selected", "true");
    expect(state().getByRole("checkbox", { name: "agreed" })).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: /S3-264202 Original CR revised/ }),
    ).toBeInTheDocument();

    fireEvent.click(state().getByRole("checkbox", { name: "revised" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", {
          name: /S3-264203 Revised CR agreed/,
        }),
      ).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: "Lineage" }));
    expect(state().getByRole("checkbox", { name: "agreed" })).toBeChecked();
    expect(state().getByRole("checkbox", { name: "revised" })).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: /S3-264203 Revised CR agreed/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /S3-264202 Original CR revised/,
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Lineage 2" }));
    expect(state().getByRole("checkbox", { name: "revised" })).toBeChecked();
    expect(state().getByRole("checkbox", { name: "agreed" })).not.toBeChecked();
  });

  it("restores and persists lineage views in the meeting config", async () => {
    const original = fetchMock.getMockImplementation();
    const stored = {
      views: [
        {
          id: "lineage-7",
          label: "Agenda 5.3.1.3",
          filters: {
            agenda: [],
            type: [],
            state: ["agreed"],
            source: [],
            tracked: false,
            include_ephemeral: true,
            hide_withdrawn: false,
            hide_not_treated: false,
            hide_unknown: false,
            show_hidden: false,
          },
        },
      ],
      active_id: "lineage-7",
    };
    let savedBody: unknown = null;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/lineage-views" && method === "GET") {
        return json(stored);
      }
      if (url === "/api/lineage-views" && method === "PUT") {
        savedBody = JSON.parse(String(init?.body ?? "{}"));
        return json(savedBody);
      }
      return original!(input, init);
    });

    render(<App />);
    const restored = await screen.findByRole("tab", {
      name: "Agenda 5.3.1.3",
    });
    expect(restored).toHaveAttribute("aria-selected", "true");
    const state = () =>
      within(screen.getByRole("group", { name: "State filter" }));
    expect(state().getByRole("checkbox", { name: "agreed" })).toBeChecked();
    expect(
      screen.queryByRole("button", {
        name: /S3-264202 Original CR revised/,
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(state().getByRole("checkbox", { name: "agreed" }));
    fireEvent.click(state().getByRole("checkbox", { name: "revised" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Rename Agenda 5.3.1.3" }),
    );
    const rename = screen.getByLabelText("Rename Agenda 5.3.1.3");
    fireEvent.change(rename, { target: { value: "Agenda view" } });
    fireEvent.keyDown(rename, { key: "Enter" });

    await waitFor(() => {
      expect(savedBody).toMatchObject({
        active_id: "lineage-7",
        views: [
          {
            id: "lineage-7",
            label: "Agenda view",
            filters: {
              state: ["revised"],
              include_ephemeral: true,
            },
          },
        ],
      });
    });
  });

  it("renames and closes lineage tabs", async () => {
    render(<App />);
    await screen.findByRole("tab", { name: "Lineage" });
    fireEvent.click(screen.getByRole("button", { name: "New lineage tab" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Rename Lineage 2" }),
    );
    const rename = screen.getByLabelText("Rename Lineage 2");
    fireEvent.change(rename, { target: { value: "Agenda 5.3.1.3" } });
    fireEvent.keyDown(rename, { key: "Enter" });

    const renamed = await screen.findByRole("tab", {
      name: "Agenda 5.3.1.3",
    });
    expect(renamed).toHaveAttribute("aria-selected", "true");
    fireEvent.click(
      screen.getByRole("button", { name: "Close Agenda 5.3.1.3" }),
    );
    expect(
      screen.queryByRole("tab", { name: "Agenda 5.3.1.3" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Lineage" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("tracks a TDoc from the left rail star", async () => {
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Untrack S3-264202" }),
    );
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input) === "/api/tdocs/S3-264202/track" &&
          init?.method === "DELETE",
      );
      expect(call).toBeTruthy();
    });
  });

  it("toggles tracking by double-clicking a lineage node", async () => {
    render(<App />);
    fireEvent.doubleClick(
      await screen.findByRole("button", { name: /S3-264203 Revised CR agreed/ }),
    );
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input) === "/api/tdocs/S3-264203/track" &&
          init?.method === "POST",
      );
      expect(call).toBeTruthy();
    });
  });

  it("shows notifications and syncs on demand", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /Notifications/ }));
    const list = await screen.findByLabelText("Tracked TDoc updates");
    expect(within(list).getByText("New link to S3-264999")).toBeInTheDocument();
    expect(within(list).getByText("New file for S3-264202")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Track S3-264999" })).toBeInTheDocument();
    expect(within(list).getAllByText("Original CR")).toHaveLength(2);
    expect(
      within(list).getByText("draft S3-264202-r2.docx"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync Now" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync Now" })).toBeEnabled();
    });
  });

  it("keeps notifications and permanently clears unread state when seen", async () => {
    const { unmount } = render(<App />);
    const tab = await screen.findByRole("tab", { name: /Notifications/ });
    expect(within(tab).getByText("3")).toBeInTheDocument();
    fireEvent.click(tab);
    const list = await screen.findByLabelText("Tracked TDoc updates");
    const first = within(list)
      .getByText("New link to S3-264999")
      .closest("li");
    const second = within(list)
      .getByText("New file for S3-264202")
      .closest("li");
    expect(first).toHaveClass("notification-unread");
    expect(second).toHaveClass("notification-unread");

    fireEvent.mouseEnter(first as HTMLElement);
    await waitFor(() => {
      expect(within(tab).getByText("2")).toBeInTheDocument();
    });
    expect(first).not.toHaveClass("notification-unread");

    fireEvent.click(second as HTMLElement);
    await waitFor(() => {
      expect(within(tab).getByText("1")).toBeInTheDocument();
    });

    const rail = screen.getByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    await waitFor(() => {
      expect(within(tab).queryByText("1")).not.toBeInTheDocument();
    });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === "/api/notifications/seen" &&
          init?.method === "POST",
      ),
    ).toBe(true);

    unmount();
    render(<App />);
    const restoredTab = await screen.findByRole("tab", {
      name: /Notifications/,
    });
    expect(within(restoredTab).queryByText("3")).not.toBeInTheDocument();
    expect(within(restoredTab).queryByText("1")).not.toBeInTheDocument();
    fireEvent.click(restoredTab);
    const restoredList = await screen.findByLabelText("Tracked TDoc updates");
    expect(within(restoredList).getAllByRole("listitem")).toHaveLength(3);
    for (const item of within(restoredList).getAllByRole("listitem")) {
      expect(item).not.toHaveClass("notification-unread");
    }
    const restoredRail = screen.getByLabelText("Tracked TDoc favourites");
    expect(
      within(restoredRail).queryByTitle(/New file for S3-264202/),
    ).not.toBeInTheDocument();
  });

  it("highlights and notifies when a new artifact arrives", async () => {
    const sent = vi.fn();
    class FakeNotification {
      static permission: NotificationPermission = "granted";
      static requestPermission = vi.fn(async () => "granted" as const);
      onclick: (() => void) | null = null;
      close = vi.fn();
      constructor(title: string, options?: NotificationOptions) {
        sent(title, options);
      }
    }
    vi.stubGlobal("Notification", FakeNotification);

    render(<App />);
    expect(await screen.findByText("SA3#130 Prague")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.map((call) => String(call[0])),
      ).toContain("/api/notifications"),
    );

    const original = fetchMock.getMockImplementation();
    const arriving = {
      ...notifications[1],
      ref: "Inbox/Drafts/draft S3-264202-r3.docx",
      detail: "draft S3-264202-r3.docx · FTP 2026-10-16T13:30:00",
      created_at: "2026-10-16T13:30:00.000000Z",
    };
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/notifications") {
        return json([arriving, ...notifications]);
      }
      return original ? original(input, init) : json({});
    });

    fireEvent.click(screen.getByRole("button", { name: "Sync Now" }));
    await waitFor(() => {
      expect(sent).toHaveBeenCalledWith(
        "New file for S3-264202",
        expect.objectContaining({
          body: "draft S3-264202-r3.docx · FTP 2026-10-16T13:30:00",
        }),
      );
    });
    expect(
      await screen.findByRole("button", {
        name: /S3-264202 Original CR revised tracked new file/,
      }),
    ).toHaveClass("new-file");
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
    const choices = within(list).getByLabelText(
      "Competing nodes for S3-264202",
    );
    expect(within(choices).getAllByRole("button")).toHaveLength(2);
    expect(within(choices).getByText("html")).toBeInTheDocument();
    expect(within(choices).getByText("user")).toBeInTheDocument();
    expect(
      within(choices).getByRole("button", {
        name: "Open S3-264202 from user",
      }),
    ).toHaveTextContent("agreed");
    expect(
      within(choices).getByRole("button", {
        name: "Open S3-264202 from html",
      }),
    ).toHaveTextContent("revised");

    fireEvent.click(
      within(choices).getByRole("button", { name: "Open S3-264202 from user" }),
    );
    expect(
      await screen.findByLabelText("Detail for S3-264202"),
    ).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: "Keep mine" }));
    await waitFor(() =>
      expect(
        within(list).getByRole("button", { name: "Keep mine" }),
      ).toBeInTheDocument(),
    );
  });

  it("adds a manual lineage link from the detail panel", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");

    expect(
      within(panel).getByRole("option", { name: "revised to" }),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByRole("option", { name: "based on" }),
    ).not.toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText("Link target"), {
      target: { value: "4999" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Add link" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input) === "/api/assertions" && init?.method === "POST",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        subject_ref: "S3-264202",
        predicate: "revision_of",
        object_kind: "tdoc",
        object_ref: "S3-264999",
      });
    });
    expect(within(panel).getByLabelText("Link target")).toHaveValue("");
  });

  it("deletes a note from the detail panel", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    fireEvent.click(within(panel).getByRole("button", { name: "delete" }));
    await waitFor(() =>
      expect(within(panel).getByRole("button", { name: "delete" })).toBeInTheDocument(),
    );
  });

  it("hides a node from lineage in the detail panel", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    fireEvent.click(within(panel).getByRole("button", { name: "Hide node" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input) === "/api/hidden" && init?.method === "PUT",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        target_kind: "tdoc",
        target_ref: "S3-264202",
        hidden: true,
      });
    });
    expect(
      await within(panel).findByRole("button", { name: "Show node" }),
    ).toBeInTheDocument();
  });

  it("sets a TDoc status separately from its notes", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    expect(
      within(panel).getByRole("button", { name: "Action" }),
    ).toHaveTextContent("Support");
    expect(within(panel).queryByLabelText("Position tag")).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Action" }));
    fireEvent.click(within(panel).getByRole("option", { name: "Object" }));
    await waitFor(() => {
      const statusCall = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]) === "/api/status" &&
          call[1]?.method === "PUT",
      );
      expect(JSON.parse(String(statusCall?.[1]?.body))).toEqual({
        target_kind: "tdoc",
        target_ref: "S3-264202",
        status: "Object",
      });
    });
  });

  it("colors lineage nodes by state and marks tracked nodes with a star", async () => {
    render(<App />);
    const original = await screen.findByRole("button", {
      name: /S3-264202 Original CR revised tracked/,
    });
    expect(original).toHaveClass("state-merged", "tracked");
    expect(within(original).getByText("★")).toBeInTheDocument();
    expect(within(original).getByTestId("status-badge-S3-264202")).toBeInTheDocument();
    const revised = screen.getByRole("button", {
      name: /S3-264203 Revised CR agreed/,
    });
    expect(revised).toHaveClass("state-approved");
    expect(revised).not.toHaveClass("tracked");
  });

  it("shows the FTP upload timestamp for artifacts", async () => {
    render(<App />);
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
    fireEvent.click(within(rail).getByText("S3-264202"));
    const panel = await screen.findByLabelText("Detail for S3-264202");
    expect(
      within(panel).getByText(/FTP uploaded 2026-10-16T09:55:00/),
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("link", {
        name: "draft S3-264202-r1.docx",
      }),
    ).toHaveAttribute(
      "href",
      "https://10.10.10.10/ftp/Meetings_3GPP_SYNC/SA3/Inbox/Drafts/draft%20S3-264202-r1.docx",
    );
  });

  it("opens a draft detail with its own notes", async () => {
    const original = fetchMock.getMockImplementation();
    const draftNode: LineageNode = {
      ...lineage.nodes[0],
      tdoc_number: "draft:1",
      title: "draft S3-264202-r1.docx",
      decision: "present",
      node_kind: "draft",
      attached_to: "S3-264202",
      artifact_id: 1,
      status: "present",
      notes_count: 1,
      node_status: "Clarify",
    };
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).startsWith("/api/lineage")) {
        return json({
          ...lineage,
          nodes: [...lineage.nodes, draftNode],
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
        });
      }
      return original ? original(input, init) : json({});
    });

    render(<App />);
    const draftButton = await screen.findByRole("button", {
      name: /draft draft S3-264202-r1.docx for S3-264202 present/,
    });
    expect(
      within(draftButton).getByTestId("status-badge-draft:1"),
    ).toBeInTheDocument();
    fireEvent.click(draftButton);
    const panel = await screen.findByLabelText(
      "Detail for draft draft S3-264202-r1.docx",
    );
    expect(
      within(panel).getByRole("link", { name: "draft S3-264202-r1.docx" }),
    ).toHaveAttribute(
      "href",
      "https://10.10.10.10/ftp/Meetings_3GPP_SYNC/SA3/Inbox/Drafts/draft%20S3-264202-r1.docx",
    );
    expect(
      within(panel).queryByRole("link", { name: /S3-264202\.zip/ }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByRole("link", { name: /S3-264203\.zip/ }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Action" }),
    ).toHaveTextContent("Clarify");
    fireEvent.click(within(panel).getByRole("button", { name: "Action" }));
    fireEvent.click(within(panel).getByRole("option", { name: "Object" }));
    await waitFor(() => {
      const statusCall = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]) === "/api/status" &&
          call[1]?.method === "PUT",
      );
      expect(JSON.parse(String(statusCall?.[1]?.body))).toEqual({
        target_kind: "draft",
        target_ref: "1",
        status: "Object",
      });
    });
    fireEvent.change(within(panel).getByLabelText("New note"), {
      target: { value: "Draft needs a title fix." },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Add note" }));
    await waitFor(() => {
      const noteCall = fetchMock.mock.calls.find(
        (call) =>
          String(call[0]) === "/api/notes" &&
          call[1]?.method === "POST",
      );
      expect(JSON.parse(String(noteCall?.[1]?.body))).toEqual({
        target_kind: "draft",
        target_ref: "1",
        body: "Draft needs a title fix.",
      });
    });
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
    const rail = await screen.findByLabelText("Tracked TDoc favourites");
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

    expect(
      within(dialog).queryByRole("button", { name: "Close" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Mail mbox path")).toHaveValue(
      "/home/ben/mail/sa3-130.mbox",
    );
    expect(within(dialog).getByLabelText("Bar color")).toHaveValue("#ffffff");
    fireEvent.change(within(dialog).getByLabelText("Bar color"), {
      target: { value: "#2457c5" },
    });
    fireEvent.change(within(dialog).getByLabelText("Mail source kind"), {
      target: { value: "eml" },
    });
    fireEvent.change(within(dialog).getByLabelText("Mail EML path"), {
      target: { value: "/tmp/sa3-130-mail" },
    });
    fireEvent.change(within(dialog).getByLabelText("Source host"), {
      target: { value: "10.10.10.12" },
    });
    fireEvent.click(
      within(dialog).getByLabelText(/Fetch working drafts only/),
    );
    fireEvent.click(
      within(dialog).getByLabelText(/Check for FTP updates automatically/),
    );
    fireEvent.change(within(dialog).getByLabelText("Meeting update interval"), {
      target: { value: "30" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Meeting settings" }),
      ).not.toBeInTheDocument();
    });
    const saveCall = fetchMock.mock.calls.find(
      (call) =>
        String(call[0]) === "/api/settings" && call[1]?.method === "PUT",
    );
    expect(JSON.parse(String(saveCall?.[1]?.body))).toMatchObject({
      auto_sync: false,
      meeting_interval_s: 30,
      idle_interval_s: 600,
      lazy_drafts: false,
      bar_color: "#2457c5",
      mail: {
        kind: "eml",
        path: null,
        eml_dir: "/tmp/sa3-130-mail",
      },
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
