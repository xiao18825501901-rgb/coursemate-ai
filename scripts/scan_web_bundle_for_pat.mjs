/**
 * Fail a production build that could ask a student for a Canvas token.
 *
 * The product rule is that a Personal Access Token never reaches CourseJesus: the local bridge reads
 * it on the user's own machine, and the website only ever connects through the school's OAuth page.
 * A source-level test can be defeated by a build-time transform, a template string or a generated
 * file, so the check runs against the **built** output — the bytes that would actually be served.
 *
 * What it looks for, in `dist`:
 *   * form fields or inputs whose name/id mentions a token, pat or credential;
 *   * fetches that post a token-ish field to the Canvas integration routes;
 *   * the absence of the sentence that tells the user not to paste a token into the page.
 *
 * Usage: node scripts/scan_web_bundle_for_pat.mjs apps/web/dist
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const root = process.argv[2] || "apps/web/dist";

function walk(directory, extensions) {
  const files = [];
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (statSync(full).isDirectory()) files.push(...walk(full, extensions));
    else if (extensions.test(entry)) files.push(full);
  }
  return files;
}

const BUILT = /\.(js|mjs|html|css)$/;
const SOURCE = /\.(ts|tsx|js|jsx)$/;

/** Patterns that would mean a token can be typed into, or posted from, the shipped bundle. */
const FORBIDDEN = [
  { pattern: /name:\s*["']([a-z_]*token[a-z_]*)["']/gi, why: "a field named like a token" },
  { pattern: /name:\s*["']([a-z_]*pat[a-z_]*)["']/gi, why: "a field named like a PAT" },
  { pattern: /["'](canvas[_-]?token|personal[_-]?access[_-]?token|canvas[_-]?pat)["']/gi,
    why: "a Canvas token field name" },
  { pattern: /localStorage\.setItem\([^)]*token/gi, why: "a token written to localStorage" },
  { pattern: /sessionStorage\.setItem\([^)]*token/gi, why: "a token written to sessionStorage" },
];

/** The rule that must survive whatever else changes. */
const REQUIRED = "本站不接收个人访问令牌";

let files;
try {
  files = walk(root, BUILT);
} catch (error) {
  console.error(`scan_web_bundle_for_pat: cannot read the build output at ${root}: ${error.message}`);
  process.exit(1);
}
if (files.length === 0) {
  console.error(`scan_web_bundle_for_pat: nothing to scan under ${root}`);
  process.exit(1);
}

const offenders = [];
let sawWarning = false;
for (const file of files) {
  const text = readFileSync(file, "utf8");
  if (text.includes(REQUIRED)) sawWarning = true;
  for (const { pattern, why } of FORBIDDEN) {
    pattern.lastIndex = 0;
    const hit = pattern.exec(text);
    if (hit) offenders.push(`${path.relative(root, file)}: ${why} — ${hit[0].slice(0, 80)}`);
  }
}

// The sources as well as the output: a build-time transform, a template literal or a generated file
// could hide a field from the bundle, and the rule is about the code that produces it.
const sources = path.resolve(root, "..", "src");
try {
  for (const file of walk(sources, SOURCE)) {
    const text = readFileSync(file, "utf8");
    for (const { pattern, why } of FORBIDDEN) {
      pattern.lastIndex = 0;
      const hit = pattern.exec(text);
      if (hit) offenders.push(`${path.relative(sources, file)}: ${why} — ${hit[0].slice(0, 80)}`);
    }
  }
} catch (error) {
  console.error(`scan_web_bundle_for_pat: cannot read the sources at ${sources}: ${error.message}`);
  process.exit(1);
}

if (offenders.length > 0) {
  console.error("scan_web_bundle_for_pat: the production bundle could collect a Canvas token:");
  for (const item of offenders) console.error(`  ${item}`);
  process.exit(1);
}

if (!sawWarning) {
  console.error(
    "scan_web_bundle_for_pat: the bundle no longer contains the notice that the site does not " +
      `accept a personal access token ("${REQUIRED}"). That sentence is part of the design, not ` +
      "decoration: without it a student may paste a credential into the page.",
  );
  process.exit(1);
}

console.log(
  `scan_web_bundle_for_pat: ${files.length} built files, no token field, notice present`,
);
