import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      main: "./src/index.ts",
      wrangler: {
        configPath: "./wrangler.jsonc",
      },
      miniflare: {
        compatibilityDate: "2026-07-29",
        bindings: {
          // CI's GITHUB_REF must not replace the dispatch target in fixtures.
          GITHUB_REF: "main",
          GITHUB_REPOSITORY: "ohxiyu/bmtnews-standalone",
          GITHUB_WORKFLOW: "daily-summary.yml",
          GITHUB_DISPATCH_TOKEN: "test-token",
          RECOVERY_CHECK_TOKEN: "test-check-token",
          PAGES_DEPLOY_HOOK: "https://api.cloudflare.com/client/v4/pages/webhooks/deploy_hooks/test",
        },
      },
    }),
  ],
});
