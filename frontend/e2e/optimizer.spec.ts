import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";

/**
 * Smoke testleri: gerçek backend/OpenSky yerine kayıtlı API yanıtları.
 * Amaç UI'ın uçtan uca akışını (optimizasyon → sonuç → trafik → doğrulama)
 * deterministik biçimde doğrulamak.
 */

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "*",
};

function fixture(name: string): unknown {
  const url = new URL(`./fixtures/${name}`, import.meta.url);
  return JSON.parse(fs.readFileSync(url, "utf8"));
}

const ROUTE =
  "/optimizer?origin=LTFM&destination=EGLL&aircraft=B738&ci=30" +
  "&fuel=40&time=35&co2=25&auto=1";

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS });
    }

    let body: unknown;
    if (pathname === "/api/config") body = fixture("config.json");
    else if (pathname === "/api/airports/LTFM") body = fixture("airport-ltfm.json");
    else if (pathname === "/api/airports/EGLL") body = fixture("airport-egll.json");
    else if (pathname === "/api/optimize") body = fixture("optimize.json");
    else if (pathname === "/api/flights/live") body = fixture("live.json");
    else if (pathname.startsWith("/api/aircraft/")) body = fixture("aircraft.json");
    else if (pathname === "/api/validate") body = fixture("validate.json");
    else if (pathname === "/api/stats/savings") body = fixture("stats.json");
    else {
      return route.fulfill({
        status: 404,
        headers: CORS,
        contentType: "application/json",
        body: JSON.stringify({ detail: "not mocked" }),
      });
    }

    return route.fulfill({
      status: 200,
      headers: CORS,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  // Harita döşemelerini engelle: test ağa çıkmasın, hızlı kalsın.
  await page.route(/arcgisonline\.com|openstreetmap\.org|basemaps\.cartocdn\.com/, (route) =>
    route.abort()
  );
}

test("rota optimizasyonu sonuçları ve irtifa taraması gösterilir", async ({ page }) => {
  await mockApi(page);
  await page.goto(ROUTE);

  await expect(page.getByText("AĞIRLIKLI MALİYET")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/yakıt tasarrufu/)).toContainText("%1.16");

  // İrtifa katmanı taraması: üç seviye de tabloda olmalı.
  await page.getByText("İRTİFA KATMANI TARAMASI").click();
  await expect(page.getByText("FL300").first()).toBeVisible();
  await expect(page.getByText("FL340").first()).toBeVisible();
  await expect(page.getByText("FL390").first()).toBeVisible();

  // Sunucu taraflı birikim paneli.
  await expect(page.getByText("EKİP ORTAK (SQLite)")).toBeVisible();
});

test("canlı trafik uçak ikonlarıyla çizilir, tıklanınca detay paneli açılır", async ({ page }) => {
  await mockApi(page);
  await page.goto(ROUTE);
  await expect(page.getByText("AĞIRLIKLI MALİYET")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "KAPALI" }).click();

  // "ROTA SAHASI" modu: fixture'daki 12 uçuştan yalnızca 150 NM koridoruna
  // girenler çizilir.
  const markers = page.locator(".aircraft-marker");
  await expect(markers.first()).toBeVisible({ timeout: 10_000 });
  const visible = await markers.count();
  expect(visible).toBeGreaterThan(0);
  expect(visible).toBeLessThanOrEqual(12);
  await expect(markers.first().locator("svg")).toHaveCount(1);

  await markers.first().click();

  // Panel, uçuşun çağrı işaretini ve kimlik bloğunu göstermeli.
  const callsigns = (fixture("live.json") as { flights: { callsign: string }[] })
    .flights.map((f) => f.callsign);
  await expect(page.getByText("UÇAK KİMLİĞİ")).toBeVisible();
  const panelText = await page.locator("body").innerText();
  expect(callsigns.some((c) => panelText.includes(c))).toBe(true);
  await expect(page.getByText("ROTA").first()).toBeVisible();
});

test("gerçek uçuş doğrulaması ADS-B izini modele karşı gösterir", async ({ page }) => {
  await mockApi(page);
  await page.goto(ROUTE);
  await expect(page.getByText("AĞIRLIKLI MALİYET")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "ÇALIŞTIR" }).click();

  await expect(page.getByText("BAW679")).toBeVisible();
  await expect(page.getByText("G-TTNR")).toBeVisible();
  await expect(page.getByText("245 iz noktası")).toBeVisible();
  await expect(page.getByText(/Gerçek uçuş bu modelde daha verimli/)).toBeVisible();
});


test("paylaşım linki ve JSON raporu çalışır", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mockApi(page);
  await page.goto(ROUTE);
  await expect(page.getByText("AĞIRLIKLI MALİYET")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "PAYLAŞ" }).click();
  const shared = await page.evaluate(() => navigator.clipboard.readText());
  expect(shared).toContain("origin=LTFM");
  expect(shared).toContain("destination=EGLL");
  expect(shared).toContain("ci=30");
  expect(shared).toContain("auto=1");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("skyoptimizer-LTFM-EGLL.json");
});
