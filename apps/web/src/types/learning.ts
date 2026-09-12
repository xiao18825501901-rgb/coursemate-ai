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
  status: "NOT_ASSESSED" | "IN_PROGRESS" | "GRADED" | "UNCONFIGURED";
  raw_score: number | null;
  grade_label: string | null;
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
}
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
  cursor: { node_id?: string; step_id?: string; solution_id?: string; unit_id?: string; bridge_id?: string; pane?: string };
  nodes: LearningNode[]; solutions: Solution[]; bridges: Bridge[]; units: Unit[];
  operations: { id: string; kind: string; status: string }[];
}
