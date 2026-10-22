import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.P2S_BASE_URL ?? "http://127.0.0.1:8765",
    headless: true,
    acceptDownloads: true,
  },
  webServer: process.env.P2S_BASE_URL
    ? undefined
    : {
        command: ".envs/coinstall/bin/python -m p2s.cli serve --port 8765 --data-dir .tmp/e2e-data",
        cwd: "../..",
        url: "http://127.0.0.1:8765/api/v1/health",
        timeout: 90_000,
        reuseExistingServer: true,
        env: { CUDA_VISIBLE_DEVICES: process.env.CUDA_VISIBLE_DEVICES ?? "0" },
      },
});
