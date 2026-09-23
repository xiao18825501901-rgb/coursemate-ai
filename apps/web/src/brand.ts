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

export interface BrandIcon {
  /** Path served from `public/`, without a build hash (browsers cache by URL, so it is versioned). */
  readonly src: string;
  /** The sizes it is declared for, as the document link or manifest entry needs them. */
  readonly sizes: string;
  /** The MIME type. Raster here on purpose: the artwork is a PNG, and calling it a vector would lie. */
  readonly type: string;
  /** Where the icon is used: the document entry, or the installable manifest. */
  readonly purposes: readonly string[];
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
  /**
   * The owner's artwork, derived deterministically from the supplied original.
   *
   * The source (`apps/web/public/brand/coursejesus-logo-source.png`, sha256
   * `ae536df4cc1e9e989c3b9c7ff15a33137d1f526bcbc779aebd4b3e6e93be14e5`) is a 1254×1254 emblem on
   * transparency; each size below is that artwork trimmed to its ink bounding box, given a uniform 4%
   * margin and scaled with LANCZOS — never stretched, never redrawn, never recoloured. The hashes and
   * the derivation are recorded in `apps/web/public/brand/derived-manifest.json` and in
   * `docs/coursejesus/LOGO_ASSET_MANIFEST.md`.
   */
  readonly logoPath: string;
  /** Accurate alternative text for the mark, so a screen reader gets the product name. */
  readonly logoAlt: string;
  /** The icon set the documents and the PWA manifest reference, in the order they are declared. */
  readonly icons: readonly BrandIcon[];
  readonly logoStatus: "PENDING_ASSET" | "FINAL";
  /** Matches the artwork's own deep crimson so the browser chrome does not clash with it. */
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
  logoPath: "/brand/logo-mark-512.png",
  logoAlt: "CourseJesus 耶课稣",
  icons: Object.freeze([
    { src: "/brand/favicon-16.png", sizes: "16x16", type: "image/png", purposes: ["document"] },
    { src: "/brand/favicon-32.png", sizes: "32x32", type: "image/png", purposes: ["document"] },
    { src: "/brand/favicon-48.png", sizes: "48x48", type: "image/png", purposes: ["document"] },
    {
      src: "/brand/apple-touch-icon-180.png",
      sizes: "180x180",
      type: "image/png",
      purposes: ["document"],
    },
    { src: "/brand/icon-192.png", sizes: "192x192", type: "image/png", purposes: ["manifest"] },
    { src: "/brand/icon-512.png", sizes: "512x512", type: "image/png", purposes: ["manifest"] },
  ]),
  logoStatus: "FINAL",
  themeColor: "#6e000e",
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
