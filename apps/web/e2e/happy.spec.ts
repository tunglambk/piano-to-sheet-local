import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = path.resolve(here, "../../../data/fixtures/smoke/fast_passage.wav");

test("upload, transcribe, view the sheet, play and export the PDF", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Jobs|Các job/ })).toBeVisible();

  await page.getByRole("link", { name: /New job|Job mới/ }).first().click();
  await page.locator('input[type="file"]').setInputFiles(fixture);
  await page.getByLabel(/Preset/).selectOption("fast");
  await page.getByRole("button", { name: /Start transcription|Bắt đầu phiên âm/ }).click();

  // The upload starts immediately; the processing screen takes over.
  await expect(page.getByRole("heading", { name: /Processing|Đang xử lý/ })).toBeVisible({ timeout: 30_000 });

  // When the job succeeds the app navigates to the workspace.
  await expect(page.locator(".sheet svg").first()).toBeVisible({ timeout: 200_000 });
  await expect(page.locator(".sheet svg").first()).toHaveAttribute("viewBox", /0 0/);

  const audio = page.locator("audio");
  await expect(audio).toHaveAttribute("src", /artifacts\/audio/);

  const pdfHref = await page.locator('.export a[href*="artifacts/pdf"]').getAttribute("href");
  expect(pdfHref).toContain("/api/v1/jobs/");
  const response = await page.request.get(pdfHref as string);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect((await response.body()).subarray(0, 5).toString()).toBe("%PDF-");
});
