import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(HERE, "..");
const SRC = path.join(WEB_ROOT, "src");

/**
 * Where a Canvas credential may be typed, and where it may not.
 *
 * The shipped shell has exactly one screen that accepts a personal access token: the one-off task
 * credential, which the server offers only to listed accounts on a deployment that enables it. The
 * public connect screen and the local-bridge screen must keep saying that this site does not accept
 * one — that sentence is a design decision, not decoration, because it is what stops a student
 * pasting a credential into a page that has nowhere to put it.
 *
 * `scripts/scan_web_bundle_for_pat.mjs` runs the same idea against the **built** bytes. This test
 * runs against the sources as well, and adds the rule the scanner cannot express: a token field is
 * allowed in exactly one place, and the screen that offers it must also carry its warning.
 */

/** A field a credential could be typed into. `className` is deliberately not matched. */
const TOKEN_FIELD =
  /(?:^|[\s{,])(?:name|id)\s*[:=]\s*["'`][^"'`\n]*(?:token|pat|secret|credential)[^"'`\n]*["'`]/gi;

/** The file allowed to hold one. Everything else must hold none. */
const OWNER_MODE_FILE = path.join("src", "ui", "CanvasImport.jsx");

/** What the offering screen must also say, so the exception is a stated one. */
const OWNER_MODE_WARNING = "这个 Token 会发送到 CourseJesus 服务器";

/** What every other screen must keep saying. */
const PUBLIC_REFUSAL = "本站不接收个人访问令牌";

/** The data module that owns the wording, so the component renders it rather than paraphrasing it. */
const WARNING_MODULE = path.join("src", "ui", "canvasImport.js");

function sourceFiles(directory: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(ts|tsx|js|jsx)$/.test(entry) && !/\.test\./.test(entry)) out.push(full);
  }
  return out;
}

function read(file: string): string {
  return readFileSync(file, "utf8");
}

describe("the one screen that may accept a Canvas credential", () => {
  it("is the only source file with a token-shaped field", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const relative = path.relative(WEB_ROOT, file);
      const text = read(file);
      TOKEN_FIELD.lastIndex = 0;
      const hit = TOKEN_FIELD.exec(text);
      if (!hit) continue;
      if (relative === OWNER_MODE_FILE) continue;
      offenders.push(`${relative}: ${hit[0].trim()}`);
    }
    expect(offenders).toEqual([]);
  });

  it("puts the token field inside the owner-mode block, next to its warning", () => {
    const text = read(path.join(WEB_ROOT, OWNER_MODE_FILE));
    // Exactly one credential field, and it is a password input rather than a visible one.
    const passwordInputs = [...text.matchAll(/<input[^>]*type="password"[^>]*>/g)].map(
      (match) => match[0],
    );
    expect(passwordInputs).toHaveLength(1);
    const field = passwordInputs[0] ?? "";
    expect(field).toContain("autoComplete=\"off\"");
    // No `name`/`id`, so the value is never attached to a browser-autofilled field or a form post.
    expect(field).not.toMatch(/\bname=/);
    expect(field).not.toMatch(/\bid=/);
    // The warning that the token does reach the server is rendered by the same component that
    // renders the field, and the field exists only in the owner-mode renderer.
    expect(text).toContain("TASK_CREDENTIAL_WARNING");
    expect(read(path.join(WEB_ROOT, WARNING_MODULE))).toContain(OWNER_MODE_WARNING);
    expect(text).toContain("canvas-task-token");
  });

  it("keeps the public screens saying that this site does not accept one", () => {
    const text = read(path.join(WEB_ROOT, OWNER_MODE_FILE));
    expect(text).toContain(PUBLIC_REFUSAL);
    // The refusal belongs to the public connect screen, which is the one that asks for OAuth.
    const connect = text.slice(text.indexOf("renderConnect()"));
    expect(connect).toContain(PUBLIC_REFUSAL);
  });

  it("reaches the task-credential routes from exactly one client module", () => {
    const posters: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const relative = path.relative(WEB_ROOT, file);
      if (read(file).includes("/task-credentials")) posters.push(relative);
    }
    expect(posters).toEqual([path.join("src", "ui", "canvasImport.js")]);
  });

  it("never writes a credential to browser storage", () => {
    for (const file of sourceFiles(SRC)) {
      const text = read(file);
      expect(text).not.toMatch(/localStorage\.setItem\([^)]*token/i);
      expect(text).not.toMatch(/sessionStorage\.setItem\([^)]*token/i);
    }
  });
});
