export type Major = "CS" | "SMART_MANUFACTURING" | "MATERIALS" | "ENERGY";
export type Mode = "AUTO" | "TEACHING" | "PROBLEM";
export type KnowledgeNodeKind = "ATOMIC" | "COMPOSITE";
export type KnowledgeSource = "CANONICAL" | "PRIVATE";
export type LearningProgressStatus = "NOT_STARTED" | "LEARNING" | "LEARNED" | "SPEC_UNAVAILABLE";
export interface LearningProgress {
  status: LearningProgressStatus;
  spec_version: number | null;
  required_total: number;
  covered_required: number;
  atomic_descendant_count?: number;
  historical_learned_spec_versions: number[];
}
export interface AssessmentState {
  status: "NOT_ASSESSED" | "IN_PROGRESS" | "SUBMITTED" | "NEEDS_REVIEW" | "GRADED" | "PARTIALLY_ASSESSED";
  raw_score: number | null;
  grade_label: string | null;
  numeric_value?: number | null;
  mapping_status?: "CONFIGURED" | "UNCONFIGURED" | "COMPOSITE_RAW_ONLY";
  independent_eligible?: boolean;
  session_id?: string;
  mode?: "INDEPENDENT" | "PRACTICE";
  assistance_status?: "UNASSISTED" | "ASSISTED" | "ANSWER_EXPOSED";
  assessed_atomic_count?: number;
  atomic_descendant_count?: number;
}
export interface KnowledgeNodeState { learning: LearningProgress; assessment: AssessmentState }
export interface LearningNode {
  id: string;
  title: string;
  description: string;
  status: string;
  progress: LearningProgressStatus;
  major: Major;
  kind: KnowledgeNodeKind;
  source: KnowledgeSource;
  learning: LearningProgress;
  assessment: AssessmentState;
}
export interface KnowledgeLink {
  id: string;
  resolution_status: "VALIDATED" | "UNRESOLVED" | "LEGACY_PRESERVED";
  node_id: string | null;
  spec_version: number | null;
  item_id: string | null;
  question_text: string;
  reason: string;
  unresolved_reason: string | null;
}
export interface SolutionStep {
  id: string;
  ordinal: number;
  operation: string;
  result: string;
  explanation: string;
  formulae: string[];
  units: string[];
  check: string | null;
  knowledge_links: KnowledgeLink[];
  source_refs: string[];
}
export interface ProblemSource {
  id: string;
  document_version_id: string;
  document_sha256: string;
  filename: string;
  source_scope: "OFFICIAL" | "OWNER_COURSE" | "WORKSPACE_PRIVATE";
  question_number: string;
  question_part: string | null;
  heading_path: string | null;
  locator_type: string;
  locator_value: string;
  question_text: string;
}
export interface LearningDocumentSource {
  id: string;
  filename: string;
  extension: string;
  version_id?: string;
  version_number?: number;
  source_scope?: "OFFICIAL" | "OWNER_COURSE" | "WORKSPACE_PRIVATE";
  status: string;
}
export interface Solution {
  id: string;
  status?: string;
  question: string;
  exam_answer: string;
  conditions: string[];
  steps: SolutionStep[];
  answer_origin: string;
  verification: string;
  assumptions: string[];
  common_mistakes: string[];
  question_transcription: string | null;
  visual_uncertainties: string[];
  input_kind: "TEXT" | "INDEXED" | "IMAGE";
  problem_index_entry_id: string | null;
  input_document_version_id: string | null;
  sources: { id: string; document_version_id: string; locator_type: string; locator_value: string }[];
}
export interface Bridge {
  id: string;
  status: string;
  node_id: string;
  knowledge_link_id?: string;
  selected_question?: string;
  reason_for_learning?: string;
  return_anchor: string;
  problem_snapshot: { question: string; conditions: string[]; step: SolutionStep };
}
export interface ComprehensionCheck {
  check_id: string;
  kind: "DEFINITION" | "DISTINCTION" | "ENGLISH" | "APPLICATION" | "SYNTHESIS";
  prompt: string;
}
export interface Unit {
  id: string;
  status?: string;
  sections: { section_id: string; title: string; content: string }[];
  uncertainties: string[];
  comprehension_checks?: ComprehensionCheck[];
  display?: { question_prefix: string | null };
  plan_version?: number;
  plan_unit_key?: string;
  plan_reused?: boolean;
  remediation_trigger_ids?: string[];
}
export type AssessmentStatus = "IN_PROGRESS" | "SUBMITTED" | "GRADED" | "ABANDONED" | "INVALIDATED";
export interface AssessmentQuestionReview {
  submitted_answer: string | null;
  answer: Record<string, unknown>;
  awarded_marks: number | null;
  feedback: string | null;
  rubric: {
    criterion_id: string;
    dimension: string;
    max_fraction: number;
    description: string;
  }[];
}
export interface AssessmentQuestion {
  id: string;
  question_revision_id: string;
  ordinal: number;
  family_id: string;
  marks: number;
  source_kind: "OFFICIAL" | "WORKSPACE_PRIVATE" | "MODEL_GENERATED" | "EXTERNAL_INSPIRED";
  verification_method: string;
  question_type: "MCQ_SINGLE" | "NUMERIC" | "SHORT_TEXT" | "EXPLANATION" | "CODE";
  difficulty: number;
  prompt: string;
  options: string[];
  attempt_status: string;
  assistance: "NONE" | "HINT" | "TEACHING" | "ANSWER_REVEALED";
  review?: AssessmentQuestionReview;
}
export interface PerformanceEvidence {
  id: string;
  question_attempt_id: string;
  criterion_id: string;
  node_id: string;
  spec_version: number;
  item_id: string;
  dimension: string;
  awarded_marks: number;
  max_marks: number;
  confidence: number;
  independent_eligible: boolean;
  performance_band: "STRONG" | "DEVELOPING" | "WEAK" | "NEEDS_REVIEW";
}
export interface AssessmentSession {
  id: string;
  workspace_id: string;
  node_id: string;
  blueprint_id: string;
  blueprint_version: number;
  blueprint_hash: string;
  spec_version: number;
  status: AssessmentStatus;
  mode: "INDEPENDENT" | "PRACTICE";
  assistance_status: "UNASSISTED" | "ASSISTED" | "ANSWER_EXPOSED";
  raw_score: number | null;
  independent_eligible: boolean;
  grade: {
    mapping_status: "CONFIGURED" | "UNCONFIGURED";
    label: string | null;
    numeric_value: number | null;
    message: string;
  };
  grade_policy: { id: string; name: string; provenance: string };
  questions: AssessmentQuestion[];
  performance_evidence: PerformanceEvidence[];
  assistance_message?: string;
  started_at: string;
  submitted_at: string | null;
  graded_at: string | null;
}
export interface AssessmentAnswerDraft { blueprint_item_id: string; answer: string }
export interface LayoutPreference { orientation: "columns" | "rows"; swapped: boolean; ratio: number }
export interface KnowledgeRegistryNode {
  id: string;
  title: string;
  description: string;
  major: Major;
  kind: KnowledgeNodeKind;
  status: string;
  source: KnowledgeSource;
  aliases: string[];
  state: KnowledgeNodeState;
}
export interface KnowledgeTreeMember {
  node_id: string;
  parent_node_id: string | null;
  ordinal: number;
  spec_version: number | null;
  title: string;
  description: string;
  major: Major;
  kind: KnowledgeNodeKind;
  source: KnowledgeSource;
  state: KnowledgeNodeState;
}
export interface KnowledgeTree {
  id?: string;
  kind?: "OFFICIAL" | "PERSONALIZED";
  status: "NO_REVIEWED_TREE" | "NOT_CREATED" | "PUBLISHED" | "ACTIVE";
  version?: number;
  title?: string;
  change_reason?: string;
  base_tree_version_id?: string | null;
  members: KnowledgeTreeMember[];
  prerequisites: { node_id: string; prerequisite_node_id: string }[];
}
export interface KnowledgeSnapshot {
  workspace_id: string;
  course_id: string;
  revision: number;
  selected_tree: "NONE" | "OFFICIAL" | "PERSONALIZED";
  official_tree: KnowledgeTree;
  personalized_tree: KnowledgeTree;
  registry: KnowledgeRegistryNode[];
}
export interface PersonalPlanDraft {
  title: string;
  change_reason: string;
  memberships: {
    node_id: string;
    parent_node_id: string | null;
    ordinal: number;
    spec_version?: number;
  }[];
  prerequisites: { node_id: string; prerequisite_node_id: string }[];
}
export interface LearningState {
  id: string; course_id: string; revision: number; mode: Mode; layout: Partial<LayoutPreference>;
  cursor: { node_id?: string; step_id?: string; solution_id?: string; unit_id?: string; bridge_id?: string; assessment_session_id?: string; pane?: string };
  nodes: LearningNode[]; solutions: Solution[]; bridges: Bridge[]; units: Unit[];
  operations: { id: string; kind: string; status: string }[];
}
