// M6F student acceptance verifier. Consumes the frozen student-API response
// bodies captured by m6f_student_acceptance_driver.mjs and asserts, with no
// browser or login, that the student-facing knowledge endpoint serves exactly
// the newly published V3 OFFICIAL trees.
import fs from "node:fs";
import path from "node:path";

const WORK = path.join(process.cwd(), "work");
const EXPECTED = {
  cs3481: { tree: "official-tree-15fd76815c754d148064e5e8872ad35c", members: 22, specs: 15 },
  ge2324: { tree: "official-tree-168ad777b4a549debd6614d75c77a09d", members: 21, specs: 14 },
};

function newest(prefix) {
  const files = fs.readdirSync(WORK)
    .filter((f) => f.startsWith(prefix) && f.endsWith(".json"))
    .map((f) => ({ f, t: fs.statSync(path.join(WORK, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  return files.length ? path.join(WORK, files[0].f) : null;
}

const verdict = { checked_at: new Date().toISOString(), courses: {}, acceptance: "FAIL" };

for (const courseId of Object.keys(EXPECTED)) {
  const file = newest(`m6f-student-knowledge-${courseId}-`);
  if (!file) {
    verdict.courses[courseId] = { error: "no captured student response found" };
    continue;
  }
  const body = JSON.parse(fs.readFileSync(file, "utf8"));
  const tree = body.official_tree ?? null;
  const members = Array.isArray(tree?.members) ? tree.members : [];
  const composites = members.filter((m) => m.kind === "COMPOSITE").length;
  const atomics = members.filter((m) => m.kind === "ATOMIC").length;
  const withSpec = members.filter((m) => m.spec_version !== null && m.spec_version !== undefined).length;
  const sources = [...new Set(members.map((m) => m.source))];
  const checks = {
    official_tree_present: !!tree,
    tree_id_matches_published_v3: tree?.id === EXPECTED[courseId].tree,
    tree_status_published: tree?.status === "PUBLISHED",
    tree_version_is_v3: tree?.version === 3,
    member_count_matches: members.length === EXPECTED[courseId].members,
    composite_atomic_split: composites + atomics === members.length,
    spec_versions_on_atomic_members: withSpec === EXPECTED[courseId].specs,
    all_members_canonical: sources.length === 1 && sources[0] === "CANONICAL",
    selected_tree_is_official: body.selected_tree === "OFFICIAL",
    no_private_or_candidate_source: members.every((m) => m.source === "CANONICAL"),
  };
  const pass = Object.values(checks).every(Boolean);
  verdict.courses[courseId] = {
    evidence_file: file,
    workspace_id: body.workspace_id,
    selected_tree: body.selected_tree,
    official_tree_id: tree?.id ?? null,
    official_tree_status: tree?.status ?? null,
    official_tree_version: tree?.version ?? null,
    title: tree?.title ?? null,
    member_count: members.length,
    expected_member_count: EXPECTED[courseId].members,
    composite_count: composites,
    atomic_count: atomics,
    spec_version_count: withSpec,
    sample_titles: members.slice(0, 5).map((m) => m.title),
    checks,
    pass,
  };
  console.log(`STUDENT_ACCEPTANCE ${courseId} pass=${pass} tree=${tree?.id ?? "MISSING"} status=${tree?.status ?? "-"} members=${members.length}/${EXPECTED[courseId].members} atomic=${atomics} composite=${composites} specs=${withSpec}`);
  if (!pass) {
    console.log(`  failing checks: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(", ")}`);
  }
}

verdict.acceptance = Object.values(verdict.courses).every((c) => c.pass) ? "PASS" : "FAIL";
const out = path.join(WORK, `m6f-student-acceptance-verdict-${Date.now()}.json`);
fs.writeFileSync(out, JSON.stringify(verdict, null, 2));
console.log("STUDENT_ACCEPTANCE_VERDICT", verdict.acceptance);
console.log("VERDICT_SAVED", out);
process.exit(verdict.acceptance === "PASS" ? 0 : 4);
