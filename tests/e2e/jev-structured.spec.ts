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
 * Journeys are included for module A (extraction verification) and the
 * Jev-unavailable deployment. Modules C (evidence consistency) and the three-layer
 * audit of D have browser coverage of *behaviour* only where the deterministic
 * provider can show it; their Jev-dependent verdicts (`SAME_CONTEXT_CONTRADICTION`,
 * an unsupported citation) need a live signal and are recorded as NOT_RUN in
 * JEV_CALLSITE_MATRIX.md rather than faked here.
 *
 * One honest limit worth stating: the deterministic test provider never emits
 * citation markers, so `.citation-list`-level data is filled from the retrieved
 * sources but a run's `citations` array is always empty in every suite. Module A's
 * per-source report is therefore asserted through the shipped QA page's own
 * request (`POST /api/qa/chat`), whose `meta` event carries it.
 */

import { expect, test } from "@playwright/test";

const UI = "http://127.0.0.1:8100/ui-extension/api/ui/v1";
const TOKEN = { Authorization: "Bearer test-session-token" };
const TERMINAL = ["completed", "failed", "cancelled"];

test.describe.configure({ mode: "serial" });

/**
 * Whether this run has a definition promoted to `on`.
 *
 * It matters to two journeys and in opposite directions. `used_jev` is false in shadow whether or
 * not a credential exists, so the journeys that assert "no Jev signal" hold in the default shape and
 * would break — correctly — once a definition is promoted. The journey that proves a promotion is
 * *used* can only run when one is. Each states its own precondition and skips with the reason rather
 * than being silently wrong in the other configuration.
 */
const PROMOTION = process.env.JEV_DEFINITION_MODES ?? "";
const PROMOTED = PROMOTION.includes("=on");
const PROMOTION_NOTE =
  "JEV_DEFINITION_MODES has a definition promoted to `on`, which changes `used_jev` by design; " +
  "the promoted-capability journey covers that configuration";

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
  if (response.status() !== 202) {
    // Say *why*, not just "expected 202". A refusal here is the product telling the caller
    // something, and a bare status code throws that away — which is how a promoted definition's
    // 409 stayed unexplained on its first run.
    const body = await response.text();
    throw new Error(
      `run creation answered ${response.status()} instead of 202: ${body.slice(0, 600)}`,
    );
  }
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
  test.skip(PROMOTED, PROMOTION_NOTE);
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

test("a promoted capability definition is actually used, which shadow alone can never show", async ({
  page,
  request,
}) => {
  // This is the assertion the rest of the suite cannot make. Every other journey here runs with
  // `used_jev === false`, and that is false in shadow **whether or not a credential exists** — so a
  // run with a live key looks exactly like a run without one (round-86 note in
  // DSH_JEV_DEEPSEEK_EXECUTION_STATE.md). The router honours `mode == "on"` explicitly
  // (`capability_router.py`: `decision.mode == "on" and decision.suggestion is not None and
  // decision.suggestion.choice in offered`), so promoting this one definition is what makes the
  // difference observable — and the journey is skipped, with its reason, when the run cannot show it.
  const key = process.env.TYPESAFE_API_KEY ?? "";
  const modes = process.env.JEV_DEFINITION_MODES ?? "";
  test.skip(
    key === "" || !modes.includes("teaching.capability.v1=on"),
    "needs a live TypeSafe credential AND JEV_DEFINITION_MODES=teaching.capability.v1=on in the " +
      "environment Playwright starts the RAG service with (the config spreads process.env)",
  );

  await bindNode(page);

  // A ruled-out request still spends no Jev call: the deterministic filter runs first, and a
  // promotion must not turn "answer only" into a model decision.
  const answerOnly = await askTeach(page, "只回答");
  expect(answerOnly.capability.skill_id).toBe("direct_qa");
  expect(answerOnly.capability.explicit_command).toBe("ANSWER_ONLY");
  expect(answerOnly.capability.used_jev).toBe(false);

  // A normal teaching request now goes through the promoted definition, and the product uses it.
  const teaching = await askTeach(page, "请从零教我理解这个节点");
  expect(teaching.capability.used_jev).toBe(true);
  expect(teaching.capability.teaching_flow).toBe(true);
  // The chosen skill must be one the catalogue actually defines, and one this mode allows.
  expect([
    "node_lesson",
    "worked_example",
    "step_explanation",
    "direct_qa",
    "prerequisite_explanation",
    "code_trace",
    "figure_explanation",
    "exercise",
  ]).toContain(teaching.capability.skill_id);
  const row = await waitTerminal(page, request, teaching.id);
  expect(row.status).toBe("completed");
});

