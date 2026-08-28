import { expect, test } from "@playwright/test";

const robot = {
  id: "robot-sim-1",
  name: "Demo Manipulator",
  model: "OpenRoboOps Simulator",
  adapter_type: "simulator",
  connection_summary: { mode: "simulator" },
  capabilities: ["telemetry", "episode_index", "collection", "sync", "reset_arm"],
  status: {
    battery: { available: true, percent: 78, charging: false, statusText: "Discharging" },
    disk: { total: 2_000_000_000_000, used: 200_000_000_000, free: 1_800_000_000_000 },
    stack: { ready: true },
    collisionProtection: { enabled: true, level: "mid" },
    resetPoses: {
      left: { available: true, source: "simulator" },
      right: { available: false, source: "default" },
    },
    services: { collector: "active", web: "active" },
    recording: false,
    vrActive: false,
    alerts: [],
  },
  online: true,
  last_seen: "2026-08-28T08:00:00Z",
  revision: 4,
  observe_only: false,
  enabled_commands: ["reset_arm"],
  created_at: "2026-08-28T07:00:00Z",
  updated_at: "2026-08-28T08:00:00Z",
};

const episode = {
  id: "episode-1",
  robot_id: robot.id,
  uid: "historical-episode",
  source_path: "/data/record/historical-episode",
  metadata: { create_time: "2026-08-21 09:33:01", task_id: 12775 },
  channels: ["head"],
  file_size: 4_937_339_725,
  duration_seconds: 268,
  aligned: false,
  validation_status: "valid",
  sync_status: "not_synced",
  last_scanned_at: "2026-08-28T07:10:00Z",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      return route.fulfill({ json: { id: "admin-1", username: "admin" } });
    }
    if (url.pathname === "/api/v1/robots") return route.fulfill({ json: [robot] });
    if (url.pathname.endsWith("/episodes")) return route.fulfill({ json: [episode] });
    if (url.pathname === "/api/v1/sync-jobs") return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/collections")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/camera-previews")) return route.fulfill({ json: [] });
    if (url.pathname === "/api/v1/commands") return route.fulfill({ json: [] });
    if (url.pathname === "/api/v1/audit") return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
});

test("keeps left and right reset-pose readiness separate", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Demo Manipulator" })).toBeVisible();
  await expect(page.getByText("Left arm")).toBeVisible();
  await expect(page.getByText("Saved reset pose available")).toBeVisible();
  await expect(page.getByText("Right arm")).toBeVisible();
  await expect(page.getByText("No saved reset pose")).toBeVisible();
});

test("opens the observe-only robot registration flow", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Add robot").click();
  await expect(page.getByRole("heading", { name: "Add a robot" })).toBeVisible();
  await expect(page.getByText("New robots are observe-only.")).toBeVisible();
  await page.getByLabel("Adapter").selectOption("a2d");
  await expect(page.getByLabel("Pinned known_hosts file")).toBeVisible();
  await expect(page.getByLabel("Private key file")).toBeVisible();
});

test("manages and safely confirms deletion from the data page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Data" }).click();
  await page.getByRole("button", { name: "Manage" }).click();

  const manager = page.getByRole("dialog", { name: "Episode details" });
  await expect(manager.getByText("historical-episode", { exact: true })).toBeVisible();
  await expect(manager.locator(".camera-card")).toHaveCount(3);
  await manager.getByRole("button", { name: "Delete data" }).click();
  await expect(manager.getByRole("button", { name: "Permanently delete" })).toBeDisabled();
  await manager.getByLabel("Confirm UID").fill("historical-episode");
  await manager.getByLabel("Administrator password").fill("correct-horse-battery");
  await expect(manager.getByRole("button", { name: "Permanently delete" })).toBeEnabled();
});

test("switches to Chinese and persists the language preference", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Switch language").click();
  await expect(page.getByText("左臂")).toBeVisible();
  await expect(page.getByRole("button", { name: "概览" })).toBeVisible();

  await page.reload();
  await expect(page.getByText("机械臂就绪状态")).toBeVisible();
});

test("keeps all three camera slots when no preview is available", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Collection" }).click();

  const cameraGrid = page.locator(".camera-grid");
  await expect(cameraGrid.locator(".camera-card")).toHaveCount(3);
  await expect(cameraGrid.getByText("Left hand camera")).toBeVisible();
  await expect(cameraGrid.getByText("Head camera")).toBeVisible();
  await expect(cameraGrid.getByText("Right hand camera")).toBeVisible();
  await expect(cameraGrid.getByText("No live frame")).toHaveCount(3);
});

test("shows collection time separately from the latest scan time", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Data" }).click();

  await expect(page.getByText(/Collected.*Aug 21/)).toBeVisible();
  await expect(page.getByText(/Last scanned.*Aug 28/)).toBeVisible();
});

test("keeps camera previews mounted while another section is open", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Collection" }).click();
  const cameraGrid = page.locator(".camera-grid");
  await expect(cameraGrid).toBeVisible();

  await page.getByRole("button", { name: "Overview" }).click();
  await expect(cameraGrid).toBeHidden();
  await expect(cameraGrid).toHaveCount(1);

  await page.getByRole("button", { name: "Collection" }).click();
  await expect(cameraGrid).toBeVisible();
});

test("reviews a failed collection and exposes force stop", async ({ page }) => {
  const failedCollection = {
    id: "collection-failed-1",
    robot_id: robot.id,
    name: "Failed pickup test",
    task_id: 1,
    job_id: 2,
    record_uid: "failed-record-uid",
    planned_duration_seconds: 60,
    status: "failed",
    error: "recorder slot was not released",
    review_status: "pending",
    reviewed_at: null,
    started_at: "2026-08-28T06:53:23Z",
    due_at: "2026-08-28T06:54:23Z",
    stopped_at: "2026-08-28T06:58:46Z",
  };
  await page.route("**/api/v1/robots/*/collections", (route) => route.fulfill({ json: [failedCollection] }));

  await page.goto("/");
  await page.getByRole("button", { name: "Collection" }).click();
  await expect(page.getByRole("button", { name: "Force stop" })).toBeVisible();
  await page.getByRole("button", { name: "Review" }).click();
  const review = page.locator(".collection-review");
  await expect(review.getByRole("heading", { name: "Failed pickup test" })).toBeVisible();
  await expect(review.getByText("failed-record-uid", { exact: true })).toBeVisible();
  await expect(review.getByRole("button", { name: "Keep data" })).toBeVisible();
  await expect(review.getByRole("button", { name: "Delete data" })).toBeVisible();
});
