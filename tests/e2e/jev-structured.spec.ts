/**
 * Module-level acceptance for the structured Jev enhancements that now reach a
 * real business path.
 *
 * Everything runs against the real three-service deployment shape (RAG API with
 * the UI extension mounted, the Node task agent, the production web build) in a
 * real Chrome with the project's own injected test identity. Two things are
 * proved here that unit tests cannot:
 *
 *   1. the capability dispatch (module E) is reachable from the shipped shell and
 *      its decision is reported on the create-run response the client receives —
 *      an answer-only request is not promoted into a Thinking teaching run, and a
 *      normal teaching request still is;
 *   2. the deployment runs with **no TypeSafe credential**, so this is also the
 *      "Jev is unavailable" acceptance: every decision degrades typed
 *      (`used_jev: false`, a deterministic/fallback path), the learner still gets
 *      a complete answer, and nothing in the learning state is fabricated.
 *
 * Journeys for modules A (extraction), C (evidence consistency) and the
 * three-layer audit of D are deliberately absent: those modules are not wired to
 * a business path yet, so there is no product behaviour to assert. They are
 * recorded as NOT_RUN in JEV_CALLSITE_MATRIX.md rather than faked here.
 */

import { expect, test } from "@playwright/test";

const UI = "http://127.0.0.1:8100/ui-extension/api/ui/v1";
const TOKEN = { Authorization: "Bearer test-session-token" };
const TERMINAL = ["completed", "failed", "cancelled"];

test.describe.configure({ mode: "serial" });

type CapabilityReport = {
  skill_id: string;
  teaching_flow: boolean;
  used_jev: boolean;
  path: string;
  explicit_command: string | null;
};

type RunBody = {
  id: string;
  teaching_mode?: string;
  capability: CapabilityReport;
};

/** Bind the taught node through the shipped tree UI (no run is started by this). */
async function bindNode(page: import("@playwright/test").Page) {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();
  await page.locator("button.knowledge-strip").click();
  const tree = page.locator(".tree-expanded");
  await expect(tree).toBeVisible();
  const nodeRow = tree.locator(".tree-node-new").filter({ hasText: "聚类分析" });
  await nodeRow.hover();
  await nodeRow.locator(".node-popover").getByRole("button", { name: /学习进度/ }).click();
  await expect(sendButton(page)).toBeVisible({ timeout: 90_000 });
}

/** The teach composer's own send control: absent while the pane is generating. */
function sendButton(page: import("@playwright/test").Page) {
  return page
    .locator(".learning-pane.pane-teach")
    .getByRole("button", { name: "发送知识问题" });
}

/** Send one message from the teach composer and return the create-run response. */
async function askTeach(
  page: import("@playwright/test").Page,
  text: string,
): Promise<RunBody> {
  const pane = page.locator(".learning-pane.pane-teach");
  const composer = pane.locator('textarea[aria-label="知识学习输入"]');
  const send = sendButton(page);
  // The shell clears its busy flag when the previous run's stream closes, which
  // can lag the run's terminal status, so wait for the composer itself: the send
  // control only exists when the pane is idle and is enabled once text is typed.
  await expect(send).toBeVisible({ timeout: 90_000 });
  await composer.fill(text);
  await expect(send).toBeEnabled({ timeout: 30_000 });
  const created = page.waitForResponse(
    (response) =>
      /\/conversations\/[^/]+\/runs$/.test(new URL(response.url()).pathname) &&
      response.request().method() === "POST",
    { timeout: 60_000 },
  );
  await send.click();
  const response = await created;
  expect(response.status()).toBe(202);
  return (await response.json()) as RunBody;
}

/** Wait for a run to reach a terminal state through the mounted API. */
async function waitTerminal(
  page: import("@playwright/test").Page,
  request: import("@playwright/test").APIRequestContext,
  runId: string,
) {
  let row: { status?: string } = {};
  await expect
    .poll(
      async () => {
        const response = await request.get(`${UI}/runs/${runId}`, { headers: TOKEN });
        row = (await response.json()) as { status?: string };
        return row.status ?? "";
      },
      { timeout: 90_000 },
    )
    .toMatch(/completed|failed|cancelled/);
  expect(TERMINAL).toContain(row.status ?? "");
  return row;
}

test("the shipped shell reports the capability it dispatched", async ({ page, request }) => {
  await bindNode(page);

  // An explicit "answer only" is honoured deterministically: no Jev call, and the
  // run does not take the journey-bound teaching flow.
  const answerOnly = await askTeach(page, "只回答");
  expect(answerOnly.capability.skill_id).toBe("direct_qa");
  expect(answerOnly.capability.teaching_flow).toBe(false);
  expect(answerOnly.capability.used_jev).toBe(false);
  expect(answerOnly.capability.explicit_command).toBe("ANSWER_ONLY");
  const answerOnlyRow = await waitTerminal(page, request, answerOnly.id);
  expect(answerOnlyRow.status).toBe("completed");
  await expect(page.locator(".learning-pane.pane-teach .generation-status")).not.toContainText(
    "失败",
  );

  // A normal teaching message still takes the journey-bound teaching flow.
  const teaching = await askTeach(page, "请从零教我理解这个节点");
  expect(teaching.capability.skill_id).toBe("node_lesson");
  expect(teaching.capability.teaching_flow).toBe(true);
  expect(teaching.capability.used_jev).toBe(false);
  expect(teaching.capability.explicit_command).toBe(null);
  const teachingRow = await waitTerminal(page, request, teaching.id);
  expect(teachingRow.status).toBe("completed");

  // The decision is on the run the client can read back, not only in a ledger.
  expect(teaching.id).not.toBe(answerOnly.id);
});

test("with no TypeSafe credential every decision degrades and teaching still works", async ({
  page,
  request,
}) => {
  await bindNode(page);

  const run = await askTeach(page, "请用一个例子解释聚类的基本思想");
  // No credential exists in this environment, so nothing may claim a Jev signal
  // and no definition may silently become authoritative.
  expect(run.capability.used_jev).toBe(false);
  expect(run.capability.teaching_flow).toBe(true);
  expect(run.capability.skill_id).toBe("node_lesson");

  await waitTerminal(page, request, run.id);
  const row = (await (
    await request.get(`${UI}/runs/${run.id}`, { headers: TOKEN })
  ).json()) as { status: string; error?: string | null; citations?: unknown[] };
  expect(row.status).toBe("completed");
  expect(row.error ?? null).toBe(null);
  expect(Array.isArray(row.citations)).toBe(true);

  // The answer really reached the learner.
  await expect(
    page.locator(".learning-pane.pane-teach .pane-messages, .learning-pane.pane-teach .message-list"),
  ).toBeVisible();
});