test("the shipped shell can file a problem report without leaving the lesson", async ({
  page,
}) => {
  await page.goto("/app#/course/cs3481/learn");
  await expect(page.locator(".workspace-columns")).toBeVisible();

  await page.getByRole("button", { name: /报告问题/ }).first().click();
  const dialog = page.locator(".modal");
  await expect(dialog).toBeVisible();

  // The privacy contract is visible in the UI: identifiers only until the user opts
  // in, and the free-text note is only reachable once they do. A disabled field is
  // the honest presentation of "this needs consent", and it is what keeps the form
  // from sending a body the server would refuse.
  const note = dialog.getByRole("textbox").last();
  await expect(note).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await expect(note).toBeEnabled();
  await note.fill("第 2 步的公式看起来不对");

  await dialog.locator("select").selectOption("ANSWER_WRONG");
  const submitted = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/api/feedback") &&
      response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: /提交报告/ }).click();
  const response = await submitted;
  expect(response.status()).toBe(201);

  // What the shell sent: the user's own note and the conversation body only because
  // they ticked the consent box — the same contract the server enforces.
  const payload = response.request().postDataJSON() as {
    attach_body?: boolean;
    report_text?: string | null;
    category?: string | null;
  };
  expect(payload.attach_body).toBe(true);
  expect(payload.report_text).toContain("公式");
  expect(payload.category).toBe("ANSWER_WRONG");

  // What the server answered: a queued report with its key, triage suggestion and the
  // durable row id — not a fabricated success.
  const body = (await response.json()) as {
    report_id?: string;
    report_key?: string;
    suggested_queue?: string;
    path?: string;
  };
  expect(body.report_id ?? "").toMatch(/^feedback_/);
  expect(body.report_key ?? "").not.toBe("");
  expect(body.path ?? "").toMatch(/^(jev|fallback:)/);
  await expect(dialog).toBeHidden({ timeout: 15_000 });
});

