import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");

describe("isolated browser test environments", () => {
  it.each(["playwright.ui.config.ts", "playwright.jev.config.ts"])(
    "%s selects the UI extension test environment explicitly",
    (configName) => {
      const config = readFileSync(path.join(REPO_ROOT, configName), "utf8");

      // APP_ENV controls the host RAG application. The mounted UI extension has
      // its own settings object and deliberately reads CMUI_ENV instead. Both must
      // be set so a production-built deterministic browser suite does not inherit
      // the development request-rate ceiling and fail only after enough journeys.
      expect(config).toContain('APP_ENV: "test"');
      expect(config).toContain('CMUI_ENV: "test"');
    },
  );
});
