/**
 * Enforce the narrow Canvas owner-token boundary in the bytes we ship.
 *
 * The normal student path is OAuth or the local bridge. A deployment may additionally expose one
 * owner-only task-credential screen. That screen intentionally sends one PAT to exactly one API
 * client module, which holds only the React input value until the request finishes. This scanner
 * makes that exception precise instead of either banning the required flow or allowing PATs
 * throughout the application.
 *
 * The build fails when a credential can be persisted, placed in a URL, logged, or submitted from a
 * second module. It also fails if the two intended fields or their plain-language warnings vanish
 * from the production bundle.
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

const REQUIRED_BUILT_TEXT = [
  "学校 Canvas 地址",
  "本次 Access Token",
  "这个 Token 会发送到 CourseJesus 服务器",
  "公共学生入口不接收个人访问令牌",
  "不写入数据库、不写入日志",
];

const FORBIDDEN = [
  {
    pattern:
      /(?:localStorage|sessionStorage)\s*\.\s*setItem\s*\([^)]{0,400}(?:personal_access_token|access.?token|taskToken|credential)/gi,
    why: "a Canvas credential written to browser storage",
  },
  {
    pattern:
      /(?:indexedDB\s*\.\s*open|IDBObjectStore[^;]{0,120}\.put)\s*\([^)]{0,400}(?:personal_access_token|access.?token|taskToken|credential)/gi,
    why: "a Canvas credential written to IndexedDB",
  },
  {
    pattern:
      /(?:URLSearchParams|searchParams\s*\.\s*(?:set|append))\s*\([^)]{0,300}(?:personal_access_token|access_token|canvas_token|taskToken)/gi,
    why: "a Canvas credential added to a URL",
  },
  {
    pattern: /[?&](?:personal_access_token|access_token|canvas_token)=/gi,
    why: "a Canvas credential query parameter",
  },
  {
    pattern:
      /(?:console\s*\.\s*(?:log|info|warn|error)|analytics\s*\.\s*track)\s*\([^)]{0,400}(?:personal_access_token|taskToken)/gi,
    why: "a Canvas credential sent to logging or analytics",
  },
];

function scanForbidden(files, relativeTo) {
  const offenders = [];
  for (const file of files) {
    const contents = readFileSync(file, "utf8");
    for (const { pattern, why } of FORBIDDEN) {
      pattern.lastIndex = 0;
      const hit = pattern.exec(contents);
      if (hit) offenders.push(`${path.relative(relativeTo, file)}: ${why}`);
    }
  }
  return offenders;
}

let builtFiles;
try {
  builtFiles = walk(root, BUILT);
} catch (error) {
  console.error(`scan_web_bundle_for_pat: cannot read the build output at ${root}: ${error.message}`);
  process.exit(1);
}
if (builtFiles.length === 0) {
  console.error(`scan_web_bundle_for_pat: nothing to scan under ${root}`);
  process.exit(1);
}

const sources = path.resolve(root, "..", "src");
let sourceFiles;
try {
  sourceFiles = walk(sources, SOURCE).filter((file) => !/\.test\.[cm]?[jt]sx?$/.test(file));
} catch (error) {
  console.error(`scan_web_bundle_for_pat: cannot read the sources at ${sources}: ${error.message}`);
  process.exit(1);
}

const offenders = [
  ...scanForbidden(builtFiles, root),
  ...scanForbidden(sourceFiles, sources),
];

const clientPath = path.join(sources, "ui", "canvasImport.js");
const componentPath = path.join(sources, "ui", "CanvasImport.jsx");
const credentialFieldOwners = sourceFiles
  .filter((file) => readFileSync(file, "utf8").includes("personal_access_token"))
  .map((file) => path.relative(sources, file));
const expectedOwner = path.relative(sources, clientPath);
if (credentialFieldOwners.length !== 1 || credentialFieldOwners[0] !== expectedOwner) {
  offenders.push(
    `personal_access_token may appear only in ${expectedOwner}; found ${credentialFieldOwners.join(", ") || "none"}`,
  );
}

const routeOwners = sourceFiles
  .filter((file) => readFileSync(file, "utf8").includes("/task-credentials"))
  .map((file) => path.relative(sources, file));
if (routeOwners.length !== 1 || routeOwners[0] !== expectedOwner) {
  offenders.push(
    `task-credential routes may appear only in ${expectedOwner}; found ${routeOwners.join(", ") || "none"}`,
  );
}

const component = readFileSync(componentPath, "utf8");
const client = readFileSync(clientPath, "utf8");
const passwordFields = component.match(/<input[^>]*type=["']password["'][^>]*>/g) || [];
if (passwordFields.length !== 1) {
  offenders.push(`the owner screen must contain exactly one password field; found ${passwordFields.length}`);
} else if (/\b(?:name|id)=/.test(passwordFields[0])) {
  offenders.push("the owner token field must not have a browser-autofill name or id");
}

const sourceContractText = `${component}\n${client}`;
for (const required of REQUIRED_BUILT_TEXT) {
  if (!sourceContractText.includes(required)) offenders.push(`the owner flow source is missing: ${required}`);
}

const builtText = builtFiles.map((file) => readFileSync(file, "utf8")).join("\n");
const builtHasCanvasFlow =
  builtText.includes("/task-credentials") || builtText.includes("personal_access_token");
if (builtHasCanvasFlow) {
  for (const required of REQUIRED_BUILT_TEXT) {
    if (!builtText.includes(required)) offenders.push(`the production bundle is missing: ${required}`);
  }
}

if (offenders.length > 0) {
  console.error("scan_web_bundle_for_pat: Canvas credential boundary failed:");
  for (const item of offenders) console.error(`  ${item}`);
  process.exit(1);
}

console.log(
  `scan_web_bundle_for_pat: ${builtFiles.length} built files; one owner field, one client, ` +
    `no persistence/URL/logging leak; Canvas flow ${builtHasCanvasFlow ? "present" : "not included in this environment build"}`,
);
