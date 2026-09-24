/**
 * Module-level acceptance for the structured Jev enhancements that now reach a
 * real business path.
 *
 * Everything runs against the real three-service deployment shape (RAG API with
 * the UI extension mounted, the Node task agent, the production web build) in a
 * real Chrome with the project's own injected test identity. What these journeys
 * prove that unit tests cannot:
 *
 *   1. the capability dispatch (module E) is reachable from the shipped shell and
 *      its decision is reported on the create-run response the client receives;
 *   2. a Chinese question reaches English material through an accepted alias, and
 *      the same word in two unrelated senses is never merged into one concept
 *      (module B), asserted on the citations the learner's own client receives and
 *      on the knowledge tree's node identity;
 *   3. two fragments of one document that answer different tasks are reported as a
 *      version/task difference with **both** kept, and — with the definition
 *      promoted and a live credential — a genuine contradiction between two
 *      sources is surfaced with both fragments kept and neither deleted
 *      (module C);
 *   4. a figure the claim asserts that no cited source states is flagged in code
 *      with zero model calls, while the sources are still delivered and rendered
 *      (module D), and the same question about a figure a source *does* state is
 *      not flagged;
 *   5. a side-effecting write is refused when the intent guard cannot answer, and
 *      is **not** refused when it can (module F);
 *   6. the deployment runs with **no TypeSafe credential**, so this is also the
 *      "Jev is unavailable" acceptance: every decision degrades typed
 *      (`used_jev: false`, a deterministic/fallback path), the learner still gets a
 *      complete answer, and nothing in the learning state is fabricated.
 *
 * The content these journeys act on is seeded by
 * `scripts/seed_structured_fixture.py`, and the properties that make each assertion
 * meaningful are pinned by
 * `services/rag-api/tests/test_structured_e2e_fixture_shape.py`.
 *
 * Modules whose verdicts need a live signal state that as their own precondition
 * and skip with the reason; nothing here is satisfied by a helper existing. Two
 * invocation facts worth keeping: the deterministic provider emits the `[S1]`
 * markers a real model emits (otherwise a run's `citations` array is empty and the
 * whole citation path is unreachable in local acceptance), and the `problem` lane
 * is deliberately left unmarked because its output is parsed into numbered steps.
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

/**
 * The fixture pages `scripts/seed_structured_fixture.py` ingests into the owner's
 * own workspace corpus, and the two figures the citation journeys assert on.
 *
 * They live here as the same literals the seeder uses; the properties that make
 * each journey meaningful (the alias page never contains the Chinese term, both
 * kernel pages use the word in unrelated senses, `42%` appears in none of them and
 * `5%` in exactly one) are checked by
 * `services/rag-api/tests/test_structured_e2e_fixture_shape.py`, so a journey
 * cannot quietly become a test of nothing.
 */
const ALIAS_PAGE = "e2e_density_clustering_en.txt";
const KERNEL_SVM_PAGE = "e2e_kernel_svm_en.txt";
const KERNEL_OS_PAGE = "e2e_kernel_os_en.txt";
const ALPHA_TWO_SIDED_A_PAGE = "e2e_alpha_two_sided_a.txt";
const THRESHOLD_SECTIONS_PAGE = "e2e_threshold_sections.md";
const LOCATOR_PAGE = "e2e_locator_questions.txt";
const UNSUPPORTED_FIGURE = "42%";
const SUPPORTED_FIGURE = "5%";

const TOOL_INTENT_MODE = process.env.JEV_TOOL_INTENT_MODE ?? "off";
const AGENT = "http://127.0.0.1:8101";
const AGENT_TOKEN = { Authorization: "Bearer test-session-token" };

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

/**
 * A citation card as the learner's client receives it.
 *
 * `GET /runs/{rid}` returns the retrieved source records with only their `text`
 * stripped, so the module annotations survive onto the card the client reads:
 * `support` / `audit_layer` / `audit_missing_numbers` from the claim↔citation audit
 * (module D) and `jev_consistency` / `jev_conflict_with` from the condition/conflict
 * check (module C).
 */
