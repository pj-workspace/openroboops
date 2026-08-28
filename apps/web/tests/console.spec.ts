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

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      return route.fulfill({ json: { id: "admin-1", username: "admin" } });
    }
    if (url.pathname === "/api/v1/robots") return route.fulfill({ json: [robot] });
    if (url.pathname.endsWith("/episodes")) return route.fulfill({ json: [] });
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
