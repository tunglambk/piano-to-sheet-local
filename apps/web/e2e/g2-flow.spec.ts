import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const listFile = path.resolve(here, "g2-files.json");
const files: { label: string; path: string }[] = existsSync(listFile)
  ? JSON.parse(readFileSync(listFile, "utf8"))
  : [];

test.describe("G2 browser flow", () => {
  test.skip(files.length === 0, "run scripts/make_g2_files.py first");

  for (const file of files) {
    test(`upload → progress → sheet → PDF: ${file.label}`, async ({ page }) => {
      await page.goto("/new");
      await page.locator('input[type="file"]').setInputFiles(file.path);
      await page.getByLabel(/Preset/).selectOption("fast");
      await page.getByRole("button", { name: /Start transcription|Bắt đầu phiên âm/ }).click();

      await expect(page.locator(".sheet svg").first()).toBeVisible({ timeout: 300_000 });
      const pdf = page.locator('.export a[href*="artifacts/pdf"]');
      const href = await pdf.getAttribute("href");
      const response = await page.request.get(href as string);
      expect(response.status()).toBe(200);
      expect((await response.body()).subarray(0, 5).toString()).toBe("%PDF-");
    });
  }
});