type CitationCard = {
  id: string;
  document_id?: string;
  name?: string;
  page?: number;
  locator?: string;
  support?: string;
  audit_layer?: string;
  audit_missing_numbers?: string[];
  audit_claim?: string;
  audit_error?: string;
  jev_consistency?: string;
  jev_conflict_with?: string[];
};

type RunRow = {
  status: string;
  error?: string | null;
  user_text?: string;
  conversation?: string;
  citations?: CitationCard[];
};

/** Read one run back the way the shipped shell does. */
async function readRun(
  request: import("@playwright/test").APIRequestContext,
  runId: string,
): Promise<RunRow> {
  const response = await request.get(`${UI}/runs/${runId}`, { headers: TOKEN });
  expect(response.status()).toBe(200);
  return (await response.json()) as RunRow;
}

/** Ask one question and return the run's cards once it has reached a terminal state. */
async function askAndRead(
  page: import("@playwright/test").Page,
  request: import("@playwright/test").APIRequestContext,
  text: string,
): Promise<RunRow> {
  const run = await askTeach(page, text);
  await waitTerminal(page, request, run.id);
  const row = await readRun(request, run.id);
  expect(row.status, `run failed: ${row.error ?? ""}`).toBe("completed");
  return row;
}

/**
 * The most recent answer in the teaching pane.
 *
 * Scoped deliberately: `.citation-row` is rendered per message, so an assertion on
 * "the last row in the pane" can match the *previous* answer while the new one is
 * still being appended — which is how a chip-count assertion can pass against a
 * stale row and the verdict assertion on the same row then fail. Every UI
 * assertion below anchors on a string only the new answer contains, so it retries
 * until the message it is about has actually rendered.
 */
function lastAnswer(page: import("@playwright/test").Page) {
  return page.locator(".learning-pane.pane-teach .chat-message-new.assistant").last();
}

/**
 * Assert the learner can see something in the newest answer, taking the shell's own
 * documented recovery path if the live stream did not render it.
 *
 * The condition it was written for is no longer unexplained. Round 93 measured it:
 * `restorePair` (a node binding finishing) moved the pane to the pair's conversation
 * while a run was streaming in the conversation it had been started in, and the
 * render guard abandoned the answer silently — leaving the learner with their
 * question, no answer, and a disabled composer. Both halves are fixed in the shell now
 * (`ask()` waits for an in-flight binding; an orphaned watcher says where the answer
 * went and releases the composer), and this helper keeps the assertion honest rather
 * than racing the fix: if the answer is still not on screen after fifteen seconds, a
 * reload must show it, which also proves the citations survive a fresh page load.
 */
async function expectInNewestAnswer(
  page: import("@playwright/test").Page,
  assertion: (scope: import("@playwright/test").Locator) => Promise<unknown>,
) {
  try {
    await assertion(lastAnswer(page));
    return;
  } catch {
    await page.reload();
    await assertion(lastAnswer(page));
  }
}

/**
 * The stable shape of the knowledge tree: node identity, title, parent and position.
 *
 * `progress` / `assessment` legitimately change as a learner works, so they are
 * excluded — what must not change is that the nodes are still the same nodes, in
 * the same places. That is the property a wrong merge would break.
 */
