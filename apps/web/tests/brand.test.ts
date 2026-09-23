import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { BRAND, brandTitle, brandTitleZh, canvasCallbackUrl, isPreviousOrigin } from "../src/brand";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const WEB_ROOT = path.resolve(HERE, "..");

/**
 * Compatibility identifiers that must keep the old spelling because callers or stored
 * data depend on them (docs/coursejesus/BRAND_REPLACEMENT_MATRIX.md, class B). Anything
 * not matched here is user-visible text and must use the brand source.
 */
const COMPATIBILITY_IDENTIFIERS = /CourseMate(Auth|Math|App|Ui|AuthBridge|Provider)/;
const COMPATIBILITY_LITERALS = ["X-CourseMate-Internal-Token"];

/**
 * Files that still contain the old name as text, each with the reason it is not yet
 * converted. This list is the honest remainder, not a permission: a file that is not
 * listed and contains a bare old-brand string fails the test, so a new page cannot
 * quietly ship the old name.
 */
const NOT_YET_CONVERTED: Record<string, string> = {
  "src/brand.ts": "documents the compatibility identifiers it deliberately keeps",
  "tests/brand.test.ts": "defines and asserts this scan rule, so it necessarily spells the old name",
};

function sourceFiles(): string[] {
  const roots = [path.join(WEB_ROOT, "src"), path.join(REPO_ROOT, "services", "agent-api", "src")];
  const files: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const full = path.join(directory, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (/\.(ts|tsx|js|jsx)$/.test(entry)) files.push(full);
    }
  };
  for (const root of roots) walk(root);
  for (const document of ["index.html", "ui.html"]) files.push(path.join(WEB_ROOT, document));
  return files;
}

function visibleBrandText(file: string, text: string): string[] {
  const found: string[] = [];
  text.split("\n").forEach((line, index) => {
    // A line that carries an allowed compatibility literal keeps it; the check is per
    // line because the literal is written with a prefix (`X-CourseMate-Internal-Token`).
    if (COMPATIBILITY_LITERALS.some((literal) => line.includes(literal))) return;
    let cursor = 0;
    for (;;) {
      const at = line.indexOf("CourseMate", cursor);
      if (at === -1) break;
      cursor = at + 1;
      const tail = line.slice(at);
      if (COMPATIBILITY_IDENTIFIERS.test(tail)) continue;
      found.push(`${path.relative(REPO_ROOT, file).replaceAll("\\", "/")}:${index + 1}: ${line.trim().slice(0, 120)}`);
    }
  });
  return found;
}

describe("brand configuration", () => {
  it("carries the agreed product identity", () => {
    expect(BRAND.name).toBe("CourseJesus");
    expect(BRAND.nameZh).toBe("耶课稣");
    expect(BRAND.canonicalOrigin).toBe("https://coursejesus.com");
    expect(BRAND.wwwOrigin).toBe("https://www.coursejesus.com");
    expect(BRAND.apiOrigins.rag).toBe("https://rag.coursejesus.com");
    expect(BRAND.apiOrigins.agent).toBe("https://agent.coursejesus.com");
  });

  it("does not carry the old name anywhere in its own values", () => {
    expect(JSON.stringify(BRAND)).not.toContain("CourseMate");
    // The previous domain is carried deliberately, but only as the compatibility list:
    // nothing the app serves as its own address may still be the old domain.
    expect(BRAND.previousOrigins.every((origin) => origin.includes("qqttai.com"))).toBe(true);
    expect(BRAND.canonicalOrigin).not.toContain("qqttai");
    expect(BRAND.wwwOrigin).not.toContain("qqttai");
    expect(BRAND.apiOrigins.rag).not.toContain("qqttai");
    expect(BRAND.apiOrigins.agent).not.toContain("qqttai");
  });

  it("keeps the previous origins only as a compatibility list", () => {
    expect(BRAND.previousOrigins).toContain("https://qqttai.com");
    expect(isPreviousOrigin("https://qqttai.com")).toBe(true);
    expect(isPreviousOrigin("https://qqttai.com/")).toBe(true);
    expect(isPreviousOrigin(BRAND.canonicalOrigin)).toBe(false);
  });

  it("serves the owner's final artwork rather than an interim mark", () => {
    // This guard used to assert PENDING_ASSET, which was right while no artwork existed. The owner
    // supplied it, so the claim that has to hold now is the opposite one: the brand source says FINAL
    // and points at the derived PNG set. The files themselves (existence, dimensions, opacity and
    // hashes against the original) are checked where a filesystem is available, in
    // services/rag-api/tests/test_brand_assets.py — a jsdom test cannot see them.
    expect(BRAND.logoStatus).toBe("FINAL");
    expect(BRAND.logoPath.startsWith("/brand/")).toBe(true);
    expect(BRAND.logoPath.endsWith(".png")).toBe(true);
    expect(BRAND.logoAlt).toContain(BRAND.name);
  });

  it("declares the document and install icon sets from the same source", () => {
    const documentIcons = BRAND.icons.filter((icon) => icon.purposes.includes("document"));
    const manifestIcons = BRAND.icons.filter((icon) => icon.purposes.includes("manifest"));
    expect(documentIcons.map((icon) => icon.sizes)).toEqual([
      "16x16",
      "32x32",
      "48x48",
      "180x180",
    ]);
    expect(manifestIcons.map((icon) => icon.sizes)).toEqual(["192x192", "512x512"]);
    for (const icon of BRAND.icons) {
      expect(icon.src.startsWith("/brand/")).toBe(true);
      // The artwork is raster: declaring it as a vector, as the interim mark did, would be false.
      expect(icon.type).toBe("image/png");
    }
  });

  it("derives titles and the Canvas callback from the same source", () => {
    expect(brandTitle()).toBe("CourseJesus");
    expect(brandTitle("Course QA")).toBe("CourseJesus · Course QA");
    expect(brandTitleZh("学习空间")).toBe("CourseJesus 学习空间");
    expect(canvasCallbackUrl()).toBe(
      "https://rag.coursejesus.com/api/integrations/canvas/oauth/callback",
    );
  });
});

describe("no user-visible old brand text", () => {
  it("is absent from every source file outside the explicit remainder list", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const relative = path.relative(REPO_ROOT, file).replaceAll("\\", "/");
      if (Object.keys(NOT_YET_CONVERTED).some((allowed) => relative.endsWith(allowed))) continue;
      offenders.push(...visibleBrandText(file, readFileSync(file, "utf-8")));
    }
    expect(offenders).toEqual([]);
  });

  it("keeps the compatibility identifiers that the old name is allowed to survive in", () => {
    const provider = readFileSync(path.join(WEB_ROOT, "src", "CourseMateUi.tsx"), "utf-8");
    // The bridge name is an external contract for `api.js` and the browser suites.
    expect(provider).toContain("window.CourseMateAuth");
    expect(provider).toContain("window.CourseMateMath");
  });

  it("builds both documents from the placeholders rather than literal names", () => {
    for (const document of ["index.html", "ui.html"]) {
      const html = readFileSync(path.join(WEB_ROOT, document), "utf-8");
      expect(html).toContain("%BRAND_NAME%");
      expect(html).toContain("%BRAND_CANONICAL%");
      expect(html).toContain("%BRAND_MANIFEST%");
      expect(html).not.toContain("CourseMate");
    }
  });
});
