/**
 * The single brand and URL source for the web app.
 *
 * Task A1 asks for one configuration source ("建立一个品牌/URL配置源，集中提供：英文名、中文名、
 * canonical origins、API origins、logo路径、support名称等。前端/meta/manifest/通知模板引用它，
 * 不各页面硬编码"). This module is that source: documents, the manifest and components read
 * from it instead of repeating the product name.
 *
 * What is deliberately NOT here: compatibility identifiers. `window.CourseMateAuth`,
 * `window.CourseMateMath`, the `cmui_*` tables and the `CMUI_*` environment variables keep
 * their names because callers and stored data depend on them, and the internal
 * `X-CourseMate-Internal-Token` header is a service-to-service contract. Renaming those is a
 * separate, dual-named migration — see docs/coursejesus/BRAND_REPLACEMENT_MATRIX.md, class B.
 */

export interface BrandApiOrigins {
  /** Host serving the RAG API in production. */
  readonly rag: string;
  /** Host serving the study-planning agent API in production. */
  readonly agent: string;
}

export interface BrandConfig {
  /** English display name. */
  readonly name: string;
  /** Chinese display name. */
  readonly nameZh: string;
  /** Short line used in footers and share text. */
  readonly tagline: string;
  /** Canonical site origin; the apex, never `www`. */
  readonly canonicalOrigin: string;
  /** Host that redirects to the canonical origin. */
  readonly wwwOrigin: string;
  /** Production API origins (request routing still follows the Vite env vars). */
  readonly apiOrigins: BrandApiOrigins;
  /** Origins kept working during the migration window. */
  readonly previousOrigins: readonly string[];
  /** Interim mark: the repository's existing SVG, not the owner's final artwork. */
  readonly logoPath: string;
  readonly logoStatus: "PENDING_ASSET" | "FINAL";
  /** Matches the interim mark so the browser chrome does not clash with it. */
  readonly themeColor: string;
  readonly support: {
    readonly name: string;
    /** Unknown until the owner supplies it; never invented here. */
    readonly email: string | null;
  };
}

export const BRAND: BrandConfig = Object.freeze({
  name: "CourseJesus",
  nameZh: "耶课稣",
  tagline: "Grounded answers. Accountable actions.",
  canonicalOrigin: "https://coursejesus.com",
  wwwOrigin: "https://www.coursejesus.com",
  apiOrigins: Object.freeze({
    rag: "https://rag.coursejesus.com",
    agent: "https://agent.coursejesus.com",
  }),
  previousOrigins: Object.freeze([
    "https://qqttai.com",
    "https://www.qqttai.com",
    "https://rag.qqttai.com",
    "https://agent.qqttai.com",
  ]),
  logoPath: "/favicon.svg",
  logoStatus: "PENDING_ASSET",
  themeColor: "#0d4637",
  support: Object.freeze({ name: "CourseJesus support", email: null }),
});

/** Title for a document: the product name, optionally with a section. */
export function brandTitle(section?: string): string {
  return section ? `${BRAND.name} · ${section}` : BRAND.name;
}

/** Title for a Chinese-language page, keeping the English product name readable. */
export function brandTitleZh(section?: string): string {
  return section ? `${BRAND.name} ${section}` : BRAND.name;
}

/** True when an origin belongs to the pre-migration domain. */
export function isPreviousOrigin(origin: string): boolean {
  return BRAND.previousOrigins.includes(origin.replace(/\/+$/, ""));
}

/** The OAuth callback origin the Canvas integration is registered against. */
export function canvasCallbackUrl(): string {
  return `${BRAND.apiOrigins.rag}/api/integrations/canvas/oauth/callback`;
}