function treeShape(payload: unknown): string {
  const nodes = (Array.isArray(payload) ? payload : []) as Record<string, unknown>[];
  return JSON.stringify(
    nodes
      .map((node) => [node["id"], node["title"], node["parent"] ?? null, node["position"] ?? 0])
      .sort((left, right) => String(left[0]).localeCompare(String(right[0]))),
  );
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

/* ------------------------------------------------------------------ *
 * Module B — CourseEntityResolution (alias retrieval, and no merging)
 * ------------------------------------------------------------------ */

test("a Chinese question reaches English material through an accepted alias", async ({
  page,
  request,
}) => {
  // The fixture's English page never contains the Chinese term, so the only route
  // from "密度聚类" to it is the concept's already-accepted alias (DBSCAN) added to
  // the recall query — deterministic expansion, no model call. What this journey
  // adds over the unit test is that the page reaches the *learner*: it is the
  // material the answer was built from, and it is rendered as a citation chip.
  await bindNode(page);

  const question = "密度聚类是什么？";
  const row = await askAndRead(page, request, question);
  const cards = row.citations ?? [];
  expect(cards.length).toBeGreaterThan(0);

  // The learner's own words survive: the original query is never replaced by its
  // expansion, and the exact locator (had there been one) would outrank it.
  expect(row.user_text).toBe(question);

  const aliased = cards.find((card) => card.name === ALIAS_PAGE);
  expect(
    aliased,
    `no citation for the English page the alias should reach: ${JSON.stringify(
      cards.map((card) => card.name),
    )}`,
  ).toBeTruthy();

  // And the learner sees it, named, next to the answer.
  await expectInNewestAnswer(page, (scope) =>
    expect(scope.locator(".citation-row button").filter({ hasText: ALIAS_PAGE })).toBeVisible({
      timeout: 15_000,
    }),
  );
});

test("one word in two senses is not merged into one concept, and the tree is untouched", async ({
  page,
  request,
}) => {
  await bindNode(page);
  const treeBefore = treeShape(
    await (await request.get(`${UI}/courses/cs3481/knowledge`, { headers: TOKEN })).json(),
  );

  const row = await askAndRead(page, request, "kernel 是什么意思？");
  const cards = row.citations ?? [];
  const svm = cards.find((card) => card.name === KERNEL_SVM_PAGE);
  const operatingSystem = cards.find((card) => card.name === KERNEL_OS_PAGE);
  expect(
    svm && operatingSystem,
    `both senses must stay separately retrievable: ${JSON.stringify(
      cards.map((card) => card.name),
    )}`,
  ).toBeTruthy();

  // Two distinct sources, not one "kernel" concept: different documents, kept side
  // by side rather than collapsed.
  expect(svm?.document_id).not.toBe(operatingSystem?.document_id);

  // The proposal-only relation store may record a guess about these two; what it
  // may never do is change the official tree. Node identity is the authority here.
  const treeAfter = treeShape(
    await (await request.get(`${UI}/courses/cs3481/knowledge`, { headers: TOKEN })).json(),
  );
  expect(treeAfter).toBe(treeBefore);
});

/* ------------------------------------------------------------------ *
 * An exact question number is never replaced by a semantic ranking
 * ------------------------------------------------------------------ */

/** The verified locator behind the first card, if the run named a question at all. */
function referenceOf(card: CitationCard | undefined): {
  questioned?: boolean;
  fields?: { field: string; value: string; status: string }[];
  dropped?: string[];
  jev_calls?: number;
} {
  return (card as { jev_reference?: ReturnType<typeof referenceOf> })?.jev_reference ?? {};
}

test("a named question number is used as a hard filter and is not replaced by ranking", async ({
  page,
  request,
}) => {
  await bindNode(page);

  // The fixture page carries explicit `Question 3` / `(b)` structure, so this really is
  // an exact locator: the parser reads it, module A verifies the label, the structured
  // search filters on the question metadata, and the recalled fragment is placed ahead
  // of the hybrid ranking. What this journey adds over the parser's own unit tests is
  // that the whole chain reaches the learner's citation list — and that the label it
  // used is reported back on the card.
  const row = await askAndRead(page, request, `${LOCATOR_PAGE} Question 3(b) 说明了什么？`);
  const cards = row.citations ?? [];
  expect(cards.length).toBeGreaterThan(0);

  const first = cards[0];
  expect(
    first?.name,
    `the named document must occupy the first slot: ${JSON.stringify(
      cards.map((card) => card.name),
    )}`,
  ).toBe(LOCATOR_PAGE);

  const reference = referenceOf(first);
  expect(reference.questioned).toBe(true);
  expect(reference.dropped).toEqual([]);
  const fields = new Map((reference.fields ?? []).map((item) => [item.field, item.value]));
  expect(fields.get("question_number")).toBe("3");
  expect(fields.get("question_part")).toBe("b");
});

test("a promoted ranking decision still cannot displace an exact question number", async ({
  page,
  request,
}) => {
  // The §16 property that is only *really* tested when the ranking decision is live:
  // with `retrieval.support.v1` promoted the model may reorder the non-exact
  // candidates, and the exact target must keep its slot regardless. Offline, the
  // slot-preservation rule is asserted against a hostile rerank
  // (`test_rerank_exact_target_keeps_slot_under_hostile_rerank`); this is the
  // end-to-end half, which needs the promotion and therefore states it.
  const key = process.env.TYPESAFE_API_KEY ?? "";
  const modes = process.env.JEV_DEFINITION_MODES ?? "";
  test.skip(
    key === "" || !modes.includes("retrieval.support.v1=on"),
    "needs a live TypeSafe credential AND JEV_DEFINITION_MODES=retrieval.support.v1=on in the " +
      "environment Playwright starts the RAG service with",
  );

  await bindNode(page);
  const row = await askAndRead(page, request, `${LOCATOR_PAGE} Question 3(b) 说明了什么？`);
  const cards = row.citations ?? [];
  expect(cards.length).toBeGreaterThan(0);
  expect(
    cards[0]?.name,
    `a live rerank displaced the exact target: ${JSON.stringify(
      cards.map((card) => card.name),
    )}`,
  ).toBe(LOCATOR_PAGE);
  const reference = referenceOf(cards[0]);
  expect(reference.questioned).toBe(true);
  expect(reference.dropped).toEqual([]);
});

/* ------------------------------------------------------------------ *
 * Module C — EvidenceConsistency (condition difference, not deletion)
 * ------------------------------------------------------------------ */

test("fragments from different tasks are reported as such, and both are kept", async ({
  page,
  request,
}) => {
  // The deterministic half of module C: two fragments of the *same* document that
  // answer different tasks carry a code-decided version/task difference, identical
  // under off, shadow and unavailable, so this journey holds with no credential at
  // all. It is the property that matters most — a difference between two figures is
  // *labelled* as a difference of task, and neither fragment is dropped for it.
  await bindNode(page);

  const row = await askAndRead(page, request, "decision threshold 是多少？");
  const cards = row.citations ?? [];
  const sameDocument = (cards ?? []).filter((card) => card.name === THRESHOLD_SECTIONS_PAGE);
  expect(
    sameDocument.length,
    `the two sections of one document must both be delivered: ${JSON.stringify(
      cards.map((card) => card.name),
    )}`,
  ).toBeGreaterThanOrEqual(2);
  for (const card of sameDocument) {
    expect(card.jev_consistency, `${card.id} (${card.locator})`).toBe(
      "VERSION_OR_TASK_DIFFERENCE",
    );
    // Still delivered, with its locator intact: an annotation is never a deletion.
    expect(card.locator).toBeTruthy();
  }
  // The two fragments are distinct parts of that document, not the same one twice.
  expect(new Set(sameDocument.map((card) => card.locator)).size).toBeGreaterThanOrEqual(2);
});

test("a genuine contradiction is surfaced with both fragments kept, never one deleted", async ({
  page,
  request,
}) => {
  // Only a real semantic decision can call two fragments a contradiction in the
  // same context, so this needs the promoted definition *and* a live credential.
  // It is skipped — with its reason — in every other configuration.
  const key = process.env.TYPESAFE_API_KEY ?? "";
  const modes = process.env.JEV_DEFINITION_MODES ?? "";
  test.skip(
    key === "" || !modes.includes("evidence.consistency.v1=on"),
    "needs a live TypeSafe credential AND JEV_DEFINITION_MODES=evidence.consistency.v1=on " +
      "in the environment Playwright starts the RAG service with",
  );

  await bindNode(page);
  const row = await askAndRead(page, request, "默认显著性水平是多少？");
  const cards = row.citations ?? [];
  const conflicting = cards.filter((card) => (card.jev_conflict_with ?? []).length > 0);
  expect(
    conflicting.length,
    `two sources stating 5% and 20% for the same two-sided test were not surfaced as a ` +
      `conflict: ${JSON.stringify(cards.map((card) => [card.name, card.jev_consistency]))}`,
  ).toBeGreaterThanOrEqual(2);

  // Kept, not resolved: the learner gets both fragments and the conflict note the
  // teaching prompt carries, so the disagreement is explained rather than hidden.
  const names = conflicting.map((card) => card.name);
  expect(new Set(names).size).toBeGreaterThanOrEqual(2);
  for (const card of conflicting) {
    expect(card.jev_consistency === "SAME_CONTEXT_CONTRADICTION" || card.jev_conflict_with)
      .toBeTruthy();
  }
});

/* ------------------------------------------------------------------ *
 * Module D — ClaimCitationAudit (a wrong citation is never "supported")
 * ------------------------------------------------------------------ */

test("a figure no cited source states is flagged in code, and the source is still shown", async ({
  page,
  request,
}) => {
  await bindNode(page);

  // The claim asserts a figure no fixture page contains. Layer 2 decides it in
  // code with zero model calls, so this is credential-free — and it is the exact
  // half of module D that used to be dead on this path.
  const unsupported = await askAndRead(
    page,
    request,
    `材料里说默认显著性水平是 ${UNSUPPORTED_FIGURE} 吗？`,
  );
  const cards = unsupported.citations ?? [];
  expect(cards.length).toBeGreaterThan(0);
  for (const card of cards) {
    expect(card.audit_error, `the audit failed on ${card.name}`).toBeUndefined();
    expect(card.support, `${card.name} was not flagged`).toBe(
      "NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE",
    );
    expect(card.audit_layer).toBe("quote");
    expect(card.audit_missing_numbers).toContain(UNSUPPORTED_FIGURE);
  }

  // Nothing was removed for being unsupported: every cited source is still on the card
  // list the client receives, and it stays flagged. Read through the run's own
  // conversation — the same route the pane renders from — rather than from the pane's
  // DOM: the marker *rendering* is covered where it is deterministic (the
  // `citationVerdict` unit tests and the alias journey's chip assertion), because the
  // pane's conversation identity has a separate race recorded in the round-93 block of
  // DSH_JEV_DEEPSEEK_EXECUTION_STATE.md. What matters here is that the verdict reaches
  // the client and that no card is dropped on the way.
  const conversation = (await (
    await request.get(`${UI}/conversations/${unsupported.conversation}`, { headers: TOKEN })
  ).json()) as { messages?: { role: string; citations?: CitationCard[] }[] };
  const answer = (conversation.messages ?? []).filter((m) => m.role === "assistant").pop();
  expect(answer, "the answer is not in the conversation the run reports").toBeTruthy();
  expect(answer?.citations?.length).toBe(cards.length);
  expect(
    (answer?.citations ?? []).every(
      (card) => card.support === "NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE",
    ),
  ).toBe(true);

  // Control: the same shape of question about a figure a page *does* state is not
  // flagged, so the check discriminates instead of condemning every citation.
  const supported = await askAndRead(
    page,
    request,
    `材料里说默认显著性水平是 ${SUPPORTED_FIGURE} 吗？`,
  );
  const control = (supported.citations ?? []).find(
    (card) => card.name === ALPHA_TWO_SIDED_A_PAGE,
  );
  expect(control, "the page stating 5% was not among the cited sources").toBeTruthy();
  expect(control?.support).not.toBe("NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE");
  expect(control?.audit_missing_numbers ?? []).toEqual([]);
});

/* ------------------------------------------------------------------ *
 * Module F — ToolIntentCheck (a side-effecting write and the user's intent)
 * ------------------------------------------------------------------ */

test("a write whose intent check cannot answer is not executed", async ({ request }) => {
  // Fail-closed, and proven deterministically: with the guard on, the agent asks
  // Jev and must not act unless the answer is `ALLOW`. The endpoint is deliberately
  // unreachable in this configuration, so the *unavailable* branch is exercised —
  // not a timeout race. (An earlier attempt pointed the gate at the real endpoint
  // and got `fallback:unavailable` anyway: the live decision took 1.35 s against the
  // guard's 1.5 s default, which is the finding recorded in
  // JEV_SECURITY_AND_FAILURE_MODES.md rather than something to hide behind an
  // assertion that would pass or fail with the model's mood.)
  test.skip(
    TOOL_INTENT_MODE !== "enforce" || process.env.JEV_TOOL_INTENT_UNREACHABLE !== "1",
    "needs the agent started with JEV_TOOL_INTENT_MODE=enforce AND an intentionally " +
      "unreachable JEV_TOOL_INTENT_URL (set JEV_TOOL_INTENT_UNREACHABLE=1 for that run), so the " +
      "fail-closed branch is what is measured",
  );

  const before = await (await request.get(`${AGENT}/api/tasks`, { headers: AGENT_TOKEN })).json();
  const answered = await request.post(`${AGENT}/api/agent/chat`, {
    headers: AGENT_TOKEN,
    data: { message: "add a cs3481 task due 2026-08-20" },
  });
  expect(answered.status()).toBe(200);
  const body = (await answered.json()) as {
    toolResults?: {
      ok?: boolean;
      error?: { code?: string } | null;
      intent?: { verdict?: string; reason?: string; path?: string; jevCalls?: number };
    }[];
  };
  const result = (body.toolResults ?? [])[0];
  expect(result, "no tool was proposed, so this journey proves nothing").toBeTruthy();
  expect(result?.ok).toBe(false);
  expect(["CONFIRMATION_REQUIRED", "INTENT_REFUSED"]).toContain(result?.error?.code ?? "");
  // The refusal is the guard's own record, and it says why: no verdict was reached,
  // and no model call was spent reaching it.
  expect(result?.intent?.path).toBe("fallback:unavailable");
  expect(result?.intent?.verdict).not.toBe("ALLOW");
  expect(result?.intent?.jevCalls).toBe(0);

  const after = await (await request.get(`${AGENT}/api/tasks`, { headers: AGENT_TOKEN })).json();
  expect(after).toEqual(before);
});

test("an explicit, authorised write is not over-blocked once its intent is established", async ({
  request,
}) => {
  const key = process.env.TYPESAFE_API_KEY ?? "";
  const modes = process.env.JEV_DEFINITION_MODES ?? "";
  test.skip(
    TOOL_INTENT_MODE !== "enforce" || key === "" || !modes.includes("tool.intent.v1=on"),
    "needs JEV_TOOL_INTENT_MODE=enforce AND a live TypeSafe credential AND " +
      "JEV_DEFINITION_MODES=tool.intent.v1=on — the other half of the guard, which must not " +
      "turn an unambiguous request into a refusal",
  );
  // The guard's own budget has to be generous enough for a real decision: the live
  // call measured 0.68–1.35 s against a 1.5 s default, so this journey states the
  // requirement instead of silently measuring the timeout. The agent's own bound is
  // 100–10 000 ms.
  expect(
    Number(process.env.JEV_TOOL_INTENT_TIMEOUT_MS ?? "0"),
    "JEV_TOOL_INTENT_TIMEOUT_MS must be raised for this journey (see the run script); " +
      "at the 1.5 s default a real decision can be cut off and the write blocked",
  ).toBeGreaterThanOrEqual(5000);

  const answered = await request.post(`${AGENT}/api/agent/chat`, {
    headers: AGENT_TOKEN,
    data: { message: "add a cs3481 task due 2026-08-20" },
  });
  expect(answered.status()).toBe(200);
  const body = (await answered.json()) as {
    toolResults?: { ok?: boolean; data?: { id?: string; title?: string } }[];
  };
  const result = (body.toolResults ?? [])[0];
  expect(result?.ok, JSON.stringify(body)).toBe(true);
  expect(result?.data?.id ?? "").not.toBe("");
});