test("with no TypeSafe credential every decision degrades and teaching still works", async ({
  page,
  request,
}) => {
  test.skip(PROMOTED, PROMOTION_NOTE);
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

type FieldReport = {
  field: string;
  value: string;
  status: string;
  verdict: string | null;
  path: string;
  used_jev: boolean;
  trusted: boolean;
};

type ReferenceReport = {
  questioned: boolean;
  fields: FieldReport[];
  dropped: string[];
  needs_review: string[];
  jev_calls: number;
};

/**
 * Where the QA page's own chat streams are tee'd for the assertion.
 *
 * `sessionStorage` rather than a page variable on purpose: the page navigates to
 * the conversation URL as soon as the first answer lands, which discards both page
 * variables and Playwright's buffered `response.text()`. Session storage survives
 * the navigation and is cleared with the browser context, so each journey starts
 * empty.
 */
const CHAT_CAPTURE_KEY = "__cm_qa_chat_bodies";

/**
 * Tee the QA page's own `POST /api/qa/chat` responses without altering them.
 *
 * Reading the tee *incrementally* is the point. `response.clone().text()` looks
 * simpler but rejects with `AbortError` in this page: the shell aborts the stream as
 * soon as it sees the terminal `done` event, so a whole-body read never completes.
 * The report rides on the very first frame (`meta`), so the reader accumulates
 * chunks and stores them the moment the report appears, then stops.
 */
async function installChatCapture(page: import("@playwright/test").Page): Promise<void> {
  await page.addInitScript((key: string) => {
    const original = window.fetch.bind(window);
    const log = (entry: string) => {
      const stored = JSON.parse(sessionStorage.getItem(`${key}_log`) ?? "[]") as string[];
      stored.push(entry);
      sessionStorage.setItem(`${key}_log`, JSON.stringify(stored));
    };
    const record = (text: string) => {
      const stored = JSON.parse(sessionStorage.getItem(key) ?? "[]") as string[];
      stored.push(text);
      sessionStorage.setItem(key, JSON.stringify(stored));
    };
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const input = args[0];
      const url =
        typeof input === "string" ? input : input instanceof Request ? input.url : "";
      log(`request ${url}`);
      const response = await original(...args);
      log(`response ${response.status} ${url}`);
      if (url.endsWith("/api/qa/chat")) {
        const reader = response.clone().body?.getReader();
        if (reader) {
          const decoder = new TextDecoder();
          void (async () => {
            let text = "";
            try {
              for (;;) {
                const { value, done } = await reader.read();
                if (done) break;
                text += decoder.decode(value, { stream: true });
                if (text.includes('"referenceVerification"')) {
                  record(text);
                  log(`captured ${text.length}`);
                  await reader.cancel();
                  return;
                }
              }
              log(`stream ended with ${text.length} chars and no report`);
            } catch (error: unknown) {
              log(`capture stopped after ${text.length} chars: ${String(error)}`);
            }
          })();
        }
      }
      return response;
    };
  }, CHAT_CAPTURE_KEY);
}

/** Ask one question in the shipped QA page and return its verification report. */
async function askQaPage(
  page: import("@playwright/test").Page,
  question: string,
): Promise<ReferenceReport> {
  await page.getByLabel("Ask a course question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const deadline = Date.now() + 90_000;
  let last = "";
  while (Date.now() < deadline) {
    const raw = await page.evaluate((key) => sessionStorage.getItem(key), CHAT_CAPTURE_KEY);
    if (raw) {
      const bodies = JSON.parse(raw) as string[];
      last = bodies[bodies.length - 1] ?? "";
      if (last.includes('"referenceVerification"')) {
        const metaLine = last
          .split("\n")
          .find(
            (line) => line.startsWith("data:") && line.includes('"referenceVerification"'),
          );
        expect(metaLine, `no meta event carried the report:\n${last.slice(0, 400)}`).toBeTruthy();
        const meta = JSON.parse(String(metaLine).replace(/^data:\s*/, "")) as {
          referenceVerification: ReferenceReport;
        };
        return meta.referenceVerification;
      }
    }
    await page.waitForTimeout(250);
  }
  const diagnostics = await page.evaluate(
    (key) => sessionStorage.getItem(`${key}_log`) ?? "[]",
    CHAT_CAPTURE_KEY,
  );
  throw new Error(
    `the QA page never reported a verification (capture: ${last.length} chars, ` +
      `traffic: ${diagnostics})`,
  );
}

test("the shipped page verifies a named question reference before filtering on it", async ({
  page,
}) => {
  await installChatCapture(page);
  await page.goto("/qa/ge2324");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();

  // A named question with a sub-part: both labels are judged, neither is dropped,
  // and with no credential nothing claims they were verified by a model.
  const named = await askQaPage(page, "assignment_2.pdf Question 1(b) 说明了什么？");
  expect(named.questioned).toBe(true);
  expect(named.fields.map((field) => field.field).sort()).toEqual([
    "question_number",
    "question_part",
  ]);
  expect(named.fields.map((field) => field.value).sort()).toEqual(["1", "b"]);
  expect(named.dropped).toEqual([]);
  for (const field of named.fields) {
    expect(field.used_jev).toBe(false);
    expect(field.verdict).toBe(null);
    expect(field.status).toBe("NEEDS_REVIEW");
    expect(field.path.startsWith("fallback:")).toBe(true);
    expect(field.trusted).toBe(true);
  }
  // The answer still arrived, grounded in the material the learner named.
  await expect(page.locator(".message-assistant").last()).toBeVisible();
  await expect(page.locator(".citation-list").last()).toBeVisible();
});

test("prose that merely follows the number is not a sub-part", async ({ page }) => {
  await installChatCapture(page);
  await page.goto("/qa/ge2324");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();

  // "question 5 have …" used to become the exact-locator filter `question_part='h'`,
  // which suppressed the exact hits for question 5.
  const prose = await askQaPage(page, "What does question 5 have to do with chapter 2?");
  expect(prose.questioned).toBe(true);
  expect(prose.fields.map((field) => field.field)).toEqual(["question_number"]);
  expect(prose.fields[0].value).toBe("5");
  expect(prose.dropped).toEqual([]);
});

test("a question that names no question spends nothing", async ({ page }) => {
  await installChatCapture(page);
  await page.goto("/qa/ge2324");
  await expect(page.getByRole("heading", { level: 1, name: "Ask your material" })).toBeVisible();

  const plain = await askQaPage(page, "聚类分析是什么意思");
  expect(plain.questioned).toBe(false);
  expect(plain.fields).toEqual([]);
  expect(plain.jev_calls).toBe(0);
});