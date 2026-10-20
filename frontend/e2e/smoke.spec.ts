import { expect, test } from "@playwright/test";

import {
  conflicts,
  detail,
  lineage,
  meeting,
  notifications,
  sync,
  tdocs,
  timeline,
} from "../src/test/fixtures";

test("three-pane navigation, selection sync, and conflict resolution", async ({
  page,
}) => {
  let resolved = 0;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const json = (data: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });

    if (path === "/api/meeting") return json(meeting);
    if (path === "/api/lineage") return json(lineage);
    if (path === "/api/notifications") return json(notifications);
    if (path === "/api/conflicts") return json(conflicts);
    if (path === "/api/sync/status") return json(sync);
    if (path === "/api/sync") return json({ status: "ok" });
    if (path === "/api/finalize") {
      return json({
        status: "finalized",
        export_path: "exports/mirko-SA3-130-20261016T150000Z.md",
        mirror_links: 1,
        finalized_at: "2026-10-16T15:00:00Z",
      });
    }
    if (path.endsWith("/resolve")) {
      resolved += 1;
      return json({ ...conflicts[0], status: "resolved" });
    }
    if (path === "/api/tdocs") return json(tdocs);
    if (path === "/api/tdocs/S3-264202") return json(detail);
    if (path === "/api/tdocs/S3-264202/timeline") return json(timeline);
    if (path === "/api/tdocs/S3-264203") {
      return json({
        ...detail,
        tdoc_number: "S3-264203",
        title: "Revised CR",
        decision: "agreed",
        is_tracked: false,
      });
    }
    if (path === "/api/tdocs/S3-264203/timeline") return json(timeline);
    if (path === "/api/tdocs/S3-264202/track") {
      return json({ tdoc_number: "S3-264202", is_tracked: method === "POST" });
    }
    return json({});
  });

  await page.goto("/");
  await expect(page.getByText("SA3#130 Prague")).toBeVisible();

  const rail = page.getByLabel("Tracked TDocs and filters");
  await expect(rail.getByText("S3-264202")).toBeVisible();
  await rail.getByText("S3-264203").click();

  const detailPanel = page.getByLabel("Detail for S3-264203");
  await expect(detailPanel.getByText("Revised CR")).toBeVisible();
  await expect(detailPanel.getByRole("button", { name: /Track/ })).toBeVisible();

  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(
    page.getByText("[SA3#130][S3-264202] CR on QUIC").first(),
  ).toBeVisible();

  await page.getByRole("tab", { name: /Conflicts/ }).click();
  const conflictList = page.getByLabel("Open conflicts");
  await expect(conflictList.getByText("decision")).toBeVisible();
  await conflictList.getByRole("button", { name: "Keep mine" }).click();
  expect(resolved).toBe(1);

  await page.getByRole("tab", { name: /Notifications/ }).click();
  await expect(page.getByText("New link to S3-264999")).toBeVisible();
});
