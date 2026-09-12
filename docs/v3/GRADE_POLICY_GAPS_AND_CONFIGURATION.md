# CourseMate V3 — Grade Policy Gaps and Configuration

Version: Stage 5 implemented policy contract, 2026-09-12.
Current implementation status: `SOURCE_IMPLEMENTED / LOCAL_CONTRACT_VERIFIED`; no production policy is configured or claimed.

## 1. What the source actually supplies

The raw requirement calls the labels “CityU / GPA style”; it does not provide an authoritative institutional policy document. It lists these labels and numeric values:

| Letter | Source numeric value | Configuration state |
|---|---:|---|
| A+ | 4.3 | supplied |
| A | 3.7 | supplied |
| A- | **not supplied** | `UNCONFIGURED` |
| B+ | 3.3 | supplied |
| B | 3.0 | supplied |
| B- | 2.7 | supplied |
| C+ | 2.3 | supplied |
| C | 2.0 | supplied |
| C- | 1.7 | supplied |
| D | 1.4 | supplied |
| E | 1.0 | supplied |
| F | 0.0 | supplied |

It also includes the statement `> 4.0 → A+`, but does not define complete raw-score percentage thresholds, rounding, boundary inclusivity, pass rules, aggregation periods or retake policy. Those remain `UNCONFIGURED`.

CourseMate must not invent A- as 3.7, 4.0 or any other value, must not infer percentage bands, and must not label the draft “CityU official GPA.”

## 2. Independent state axes

```text
Learning Progress = NOT_STARTED | LEARNING | LEARNED
Assessment State  = NOT_ASSESSED | IN_PROGRESS | SUBMITTED | GRADED | ...
Grade             = raw score + rubric evidence + optional configured letter/GPA
```

`LEARNED` is derived only from REQUIRED Teaching coverage. A legal record may be `LEARNED + C-`, `NOT_STARTED + high prior diagnostic`, or `LEARNED + NOT_ASSESSED`. Neither axis overwrites the other.

## 3. GradePolicyVersion implemented contract

```text
id
scope_type: PLATFORM | COURSE | NODE
scope_id
version
status: DRAFT_UNCONFIGURED | DRAFT_VALID | PUBLISHED | RETIRED
display_name
provenance_label
numeric_scale[]: {letter, numeric_value|null}
raw_score_bands[]: {letter, minimum, maximum}
rounding_rule|null
pass_rule|null
retake_rule|null
created_by / created_at
published_by / published_at
supersedes_policy_id|null
```

`SUPPLEMENTAL_ENGINEERING_DECISION`: policies are immutable after publication. Editing creates a new version. Assessment Blueprint and GradeSnapshot pin the exact policy version so later policy changes do not rewrite history.

## 4. Validation and behavior

Draft save may preserve missing values. Publish requires all enabled outputs to pass:

- unique letter labels and one numeric value per required label;
- A- configured if A- is enabled;
- monotonic numeric ordering with an explicit exception mechanism, never silent repair;
- raw-score bands cover exactly the configured range without gaps/overlap;
- inclusive/exclusive boundaries and rounding are explicit;
- source/provenance wording does not claim institutional authority without evidence;
- policy scope is authorized and publication is audited.

If policy is incomplete:

```text
Raw Score: available after a valid submitted assessment
Rubric Evidence: available
Weak Points: available with confidence/source labels
Letter Grade: 评分映射待配置 / GRADE_MAPPING_UNCONFIGURED
Numeric GPA: unavailable
Learning Progress: unaffected
```

Unsubmitted/interrupted sessions are not zero or F. `NOT_ASSESSED` is a state, not numeric `0`.

## 5. Default assessment blueprint policy

Each ATOMIC node assessment freezes exactly five questions. Marks must be positive integers, not all equal, and total exactly 100. The current default selector assigns `10/15/20/25/30`; SQLite independently rejects any frozen Blueprint that is not exactly five, totals other than 100 or has all-equal marks. Future node-specific weighting requires a new versioned selection policy, not mutation of a frozen Blueprint.

Frozen Blueprint contains:

- node/tree/Spec versions and intended knowledge/rubric coverage;
- five immutable question revision IDs and family IDs;
- marks and Rubric version per question;
- origin/scope/visibility and exposure history;
- assistance policy and independent-evidence eligibility;
- GradePolicy version or explicit unconfigured state;
- generation/selection algorithm and random seed/reference where applicable.

Answers and Rubrics remain server-side before submission.

## 6. GradeSnapshot implemented behavior

The backend computes awarded marks from validated criterion proposals and clamps/rejects impossible totals. The model may explain semantic evidence but cannot perform the authoritative sum or select a GradePolicy.

Snapshot pins:

```text
assessment session + blueprint + question/attempt/rubric revisions
assistance/exposure qualification
per-criterion awarded marks and evidence
raw score / 100
GradePolicyVersion or UNCONFIGURED reason
letter/numeric value only when deterministically resolved
created timestamp and supersession link
```

Fine-grained PerformanceEvidence records concept, terminology, method/reasoning, calculation, derivation, code/application, clarity and node-specific dimensions without forcing every major into the same rubric.

## 7. Required tests

1. five questions, unequal marks, total 100; equal/zero/negative/wrong total rejected;
2. natural-language grader output references only frozen rubric criteria;
3. backend rejects sum mismatch, invented criterion or out-of-range award;
4. A- null and missing bands round-trip without fabricated defaults;
5. incomplete draft previews but cannot publish or emit letter/GPA;
6. later completed policy does not rewrite an older GradeSnapshot;
7. unsubmitted/abandoned remains ungraded, not F;
8. answer-exposed/assisted attempt is excluded from independent grade/readiness;
9. Learning Progress remains unchanged for every grade outcome;
10. parent COMPOSITE aggregation documents missing/uncertain children and never writes contradictory mastery.

All ten contract families have local deterministic coverage in `test_assessment_runtime.py`; the current focused file reports 13 passing tests, including server-answer-column denial, abandoned-answer secrecy and exposed-family retest guards. This is not evidence of live semantic grading quality or production configuration. Human finalization of `NEEDS_REVIEW`, author/reviewer UI and integrated COMPOSITE exams remain future work.

## 8. Minimal Owner action, deferred

Before Letter/GPA production activation, the Owner must provide or approve:

- A- numeric value;
- complete percentage-to-letter bands and boundary/rounding rules;
- pass/retake/aggregation behavior if desired;
- the precise non-misleading policy display name and provenance.

This missing policy does not block raw score, Rubric, performance evidence, `NOT_ASSESSED`, test workflows or local implementation.

The repository seed `gp_requirements_draft_v1` is therefore intentionally `DRAFT_UNCONFIGURED`, has no raw-score bands, keeps A- numeric value null and says “Requirements draft; not an institutional policy.” Admin endpoints can create and preview a later version, but publish rejects incomplete mappings and unverified institutional claims. Frozen Blueprints retain their exact old policy binding.
