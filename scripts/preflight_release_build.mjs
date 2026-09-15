#!/usr/bin/env node
/**
 * Pre-build gate for the production frontend publish path.
 *
 * Runs first in the Netlify build command. In non-production contexts it is a
 * no-op so local and E2E builds stay usable; on a production deploy (or when
 * RELEASE_BUILD=1) it fails the build unless the real production configuration
 * is present:
 *
 *  - VITE_CLERK_PUBLISHABLE_KEY must exist and look like a production Clerk
 *    key (pk_live_...). A fake sample key cannot pass; whether the key's real
 *    Clerk application works is left to the real sign-in acceptance.
 *  - the API origins must be https production origins, never localhost;
 *  - VITE_AUTH_TEST_TOKEN must be unset (any value, even empty, fails);
 *  - VITE_V3_ENABLED must be 'true' for the released learning surface.
 *
 * No secret is printed: only presence, prefix and length are logged.
 */

const isProduction =
  process.env.CONTEXT === "production" || process.env.RELEASE_BUILD === "1";

if (!isProduction) {
  console.log("preflight: non-production context, production checks skipped.");
  process.exit(0);
}

const failures = [];

function requireValue(name) {
  const value = process.env[name];
  if (!value) {
    failures.push(`${name} is missing.`);
    return undefined;
  }
  return value;
}

const clerkKey = requireValue("VITE_CLERK_PUBLISHABLE_KEY");
if (clerkKey !== undefined && !/^pk_live_[A-Za-z0-9_-]+$/.test(clerkKey)) {
  failures.push(
    "VITE_CLERK_PUBLISHABLE_KEY does not look like a production Clerk key (pk_live_...). " +
      "A fake or test key cannot be published.",
  );
}

for (const name of ["VITE_UI_API_BASE", "VITE_RAG_API_URL", "VITE_AGENT_API_URL"]) {
  const value = process.env[name];
  if (value === undefined || value === "") {
    failures.push(`${name} is missing; production builds must pin production API origins.`);
    continue;
  }
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.hostname === "localhost" ||
      url.hostname === "127.0.0.1" ||
      /^10\.|^192\.168\.|^172\.(1[6-9]|2\d|3[01])\./.test(url.hostname)
    ) {
      failures.push(
        `${name} must be a production https origin; got ${url.protocol}//${url.hostname}.`,
      );
    }
  } catch {
    failures.push(`${name} is not a valid URL.`);
  }
}

if (process.env.VITE_AUTH_TEST_TOKEN !== undefined) {
  failures.push("VITE_AUTH_TEST_TOKEN is set; test identity must not enter a production build.");
}
if (requireValue("VITE_V3_ENABLED") !== "true") {
  failures.push("VITE_V3_ENABLED must be 'true' for the released learning surface.");
}

console.log(
  `preflight: context=${process.env.CONTEXT ?? "local"} ` +
    `clerk=${clerkKey ? `${clerkKey.slice(0, 7)}…(${clerkKey.length} chars)` : "missing"} ` +
    `ui_api=${process.env.VITE_UI_API_BASE ?? "default"} ` +
    `test_token=${process.env.VITE_AUTH_TEST_TOKEN === undefined ? "absent" : "PRESENT"}`,
);

if (failures.length > 0) {
  console.error("Production build preflight FAILED:");
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("preflight: production configuration checks passed.");
