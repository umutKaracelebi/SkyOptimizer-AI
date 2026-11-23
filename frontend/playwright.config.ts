import { defineConfig, devices } from "@playwright/test";

/**
 * SkyOptimizer AI — E2E smoke testleri.
 *
 * Testler gerçek ağa çıkmaz: /api/* istekleri e2e/fixtures içindeki
 * kayıtlı yanıtlarla karşılanır. Böylece OpenSky kotası, GFS gecikmesi
 * veya hava durumu servisi kesintisi testleri kırmaz.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "npm run dev -- --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
